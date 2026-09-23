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


# 双视角说明文案（邮件 / rank.md 共用）
GROWTH_NOTE = "排序：按本周 star 增量降序（谁涨得多谁靠前）"
OFFICIAL_NOTE = "排序：照搬 github.com/trending 官方顺序（GitHub 自家算法，非纯增量）"
OFFICIAL_TITLE = "GitHub 官方 trending 原顺序（未重排）"


def md_block(items, title, sort_note=""):
    lines = [f"## {title}", "> 数据来源 github.com/trending"]
    if sort_note:
        lines.append(f"> {sort_note}")
    lines.append("")
    for i, it in enumerate(items, 1):
        url = f"https://github.com/{it['repo']}"
        lines.append(f"{i}. [{it['repo']}]({url})  ⭐{it['stars']}  {it['week']}")
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
        f"<td><a href='https://github.com/{it['repo']}'>{it['repo']}</a></td>"
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


def html_email(sorted_items, raw_items, title):
    """单邮件双视角：视角一=本周增量降序；视角二=GitHub 官方原顺序。"""
    return (
        f"<h2>{title}</h2>"
        + html_section(sorted_items, "视角一 · 本周 star 增量榜（谁涨得多谁靠前）", GROWTH_NOTE)
        + html_section(raw_items, f"视角二 · {OFFICIAL_TITLE}", OFFICIAL_NOTE)
    )


def push_email(sorted_items, raw_items, title):
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
    msg = MIMEText(html_email(sorted_items, raw_items, title), "html", "utf-8")
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
    today = datetime.date.today().strftime("%Y-%m-%d")
    title = f"GitHub {_period_cn(since)}趋势榜 Top{len(raw_items)} ({today})"
    with open("rank.md", "w", encoding="utf-8") as f:
        # 单文件双视角：主视角=增量降序，副视角=官方原顺序
        f.write(md_block(sorted_items, title, GROWTH_NOTE) + "\n\n")
        f.write(md_block(raw_items, OFFICIAL_TITLE, OFFICIAL_NOTE) + "\n")
    print(f"抓取 {len(raw_items)} 条，已写 rank.md（双视角）")
    push_wechat(sorted_items, title)                 # 企微（未配置）仅发主视角
    push_email(sorted_items, raw_items, title)       # 邮件发双视角


if __name__ == "__main__":
    main()
