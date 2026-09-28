#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Trending 抓取 + 多渠道推送（企业微信群机器人 / SMTP 邮件）。
运行环境：GitHub Actions（境外，能稳定访问 github.com）。
本地也可直接 `python gen_rank.py` 验证抓取（无 secret 时仅生成 rank.md，不推送）。
"""
import os
import re
import sys
import json
import time
import datetime
import urllib.request
from email.mime.text import MIMEText
from email.utils import formataddr
import smtplib
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

_LANG_RE = re.compile(r"^[a-z][a-z0-9+#-]*$")


def _norm_lang(v):
    """净化语言参数。

    🔴 绝不能读系统的 LANG / LC_ALL！它们是 POSIX 区域设置变量（Linux/macOS/Git-Bash
    默认为 C.UTF-8、en_US.UTF-8 之类），一旦被当成语言拼进 URL 就会变成
    `github.com/trending?l=C.UTF-8&since=weekly` —— GitHub 对未知语言返回**空榜**，
    脚本会静默抓到 0 条。GitHub Actions runner 同样自带 LANG，故这里是必踩坑。
    本函数只放行纯小写语言名（python / rust / go / c++ / c# …）。
    """
    if not v:
        return None
    v = str(v).strip()
    if not _LANG_RE.match(v):
        print(f"[warn] 忽略非法语言参数 {v!r}（应为 python/rust/go 这类小写语言名），已按全语言处理")
        return None
    return v


def _load_dotenv(path=".env"):
    """依赖-free 读取本地 .env 到环境变量（仅当该变量尚未设置时）。
    本地运行用；GitHub Actions 中真实 Secrets 优先，不受影响。"""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                os.environ.setdefault(k, v)
    except FileNotFoundError:
        pass


def fetch_trending(since="weekly", lang=None, retries=3):
    lang = _norm_lang(lang)          # 🔴 必须净化，否则系统 LANG 会污染 URL
    url = "https://github.com/trending"
    url += f"?l={lang}&" if lang else "?"
    url += f"since={since}"
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8")
            soup = BeautifulSoup(html, "html.parser")
            items = []
            for row in soup.select("article.Box-row")[:20]:
                a = row.select_one("h2 a")
                repo = a["href"].strip("/") if a else "?"
                desc_el = row.select_one("p")
                desc = desc_el.get_text(strip=True) if desc_el else ""
                star_el = row.select_one('a[href$="/stargazers"]')
                stars = star_el.get_text(strip=True) if star_el else "?"
                wk_el = row.select_one("span.d-inline-block.float-sm-right")
                wk = wk_el.get_text(strip=True) if wk_el else ""
                items.append({"repo": repo, "stars": stars, "week": wk, "desc": desc})
            if not items:  # 命中限流/软封页，退避重试
                last_err = "返回空榜（可能命中限流或软封页）"
                print(f"[retry {attempt}/{retries}] 空榜，{5 * attempt}s 后重试  URL={url}")
                time.sleep(5 * attempt)
                continue
            return items
        except Exception as e:  # 断流/超时，退避重试
            last_err = f"{type(e).__name__}: {str(e)[:120]}"
            print(f"[retry {attempt}/{retries}] {last_err}")
            time.sleep(5 * attempt)
    raise RuntimeError(f"抓取失败（已重试 {retries} 次，URL={url}）：{last_err}")



def _period_cn(since):
    return {"daily": "日", "weekly": "周", "monthly": "月"}.get(since, since)


def _parse_weekly(wk):
    """从 '12,590 stars this week' 这类文案里抠出周增量整数（去千分位逗号）。

    用于「按本周 star 增量降序」排序，而非照搬 GitHub 官方 trending 页的
    不透明顺序。daily/monthly 文案同理（'stars today' / 'stars this month'），
    正则只取首个数字即正确。解析失败回落 0（沉底）。"""
    if not wk:
        return 0
    m = re.search(r"([\d,]+)", wk)
    if not m:
        return 0
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return 0


# ===== 视角三：AI 应用层周榜 =====
# GitHub 官方不支持“按主题(如 AI)筛选趋势”，只支持按语言。故抓 AI 重仓语言周榜
# 合并去重，宽松判定 AI 类并分级（应用层优先，新手友好）。
AI_LANGS = ["python", "typescript", "javascript", "jupyter", "rust", "c++", "go"]
WATCHLIST = []   # 留空=不强制置顶任何仓库；以后要长期盯某个 repo 时往里加，例如 ["owner/name"]

_AI_KW = re.compile(
    r"\b(ai|a\.i\.|llm|llms|gpt|chatgpt|claude|gemini|copilot|rag|ml|machine learning|"
    r"deep learning|neural|diffusion|transformer|model|models|embedding|prompt|chatbot|"
    r"assistant|openai|anthropic|ollama|vllm|langchain|mcp|multimodal|vision|speech|tts|"
    r"asr|whisper|video generation|image generation|genai|generative|qwen|deepseek|"
    r"mistral|llama|glm|hunyuan|kimi|yuanbao)\b", re.I)
_APP_KW = re.compile(
    r"\b(agent|agents|cli|tool|sdk|self-hosted|selfhosted|extension|plugin|bot|workflow|"
    r"app|ui|studio|platform|engine|generator|framework|library|wrapper|api|server|"
    r"client|alternative|替代|自动化|助手|机器人)\b", re.I)
_RESEARCH_KW = re.compile(
    r"\b(paper|survey|dataset|benchmark|weights|checkpoint|pretrain|pretraining|arxiv|"
    r"fine-tun|fine-tune|sft|rlhf|thesis|academic|evaluation)\b", re.I)
_NON_AI_KW = re.compile(r"\b(blog|portfolio|boilerplate|cooking|recipe|pet|tamagotchi)\b", re.I)


def _is_ai(repo, desc):
    """宽松判定：你关注的仓库恒 True；含 AI 关键词 True；明确非 AI 且无 AI 信号才 False。
    其余（抓的多为 AI/工具向语言）默认包含，宁滥勿漏，避免 hypit 这类‘没写 AI 二字’被漏。"""
    if repo in WATCHLIST:
        return True
    if _AI_KW.search(desc):
        return True
    if _NON_AI_KW.search(desc) and not _AI_KW.search(desc):
        return False
    return True


def _grade(desc):
    """分级：命中研究关键词 → 研究层；否则默认应用层（新手友好，能直接上手的轮子优先）。"""
    if _RESEARCH_KW.search(desc):
        return "research"
    return "app"


def _ai_badge(it):
    grade = _grade(it["desc"])
    badge = "🔬 研究层" if grade == "research" else "🛠️ 应用层"
    if it["repo"] in WATCHLIST:
        badge = "👁 " + badge
    return badge


def _fetch_repo_stars(repo):
    """watchlist 兜底：当周未进任何语言榜时，拉一次总星数用于展示。失败返回 None。"""
    url = f"https://github.com/{repo}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8")
        m = re.search(r"([\d,]+)\s+users? starred this repository", html)
        if m:
            return m.group(1)
        m2 = re.search(r'id="repo-stars-counter-star"[^>]*title="([\d,]+)"', html)
        if m2:
            return m2.group(1)
    except Exception:
        pass
    return None


def _ai_sort_key(it):
    badge = it.get("badge", "")
    # 优先级数字越大越靠前（配合 reverse=True）：3=你关注 > 2=应用层 > 1=研究层
    grp = 3 if "👁" in badge else (2 if "🛠️" in badge else 1)
    return (grp, _parse_weekly(it["week"]))


def fetch_ai_board(since="weekly"):
    """抓多语言周榜 → 合并去重 → 宽松判 AI → 分级 → 排序，产出视角三。"""
    merged = {}
    for lang in AI_LANGS:
        try:
            items = fetch_trending(since, lang)
        except Exception as e:
            print(f"[ai] 语言 {lang} 抓取失败，跳过：{e}")
            continue
        for it in items:
            repo = it["repo"]
            if repo in merged:
                if _parse_weekly(it["week"]) > _parse_weekly(merged[repo]["week"]):
                    merged[repo] = it
            else:
                merged[repo] = it
        time.sleep(1)   # 礼貌节流，避免触发限流
    board = []
    for repo, it in merged.items():
        if not _is_ai(repo, it["desc"]):
            continue
        it["badge"] = _ai_badge(it)
        board.append(it)
    # watchlist 兜底：当周未进任何语言榜也要显示
    for repo in WATCHLIST:
        if repo not in merged:
            stars = _fetch_repo_stars(repo) or "?"
            board.append({
                "repo": repo, "stars": stars, "week": "本周未进语言趋势榜",
                "desc": "你关注的仓库，当前未出现在任何语言周榜", "badge": "👁 关注",
            })
    board.sort(key=_ai_sort_key, reverse=True)
    return board


# 双视角说明文案（邮件 / rank.md 共用）
GROWTH_NOTE = "排序：按本周 star 增量降序（谁涨得多谁靠前）"
OFFICIAL_NOTE = "排序：照搬 github.com/trending 官方顺序（GitHub 自家算法，非纯增量）"
OFFICIAL_TITLE = "GitHub 官方 trending 原顺序（未重排）"
# 视角三：AI 应用层周榜
AI_NOTE = "排序：👁 你关注的置顶 → 🛠️ 应用层优先 → 🔬 研究层靠后；各组内按本周 star 增量降序。多语言(py/ts/js/jupyter/rust/c++/go)周榜合并去重，宽松判定 AI 类（宁滥勿漏）。"
AI_TITLE = "视角三 · AI 应用层周榜（可直接上手的轮子优先）"

# 视角四：Agent Skills 7天飙升榜（数据来自 LinklyAI/best-skills 开源聚合，CC BY 4.0）
# GitHub 官方无“skill”维度趋势，best-skills 每日聚合 skills.sh/ClawHub/腾讯SkillHub/
# GitHub/X 等多生态，给出“7天增长最快”的 skill 排名。raw CSV 公开免鉴权，Actions runner 可直抓。
SKILLS_CSV_URL = ("https://raw.githubusercontent.com/LinklyAI/best-skills/main/"
                   "data/latest/rankings/trending-7d.csv")
SKILLS_TOP = 100         # 邮件/rank.md 展示条数（CSV 含 Top100，取前 N 防过长）
SKILLS_TITLE = "视角四 · Agent Skills 7天飙升榜（best-skills 跨生态聚合）"
SKILLS_NOTE = ("数据来源 LinklyAI/best-skills（CC BY 4.0），每日更新；按 7 天安装增速降序。"
               "厂商=发布方，分类=技能类型，本周安装=近7天新增安装，增长率=周环比 %。"
               "链接优先跳 GitHub 仓库，无则跳 skills.sh 页面。"
               "【用途】列由 skill 名+分类本地派生（源 CSV 无简介字段），辅助快速判断是干啥的。")

# 视角四：分类 → 中文标签（category 字段有值，但为英文，翻译后更易读）
_SKILL_CAT_CN = {
    "design-media": "设计/媒体",
    "content-creation": "内容创作",
    "ai-agent": "AI 智能体",
    "dev-tools": "开发工具",
    "productivity": "效率",
    "data": "数据",
    "research": "研究",
    "automation": "自动化",
}
# 视角四：skill 名 token → 中文（覆盖 best-skills 高频词；未命中保留原文）
_SKILL_TOKEN_CN = {
    "ai": "AI", "video": "视频", "generation": "生成", "generate": "生成",
    "image": "图像", "images": "图像", "audio": "音频", "music": "音乐",
    "avatar": "虚拟形象", "reference": "参考", "to": "→", "seedance": "Seedance",
    "wan": "万相", "prime": "旗舰", "media": "媒体", "use": "使用", "edit": "剪辑",
    "editing": "剪辑", "twitter": "Twitter/X", "reddit": "Reddit",
    "automation": "自动化", "google": "Google", "agents": "智能体", "agent": "智能体",
    "cli": "命令行", "adk": "ADK", "code": "编码", "eval": "评估",
    "evaluation": "评估", "workflow": "工作流", "observability": "可观测性",
    "scaffold": "脚手架", "publish": "发布", "deploy": "部署", "find": "查找",
    "skills": "技能", "design": "设计", "mobile": "移动端", "apps": "应用",
    "app": "应用", "ios": "iOS", "ui": "UI", "taste": "审美", "heygen": "HeyGen",
    "hyperframes": "HyperFrames", "genmedia": "GenMedia", "labs": "实验室", "qu": "Qu",
    "vercel": "Vercel", "kimi": "Kimi", "deepseek": "DeepSeek", "claude": "Claude",
    "openai": "OpenAI", "llama": "Llama", "mistral": "Mistral", "glm": "GLM",
    "hunyuan": "混元", "qwen": "通义千问", "chatgpt": "ChatGPT", "gemini": "Gemini",
    "copilot": "Copilot", "translate": "翻译", "transcription": "转写",
    "speech": "语音", "ocr": "OCR", "pdf": "PDF", "search": "搜索", "rag": "RAG",
    "bot": "机器人", "scraper": "爬虫", "crawler": "爬虫", "api": "API",
    "sdk": "SDK", "server": "服务", "client": "客户端", "wrapper": "封装",
}


def _skill_brief(name, category):
    """本地派生中文简述：分类标签 + skill 名逐 token 翻译。零网络、零额外请求。
    源 CSV 的 description/description_zh 两列 100% 为空，故用名字面救命。"""
    cat_cn = _SKILL_CAT_CN.get((category or "").strip().lower(), category or "")
    tokens = [t for t in (name or "").split("-") if t]
    parts = []
    for t in tokens:
        parts.append(_SKILL_TOKEN_CN.get(t.lower(), t))
    # “→” 前后不空格；其余 token 用空格连接
    name_cn = " ".join(parts).replace(" → ", "→")
    # 相邻中文 token 去空格（“AI 视频 生成”→“AI 视频生成”），更易读
    name_cn = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", name_cn)
    if cat_cn:
        return f"[{cat_cn}] {name_cn}"
    return name_cn


def fetch_skills_trending(top=SKILLS_TOP, retries=3):
    """抓 best-skills 的 trending-7d.csv → 解析 → 取前 top 条，产出视角四。
    失败（限流/断流）返回 []，不抛异常（避免拖垮整封邮件）。"""
    import csv, io
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(SKILLS_CSV_URL, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                text = resp.read().decode("utf-8")
            rows = list(csv.DictReader(io.StringIO(text)))
            items = []
            for r in rows[:top]:
                items.append({
                    "name": (r.get("skill") or "?").strip(),
                    "vendor": (r.get("vendor") or "").strip(),
                    "category": (r.get("category") or "").strip(),
                    "weekly_recent": (r.get("weekly_recent") or "").strip(),
                    "weekly_prev": (r.get("weekly_prev") or "").strip(),
                    "growth_pct": (r.get("growth_pct") or "").strip(),
                    "desc_zh": (r.get("description_zh") or r.get("description") or "").strip(),
                    "brief": _skill_brief(r.get("skill") or "", r.get("category") or ""),
                    "url": (r.get("repo_url") or r.get("url") or "").strip(),
                })
            print(f"[skills] 抓取 {len(items)} 条 Agent Skills（trending-7d）")
            return items
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:120]}"
            print(f"[skills][retry {attempt}/{retries}] {last_err}")
            time.sleep(3 * attempt)
    print(f"[skills] 抓取失败（已重试 {retries} 次）：{last_err} → 视角四为空")
    return []


def skills_md_block(items, title, sort_note=""):
    lines = [f"## {title}", "> 数据来源 LinklyAI/best-skills（CC BY 4.0）"]
    if sort_note:
        lines.append(f"> {sort_note}")
    lines.append("")
    for i, it in enumerate(items, 1):
        link = it["url"] or f"https://skills.sh/{it['name']}"
        vp = f" · 厂商 {it['vendor']}" if it["vendor"] else ""
        cat = f" · 分类 {it['category']}" if it["category"] else ""
        gp = it["growth_pct"]
        gp_str = f" · 增长 +{gp}%" if gp else " · 增长 —"
        lines.append(f"{i}. [{it['name']}]({link}){vp}{cat} · 本周安装 {it['weekly_recent']}{gp_str}")
        if it.get("brief"):
            lines.append(f"> {it['brief']}")
    return "\n".join(lines)


def skills_html_section(items, subtitle, note):
    rows = "".join(
        f"<tr><td>{i}</td>"
        f"<td><a href='{it['url'] or 'https://skills.sh/' + it['name']}'>{it['name']}</a></td>"
        f"<td>{it['vendor']}</td><td>{it['category']}</td>"
        f"<td>{it['weekly_recent']}</td>"
        f"<td>{('+' + it['growth_pct'] + '%') if it['growth_pct'] else '—'}</td>"
        f"<td>{it.get('brief', '')}</td></tr>"
        for i, it in enumerate(items, 1)
    )
    return (
        f"<h3>{subtitle}</h3>"
        f"<p style='color:#888;font-size:12px;margin:2px 0 8px'>{note}</p>"
        f"<table border='1' cellspacing='0' cellpadding='6'>"
        f"<tr><th>#</th><th>Skill</th><th>厂商</th><th>分类</th><th>本周安装</th><th>增长率</th><th>用途</th></tr>"
        f"{rows}</table><br/>"
    )


def md_block(items, title, sort_note=""):
    lines = [f"## {title}", "> 数据来源 github.com/trending"]
    if sort_note:
        lines.append(f"> {sort_note}")
    lines.append("")
    for i, it in enumerate(items, 1):
        url = f"https://github.com/{it['repo']}"
        badge = it.get("badge")
        badge_str = f"  [{badge}]" if badge else ""
        lines.append(f"{i}. [{it['repo']}]({url}){badge_str}  ⭐{it['stars']}  {it['week']}")
        if it["desc"]:
            lines.append(f"> {it['desc'][:60]}")
    return "\n".join(lines)


def push_wechat(items, title):
    wh = os.environ.get("WECHAT_WEBHOOK")
    if not wh:
        print("[wechat] 未配置 WECHAT_WEBHOOK，跳过")
        return
    full = md_block(items, title, GROWTH_NOTE)
    # 企微 markdown 内容上限 4096 字节，超出则拆两条
    chunks = [full] if len(full) <= 4000 else [
        md_block(items[: len(items) // 2], title + "（上）"),
        md_block(items[len(items) // 2:], title + "（下）"),
    ]
    for c in chunks:
        payload = {"msgtype": "markdown", "markdown": {"content": c}}
        req = urllib.request.Request(
            wh, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=15).read()
            print("[wechat] 已推送", len(c), "字节")
        except Exception as e:
            print("[wechat] 失败:", e)


def html_section(items, subtitle, note):
    """邮件里单个视角区块（小标题 + 说明 + 一张表）。"""
    rows = "".join(
        f"<tr><td>{i}</td>"
        f"<td><a href='https://github.com/{it['repo']}'>{it['repo']}</a>"
        + (f"<br/><span style='color:#c60;font-size:12px'>{it['badge']}</span>" if it.get("badge") else "")
        + f"</td>"
        f"<td>{it['stars']}</td><td>{it['week']}</td><td>{it['desc']}</td></tr>"
        for i, it in enumerate(items, 1)
    )
    return (
        f"<h3>{subtitle}</h3>"
        f"<p style='color:#888;font-size:12px;margin:2px 0 8px'>{note}</p>"
        f"<table border='1' cellspacing='0' cellpadding='6'>"
        f"<tr><th>#</th><th>仓库</th><th>Stars</th><th>本周</th><th>描述</th></tr>"
        f"{rows}</table><br/>"
    )


def html_email(sorted_items, raw_items, ai_items, skills_items, title):
    """单邮件四视角：视角一=本周增量降序；视角二=GitHub 官方原顺序；视角三=AI 应用层周榜；视角四=Agent Skills 7天飙升榜。"""
    return (
        f"<h2>{title}</h2>"
        + html_section(sorted_items, "视角一 · 本周 star 增量榜（谁涨得多谁靠前）", GROWTH_NOTE)
        + html_section(raw_items, f"视角二 · {OFFICIAL_TITLE}", OFFICIAL_NOTE)
        + html_section(ai_items, AI_TITLE, AI_NOTE)
        + (skills_html_section(skills_items, SKILLS_TITLE, SKILLS_NOTE) if skills_items else "")
    )


def push_email(sorted_items, raw_items, ai_items, skills_items, title):
    host, port, user, pwd, to = (
        os.environ.get(k) for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "EMAIL_TO")
    )
    if not all([host, port, user, pwd, to]):
        print("[email] 未配置完整 SMTP 参数，跳过")
        return
    # 注意：工作流里 EMAIL_FROM: ${{ secrets.EMAIL_FROM }} 在未配置该 secret 时会注入
    # 空字符串（key 存在、值为空），此时 os.environ.get(k, default) 的 default 不生效，
    # 会拼出发件人 "GitHubTrending <>"，被 QQ 以 550 "From header is missing or invalid" 拒收。
    # 因此必须用 `or user` 兜底，并校验含 @ 才认为是合法地址。
    from_addr = (os.environ.get("EMAIL_FROM") or "").strip()
    if "@" not in from_addr:
        from_addr = user
    from_ = formataddr(("GitHubTrending", from_addr))
    msg = MIMEText(html_email(sorted_items, raw_items, ai_items, skills_items, title), "html", "utf-8")
    msg["Subject"] = title
    msg["From"] = from_
    msg["To"] = to
    port = int(port)
    try:
        if port == 465:
            s = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            s = smtplib.SMTP(host, port, timeout=15)
            s.starttls()
        s.login(user, pwd)
        s.sendmail(user, [to], msg.as_string())
        s.quit()
        print("[email] 已发送至", to)
    except Exception as e:
        print("[email] 失败:", e)


def main():
    _load_dotenv()
    since = (os.environ.get("SINCE") or "weekly").strip().lower()
    if since not in ("daily", "weekly", "monthly"):
        print(f"[warn] 非法 SINCE={since!r}，回落 weekly")
        since = "weekly"
    # 🔴 用 TRENDING_LANG，不要用 LANG（系统区域变量会污染 URL，见 _norm_lang 注释）
    lang = _norm_lang(os.environ.get("TRENDING_LANG"))
    raw_items = fetch_trending(since, lang)          # 官方 trending 页原始顺序（视角二）
    # 🔴 按「本周 star 增量」降序重排出视角一（官网顺序是自家不透明算法，并非纯增量排序）
    sorted_items = sorted(raw_items, key=lambda it: _parse_weekly(it["week"]), reverse=True)
    ai_items = fetch_ai_board(since)                  # 视角三：AI 应用层周榜（多语言合并）
    skills_items = fetch_skills_trending()            # 视角四：Agent Skills 7天飙升榜（best-skills）
    today = datetime.date.today().strftime("%Y-%m-%d")
    title = f"GitHub {_period_cn(since)}趋势榜 Top{len(raw_items)} ({today})"
    with open("rank.md", "w", encoding="utf-8") as f:
        # 单邮件四视角：主视角=增量降序，副视角=官方原顺序，视角三=AI 应用层，视角四=Agent Skills
        f.write(md_block(sorted_items, title, GROWTH_NOTE) + "\n\n")
        f.write(md_block(raw_items, OFFICIAL_TITLE, OFFICIAL_NOTE) + "\n\n")
        f.write(md_block(ai_items, AI_TITLE, AI_NOTE) + "\n\n")
        f.write(skills_md_block(skills_items, SKILLS_TITLE, SKILLS_NOTE) + "\n")
    print(f"抓取 {len(raw_items)} 条综合 + {len(ai_items)} 条 AI 应用层 + {len(skills_items)} 条 Agent Skills，已写 rank.md（四视角）")
    push_wechat(sorted_items, title)                 # 企微（未配置）仅发主视角
    push_email(sorted_items, raw_items, ai_items, skills_items, title)   # 邮件发四视角


if __name__ == "__main__":
    main()
