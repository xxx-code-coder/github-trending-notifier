#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地预览：生成四视角邮件的 HTML/MD，用于查看视觉排版（不发信、不联网抓 trending）。
视角一/二/三用桩样例；视角四真实抓 best-skills，失败用真实前几行兜底。"""
import sys
sys.path.insert(0, r"E:/MyWork/github-trending-notifier")
import gen_rank as g

# ---- 视角一/二/三：本地预览桩（不联网抓 trending，避免代理拦截）----
stub_sorted = [
    {"repo": "alibaba/open-code-review", "stars": "39,817", "week": "12,590 stars this week", "desc": "通义开源代码审查智能体"},
    {"repo": "anthropics/claude-code", "stars": "147,678", "week": "2,754 stars this week", "desc": "Claude 官方命令行编码智能体"},
    {"repo": "Tencent/WeKnora", "stars": "29,037", "week": "5,303 stars this week", "desc": "腾讯知识库检索智能体"},
]
stub_raw = [
    {"repo": "alibaba/open-code-review", "stars": "39,817", "week": "12,590 stars this week", "desc": "通义开源代码审查智能体"},
    {"repo": "anthropics/claude-code", "stars": "147,678", "week": "2,754 stars this week", "desc": "Claude 官方命令行编码智能体"},
    {"repo": "cloudflare/security-audit-skill", "stars": "20,270", "week": "15,381 stars this week", "desc": "Cloudflare 安全审计技能"},
]
stub_ai = [
    {"repo": "anthropics/claude-code", "stars": "147,678", "week": "2,754 stars this week", "desc": "Claude 官方命令行编码智能体", "badge": "🛠️ 应用层"},
    {"repo": "foo/agent-cli", "stars": "3,000", "week": "1,500 stars this week", "desc": "一个 CLI 智能体工具", "badge": "🛠️ 应用层"},
    {"repo": "some/paper-list", "stars": "1,200", "week": "900 stars this week", "desc": "awesome paper list survey", "badge": "🔬 研究层"},
]

# ---- 视角四：真实抓 best-skills，失败用桩（真实前几行 + 中文占位）----
skills = g.fetch_skills_trending()
real = bool(skills)
if not skills:
    skills = [
        {"name": "ui-taste", "vendor": "uizze.sh", "category": "design-media", "weekly_recent": "238,191", "growth_pct": "", "desc_zh": "(预览桩) UI 审美技能", "url": ""},
        {"name": "ios-design", "vendor": "uizze.sh", "category": "design-media", "weekly_recent": "114,099", "growth_pct": "", "desc_zh": "(预览桩) iOS 设计技能", "url": ""},
        {"name": "ai-video-generation", "vendor": "101-skills", "category": "design-media", "weekly_recent": "531,266", "growth_pct": "12.8", "desc_zh": "(预览桩) AI 视频生成", "url": "https://github.com/101-skills/superpowers"},
        {"name": "ai-image-generation", "vendor": "101-skills", "category": "design-media", "weekly_recent": "530,868", "growth_pct": "12.8", "desc_zh": "(预览桩) AI 图像生成", "url": "https://github.com/101-skills/superpowers"},
        {"name": "twitter-automation", "vendor": "101-skills", "category": "content-creation", "weekly_recent": "530,901", "growth_pct": "12.7", "desc_zh": "(预览桩) Twitter 自动化", "url": "https://github.com/101-skills/superpowers"},
    ]

title = "GitHub 周趋势榜 Top20（本地预览 2026-09-28）"
html = g.html_email(stub_sorted, stub_raw, stub_ai, skills, title)
md = (g.md_block(stub_sorted, title, g.GROWTH_NOTE) + "\n\n"
      + g.md_block(stub_raw, g.OFFICIAL_TITLE, g.OFFICIAL_NOTE) + "\n\n"
      + g.md_block(stub_ai, g.AI_TITLE, g.AI_NOTE) + "\n\n"
      + g.skills_md_block(skills, g.SKILLS_TITLE, g.SKILLS_NOTE))

page = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<style>body{{font-family:-apple-system,"Segoe UI",Roboto,"Microsoft YaHei",sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#222}}
h2{{color:#0969da}}h3{{color:#1a7f37;margin-top:28px}}table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #d0d7de;padding:6px 8px;text-align:left}}th{{background:#f6f8fa}}
p{{color:#888;font-size:12px}}a{{color:#0969da;text-decoration:none}}</style></head>
<body>{html}
<p style="margin-top:30px;color:#aaa;font-size:11px">视角一/二/三为本地预览桩样例（未联网抓 trending）；视角四{'为 best-skills 真实抓取' if real else '为预览桩（联网抓取被拦截，仅演示排版）'}。</p>
</body></html>"""

with open("rank_preview_v4.html", "w", encoding="utf-8") as f:
    f.write(page)
with open("rank_preview_v4.md", "w", encoding="utf-8") as f:
    f.write(md)
print("PREVIEW_OK  视角四真实数据=", real, " 条数=", len(skills))
