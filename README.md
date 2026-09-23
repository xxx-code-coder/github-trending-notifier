# GitHub Trending Notifier

每周一自动抓取 GitHub Trending 榜单（默认周榜 Top20），推送至**企业微信群机器人**和/或**邮件**，并归档到 `rank.md`。
全程跑在 GitHub Actions 境外环境，你**不需要直连 GitHub、不需要开代理**，在国内用企业微信 / 邮箱即可收榜。

## 使用方法（逐屏指引）

> ⚠️ **最容易踩的坑**：`Secrets and variables` 在**「仓库级」** Settings 里，**不在「账号级」Settings 里**。
> - 账号级设置页 `github.com/settings/profile`（左侧有 Profile / Account / Appearance / Repositories…）→ **这里没有 Secrets**。
> - 仓库级设置页 `github.com/<你的用户名>/<仓库名>/settings`（左侧有 General / Access / **Security** → Secrets and variables…）→ **Secrets 在这里**。

### 第 1 步：先有仓库（没有仓库就没有「仓库 Settings」）
- 登录 GitHub → 打开本模板 → 点右上角 **`Fork`** → 选你的账号 → 得到 `github.com/<你的用户名>/github-trending-notifier`。
- （也可手动新建一个仓库，把这 4 个文件传上去。）

### 第 2 步：进入「仓库」Settings 配 Secrets
1. 打开你的仓库页：`https://github.com/<你的用户名>/github-trending-notifier`
2. 点仓库顶部导航栏**最右侧的 `Settings`**（齿轮图标）——注意是**仓库页面里的**这个标签，不是你点头像进去的账号设置。
   - 直达链接（把用户名换掉）：`https://github.com/<你的用户名>/github-trending-notifier/settings/secrets/actions`
3. 在**左侧栏**找到 **Security** 分组 → 点 **`Secrets and variables`** → 展开后点 **`Actions`**。
4. 点右侧 **`New repository secret`**，逐个添加（**Name 填名字，Secret 填值**，不用的渠道可留空自动跳过）：

| Secret Name | 值 | 渠道 |
|---|---|---|
| `WECHAT_WEBHOOK` | 企微群机器人完整 URL（`https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx`） | 企业微信 |
| `SMTP_HOST` | `smtp.qq.com` | 邮件 |
| `SMTP_PORT` | `465` | 邮件 |
| `SMTP_USER` | 你的 QQ 邮箱，如 `476219712@qq.com` | 邮件 |
| `SMTP_PASS` | **邮箱授权码**（16 位，非登录密码） | 邮件 |
| `EMAIL_TO` | 收件邮箱（可同 `SMTP_USER`） | 邮件 |

   - 可选项：`EMAIL_FROM`（默认= `SMTP_USER`）。
   - 若想用 **Variables** 而非 Secrets 调整周期：左侧同处 **`Variables`** → `New repository variable`，加 `SINCE=weekly|daily|monthly`、`TRENDING_LANG=python` 等（非敏感，用 variable 即可）。
     - 🔴 **语言变量名必须是 `TRENDING_LANG`，不能叫 `LANG`**：`LANG` 是 POSIX 区域设置变量，GitHub runner 自带 `LANG=C.UTF-8`，被拼进 URL 会变成 `?l=C.UTF-8&...`，GitHub 对未知语言返回**空榜**，脚本会抓到 0 条并报错。脚本已加净化（只放行小写语言名），但仍请用 `TRENDING_LANG`。

### 第 3 步：手动跑一次验证
- 点仓库顶部 **`Actions`** 标签 → 左侧选 **`GitHub Trending Notifier`** → 右侧 **`Run workflow ▾`** → `Run workflow`。
- 跑完看日志有没有 `[email] 已发送至 …` / `[wechat] 已推送 …`，并检查邮箱 / 企微群。

### 第 4 步：以后自动
- 每周一北京时间 08:00（UTC 00:00）自动触发，推送 + 更新仓库 `rank.md`。你之后**只在国内收邮件/企微即可**。

### 找不到 `Secrets and variables` 的排错
- 你现在是不是在**账号设置页**（左侧是 Profile / Account / Appearance…）？→ 那是错的，按第 2 步进**仓库页**再点 `Settings`。
- 仓库页**没有 `Settings` 标签**？→ 说明你对这个仓库没有 admin 权限（不是 owner）。用你自己账号 **fork** 出来的仓库才有。
- 仓库是**空仓库/刚建**？→ 也能配 Secrets，但先把 4 个文件提交进去，否则 Actions 无内容可跑。
- 手机 App 端入口不同且受限，**建议用电脑浏览器**操作这几步。

## 备选方案：完全不用 GitHub（本机 Windows 计划任务）

如果你不想注册 / 登录 GitHub，但本机能访问 `github.com`，可以只在本机定时跑，推送逻辑完全一样：

1. 本目录已生成 `run_weekly.bat`（GBK 编码，可**双击手动跑一次**做验证）。
2. 打开 CMD（普通身份即可），注册「每周一 08:00」的计划任务：

```
schtasks /Create /TN "GitHubTrendingWeekly" /TR "E:\MyWork\github-trending-notifier\run_weekly.bat" /SC WEEKLY /D MON /ST 08:00 /F
```

3. 立刻试跑一次：`schtasks /Run /TN "GitHubTrendingWeekly"`
4. 查看运行日志：`E:\MyWork\github-trending-notifier\log\run.log`
5. 想撤销：`schtasks /Delete /TN "GitHubTrendingWeekly" /F`

**前提**：本目录 `.env` 里的 SMTP 凭证有效（已配好），且**周一 08:00 机器处于开机、联网状态**。

**两条路怎么选**：

| | GitHub Actions | 本机计划任务 |
|---|---|---|
| 需要 GitHub 账号 / 登录 | 需要（一次性） | **不需要** |
| 需要配 Secrets | 需要（6 项） | 不需要（读本地 `.env`） |
| 依赖本机开机 | 不依赖 | **依赖** |
| 稳定性 | 高（云端） | 取决于本机网络与限流 |

## 文件说明
- `gen_rank.py`：抓取 + 解析 + 生成 + 推送（企业微信 markdown / SMTP HTML）。
- `run_weekly.bat`：本机计划任务入口（GBK 编码，日志写入 `log/run.log`）。
- `tools/make_launcher.py`：重新生成上述 `.bat` 的小工具（保证 GBK 编码，中文 Windows 不乱码）。
- `.github/workflows/weekly-rank.yml`：定时任务与 secrets 注入。
- `rank.md`：每次运行自动生成的榜单存档。

> 注意：企业微信 markdown 消息上限 4096 字节，Top20 超出时脚本会自动拆成两条发送。
