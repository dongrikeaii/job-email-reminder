# Windows 使用说明

和其他平台共用同一套代码，界面完全一致：**一个网页 + 一个按钮**。
不需要 Outlook，不需要 Office。

## 安装后怎么做（首次 3 步）

**1. 启动** —— 双击 **`start-windows.bat`**，浏览器自动打开 `http://127.0.0.1:8787`。
命令行也可以：`python serve.py`。关闭窗口即停止服务，只有本机能访问。

> 启动时会**自动在后台扫一次邮箱**（约 30 秒），所以打开就能看到最新数据。

**2. 填邮箱** —— 第一次打开会提示配置：填邮箱地址 + **16 位授权码** + IMAP 服务器，
点「保存并测试连接」。连上了会提示成功。（不用手改 JSON 文件。）

**3. 检索** —— 选好天数，点「**一键检索并导入**」。

之后日常只要做第 1 步和第 3 步。

## 每天自动更新

### 方案 A：打开即更新（默认已有，零配置）

`start-windows.bat` 启动时后台自动扫一次。**每次打开看板都是最新数据**，不用装任何计划任务。

### 方案 B：计划任务（真正后台，每天 09:00）

```powershell
schtasks /Create /TN "job-mail-radar-am" `
  /TR "powershell -NoProfile -WindowStyle Hidden -File `"C:\path\to\run-windows.ps1`" -ScanOnly" `
  /SC DAILY /ST 09:00 /F

schtasks /Delete /TN "job-mail-radar-am" /F   # 卸载
```

把 `C:\path\to\` 换成实际解压目录。
定时任务用 `-ScanOnly`，只更新看板数据，不生成 .ics——避免把没确认过的条目灌进日历。

> 定时扫描走正则解析，精度不如 AI 精读，「3天内」这类相对表述容易算错。
> 重要事项建议在 WorkBuddy 里说一句「查测评邮件」走 AI 精判。

## 界面能做什么

- **一键检索并导入** —— 连接邮箱扫描 → 解析截止时间 → 自动导入未逾期的条目
- **仅检索** —— 只看结果，勾选题目后再手动导入
- 每张卡片有**实时倒计时**（精度到小时，每 30 秒刷新）
- 顶部横幅显示最紧急的一项
- 分组：进行中 / 已逾期 / 待确认（无截止时间）/ 时间存疑 / 已完成
- 「标记完成」可撤销

## 提醒落到哪里

Windows 端**不写 Outlook**，统一导出 `.ics` 文件到 `data\ics\`：

- 点「导入」后，到 `data\ics\` 目录双击 `.ics` 文件
- Windows 会用「日历」App（或你关联的程序）打开，确认导入即可
- 导入后会在截止时间前弹出系统提醒

> 每条目一个 .ics，只导入你真正需要的那几个。

## Python 要求

Python 3.8+，**零第三方依赖**，不需要 `pip install`。

启动脚本按以下顺序自动探测：

1. `%USERPROFILE%\.workbuddy\binaries\python\versions\*\python.exe`（WorkBuddy 自带）
2. `python`
3. `py -3`

都没有的话：

```powershell
winget install Python.Python.3.12
```

## 配置邮箱

首次使用需填 `config.json`（可从 `config.example.json` 复制）：

```json
{
  "email": "your_name@163.com",
  "auth_code": "16位授权码",
  "imap_host": "imap.163.com",
  "imap_port": 993
}
```

163/126 授权码：网页邮箱 → 设置 → POP3/SMTP/IMAP → 开启 IMAP → 短信验证 → 拿到 16 位码。
**不是登录密码。** 常用服务器：`imap.163.com` / `imap.qq.com` / `imap.gmail.com` / `outlook.office365.com`，端口 993。

## 定时扫描（可选）

见上面「方案 B：计划任务」。命令要点是加 `-ScanOnly`。

## 数据存在哪

| 文件 | 内容 |
|---|---|
| `data\events_store.json` | 累积事件库（看板主数据源，跨扫描保留） |
| `data\state.json` | 已扫过的邮件，避免重复提醒 |
| `data\applied.json` | 已写入的事件，避免重复导入 |
| `data\completed.json` | 已标记完成的条目 |
| `data\events_ai.json` | AI 精判结果（优先级最高） |
| `data\ics\` | 导出的日历文件 |

想强制重来：删掉对应 JSON，或导入时加 `--force`。

## 安全

- `config.json` 含授权码，不要提交到公开仓库（`.gitignore` 已排除）
- 打包脚本 `package.sh` 会自动排除 `config.json`、`data\`、`logs\`
- 全程本机处理，邮件以**只读**方式拉取

## 常见问题

**Q：双击 bat 一闪而过**
在 PowerShell 里手动跑 `python serve.py` 看报错。

**Q：中文乱码**
试试 `chcp 65001` 切换控制台编码。

**Q：端口 8787 被占用**
`python serve.py --port 9000`，服务会自动从 8787 起找可用端口。

**Q：导入后没反应**
Windows 端导入是生成 .ics 文件，不是直接进日历。去 `data\ics\` 双击导入。

**Q：登录失败**
确认用的是授权码而非密码，确认网页邮箱已开启 IMAP。
