# 秋招邮件雷达

自动扫描邮箱里的**测评 / 笔试 / AI面试 / 宣讲会**邀请邮件，抽取公司与截止时间，
用一个网页 + 一个按钮完成检索与导入，并在卡片上显示**精确到小时的倒计时**。

> **跨平台**：macOS（写入提醒事项/日历）、Windows 与 Linux（导出 .ics）。
> Windows 用户请看 **[README-Windows.md](README-Windows.md)**。

---

## 一、日常使用（每天只做这一件事）

**双击 `start.command`**，浏览器自动打开看板，点 **「一键检索并导入」**。

```
流程：连邮箱扫描 → 解析截止时间 → 自动导入未逾期的条目
```

> 一定要从「终端」环境启动（双击 `start.command` 就是），
> 这样服务进程会继承终端的提醒事项授权，网页上的导入按钮才能真正写入系统。
> 关闭终端窗口即停止服务，只监听 127.0.0.1，外网访问不到。

界面上还有：

- **仅检索** —— 只看结果，勾选题目后再手动导入
- 每张卡片实时倒计时（精度到小时，30 秒刷新一次）
- 顶部横幅显示最紧急的一项
- 分组：进行中 / 已逾期 / 待确认（无截止时间）/ 时间存疑 / 已完成
- 「标记完成」可撤销
- 标题下显示**数据更新时间**，后台扫到新数据会自动刷新

---

## 二、Mac 每天自动更新

### 方案 A：打开即更新（默认已有，零配置）

`start.command` 启动时会先在后台跑一次扫描，所以**每次打开看板看到的都是最新数据**。
不装任何后台进程也能用，推荐先这样。

### 方案 B：定时扫描（真正后台，每天 09:00 / 21:00）

```bash
cd ~/job-mail-radar        # 换成你的实际解压目录
./install-schedule.sh
```

脚本会写 `~/Library/LaunchAgents/com.jobmailradar.plist` 并尝试加载。
**若提示"当前环境未能向 launchd 注册"**（受限 shell 里常见），在「终端」App 里手动执行：

```bash
launchctl load -w ~/Library/LaunchAgents/com.jobmailradar.plist
```

常用命令：

```bash
launchctl list | grep jobmailradar      # 确认在跑
launchctl start com.jobmailradar        # 立即试跑一次
tail -f logs/launchd.log                # 看日志
./install-schedule.sh --uninstall       # 卸载
```

### 为什么定时只扫描、不自动写入

后台进程（launchd）**拿不到 AppleScript 授权**——它没法弹权限窗，会直接静默失败。
所以定时任务只做「扫描 + 解析」，把最新数据更新到看板；
真正写入提醒事项由你在看板里点一次「导入」完成，那时进程是终端的子进程，有授权。

### 关于去重与累积

邮件扫描有去重（`data/state.json`），第二次跑时旧邮件会被跳过。
为避免看板被清空，解析结果会**并入累积库** `data/events_store.json`（按内容指纹去重，
逾期超过 3 天的自动清理）。定时任务带 `--force`，每次重扫 7 天内全部邮件，可自愈。

---

## 三、首次配置（做过一次就不用管）

### 1. 拿 163 邮箱的 IMAP 授权码

> ⚠️ 授权码**不是**登录密码，是给第三方客户端专用的一串字符。

网页登录 [mail.163.com](https://mail.163.com) → **设置** → **POP3/SMTP/IMAP**
→ 勾选 **开启 IMAP/SMTP 服务**（手机短信验证）→ 复制 **16 位授权码**。

### 2. 填配置（两种方式）

**网页上填**（推荐）：打开看板，若未配置会自动展开面板，填邮箱 + 授权码 + IMAP 服务器，
点「保存并测试连接」。

**或改文件**：

```bash
cp config.example.json config.json && open -e config.json
```

常用服务器：`imap.163.com` / `imap.qq.com` / `imap.gmail.com` / `outlook.office365.com`，端口 993。

---

## 四、两种解析路径

| 路径 | 触发方式 | 准确度 |
|---|---|---|
| **AI 精判** | 在 WorkBuddy 里说「查测评邮件」 | 高，能读懂"本周内""48小时" |
| **正则兜底** | 网页按钮 / 定时任务 | 一般，相对时间容易算错 |

AI 精判结果存在 `data/events_ai.json`，优先级最高，会自动覆盖同公司同类型的正则条目。
重要事项建议走 AI 路径：直接说 **「查一下测评邮件」**。

---

## 五、权限与兜底

首次写入提醒事项/日历时 macOS 会弹窗，**在「终端」App 里操作授权归属最清晰**。
若误点「不允许」：**系统设置 → 隐私与安全性 → 自动化** → 给「终端」勾上
**提醒事项** 和 **日历**。

拿不到权限也能用：

```bash
python3 export_ics.py data/events_ai.json -o ~/Desktop/求职日程.ics --open
```

双击 `.ics` 导入「日历」App，无需任何权限。

---

## 六、文件说明

| 文件 | 作用 |
|---|---|
| `serve.py` | 本地网页服务（跨平台，纯标准库） |
| `dashboard.html` | 看板界面，含倒计时与自动刷新 |
| `start.command` | 双击启动（启动即扫描一次） |
| `install-schedule.sh` | 安装/卸载 macOS 每日定时扫描 |
| `run.sh` | 命令行流水线：`--scan-only` 只扫描，`--days N` 天数，`--dry-run` 预览 |
| `merge_store.py` | 把解析结果并入累积事件库 |
| `countdown.py` | 倒计时与紧急度计算（网页/按钮/备注三处共用） |
| `backend.py` | 平台后端分派：apple / outlook / ics |
| `scan_mail.py` | IMAP 扫描 + 关键词粗筛 |
| `parse_rules.py` | 正则兜底解析 |
| `apply_events.py` | 写入提醒事项与日历 |
| `complete.py` / `done.sh` | 列出待办、标记完成（`--list`、`--undo`） |
| `data/events_store.json` | 累积事件库（看板主数据源） |
| `data/events_ai.json` | AI 精判结果 |
| `data/completed.json` | 已标记完成的条目 |

---

## 七、安全与隐私

- 全部处理在**本机**完成，邮件正文不上传任何服务器
- `config.json` 含授权码，已加入 `.gitignore`
- 扫描用**只读**模式连接邮箱，不会改动或删除邮件
- 建议单独注册求职专用邮箱，与个人邮箱隔离
