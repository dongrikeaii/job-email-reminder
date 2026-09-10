#Requires -Version 5.1
<#
.SYNOPSIS
    job-mail-radar 的 Windows 一键安装脚本。

.DESCRIPTION
    依次完成：探测 Python → 建目录 → 写配置 → 测邮箱登录 → 探测写入后端
    → 安装 WorkBuddy 技能 → （可选）注册每日定时扫描。

.EXAMPLE
    # 双击 install-windows.bat 即可，或手动执行：
    powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
#>
param(
    [switch]$SkipSchedule,      # 跳过定时任务注册
    [switch]$SkipSkillInstall   # 跳过 WorkBuddy 技能安装
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Write-Step { param($n, $text) Write-Host "`n[$n] $text" -ForegroundColor Cyan }
function Write-OK   { param($text)   Write-Host "    OK  $text" -ForegroundColor Green }
function Write-Warn2{ param($text)   Write-Host "    警告 $text" -ForegroundColor Yellow }
function Write-Err2 { param($text)   Write-Host "    错误 $text" -ForegroundColor Red }

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  秋招邮件雷达 job-mail-radar  Windows 安装" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# ---------------------------------------------------------------- 1 Python
Write-Step 1 "探测 Python"
$py = $null

$candidates = @()
$wb = Join-Path $env:USERPROFILE ".workbuddy\binaries\python\versions"
if (Test-Path $wb) {
    $candidates += Get-ChildItem -Path $wb -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue |
                   Sort-Object FullName -Descending | ForEach-Object { $_.FullName }
}
$candidates += @("py", "python", "python3")

foreach ($c in $candidates) {
    try {
        if ($c -eq "py") {
            $v = & py -3 -c "import sys;print(sys.version.split()[0])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v) {
                $py = "py -3"; Write-OK "py -3  (Python $v)"; break
            }
        } else {
            $v = & $c -c "import sys;print(sys.version.split()[0])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v) {
                $py = $c; Write-OK "$c  (Python $v)"; break
            }
        }
    } catch { }
}

if (-not $py) {
    Write-Err2 "未找到 Python 3。"
    Write-Host "    请先安装：winget install Python.Python.3.12" -ForegroundColor Yellow
    Write-Host "    或 https://www.python.org/downloads/ （安装时勾选 Add to PATH）" -ForegroundColor Yellow
    Read-Host "    按回车退出"
    exit 1
}

# Python 命令拆成数组，便于带参数调用
$pyCmd = if ($py -eq "py -3") { @("py", "-3") } else { @($py) }

# ---------------------------------------------------------------- 2 目录
Write-Step 2 "准备目录"
foreach ($d in @("data", "logs", "data\ics")) {
    $p = Join-Path $Root $d
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}
Write-OK "data / logs / data\ics 就绪"

# ---------------------------------------------------------------- 3 配置
Write-Step 3 "邮箱配置"
$cfgPath = Join-Path $Root "config.json"
if (Test-Path $cfgPath) {
    Write-OK "config.json 已存在，跳过（如需修改请手动编辑）"
} else {
    $example = Join-Path $Root "config.example.json"
    Copy-Item $example $cfgPath -Force
    Write-Host "    已生成 config.json，现在填写邮箱信息：" -ForegroundColor Yellow
    $addr = Read-Host "    邮箱地址（如 your_name@163.com）"
    $code = Read-Host "    IMAP 授权码（16 位，不是登录密码）"
    $host_ = Read-Host "    IMAP 服务器（回车默认 imap.163.com）"
    if ([string]::IsNullOrWhiteSpace($host_)) { $host_ = "imap.163.com" }

    $json = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $json.email     = $addr.Trim()
    $json.auth_code = $code.Trim()
    $json.imap_host = $host_.Trim()
    $out = $json | ConvertTo-Json -Depth 6
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($cfgPath, $out, $enc)
    Write-OK "配置已写入 config.json"
    Write-Warn2 "该文件含授权码，请勿上传到公开仓库"
}

# ---------------------------------------------------------------- 4 登录测试
Write-Step 4 "测试邮箱连接"
& $pyCmd (Join-Path $Root "scan_mail.py") --test-login
if ($LASTEXITCODE -eq 0) {
    Write-OK "邮箱连接成功"
} else {
    Write-Warn2 "连接失败。请检查：授权码是否正确、邮箱是否开启 IMAP 服务。"
    Write-Host "    163/126：网页邮箱 → 设置 → POP3/SMTP/IMAP → 开启 IMAP → 获取授权码" -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 5 后端
Write-Step 5 "探测提醒写入后端"
& $pyCmd (Join-Path $Root "backend.py")
if ($LASTEXITCODE -ne 0) { Write-Warn2 "后端探测异常，可忽略" }

# ---------------------------------------------------------------- 6 技能
if (-not $SkipSkillInstall) {
    Write-Step 6 "安装 WorkBuddy 技能"
    $skillSrc = Join-Path $Root "SKILL.md"
    if (Test-Path $skillSrc) {
        $skillDir = Join-Path $env:USERPROFILE ".workbuddy\skills\job-mail-radar"
        New-Item -ItemType Directory -Path $skillDir -Force | Out-Null
        Copy-Item $skillSrc (Join-Path $skillDir "SKILL.md") -Force
        Write-OK "已安装到 $skillDir"
        Write-Host "    之后在 WorkBuddy 里直接说「查测评邮件」即可触发" -ForegroundColor Gray
    } else {
        Write-Warn2 "包内缺少 SKILL.md，跳过"
    }
}

# ---------------------------------------------------------------- 7 定时任务
if (-not $SkipSchedule) {
    Write-Step 7 "每日定时扫描（可选）"
    $ans = Read-Host "    是否注册每天 09:00 和 21:00 自动扫描？[y/N]"
    if ($ans -match '^[yY]') {
        $runner = Join-Path $Root "run-windows.ps1"
        $taskCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`""
        foreach ($t in @(@{n = "job-mail-radar-am"; s = "09:00"}, @{n = "job-mail-radar-pm"; s = "21:00"})) {
            & schtasks /Create /TN $t.n /TR $taskCmd /SC DAILY /ST $t.s /F 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { Write-OK "已注册 $($t.n) 每天 $($t.s)" }
            else { Write-Warn2 "注册 $($t.n) 失败（可能需要管理员权限）" }
        }
        Write-Host "    管理命令：schtasks /Query /TN job-mail-radar-am" -ForegroundColor Gray
        Write-Host "    卸载：schtasks /Delete /TN job-mail-radar-am /F" -ForegroundColor Gray
    } else {
        Write-OK "已跳过，可随时手动运行 run-windows.ps1"
    }
}

# ---------------------------------------------------------------- 完成
Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  安装完成" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  常用命令（在本目录打开 PowerShell）：" -ForegroundColor Cyan
Write-Host "    powershell -ExecutionPolicy Bypass -File .\run-windows.ps1   # 扫描并写入"
Write-Host "    powershell -ExecutionPolicy Bypass -File .\done-windows.ps1 -List"
Write-Host ""
$openAns = Read-Host "  现在试跑一次完整扫描？[y/N]"
if ($openAns -match '^[yY]') {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "run-windows.ps1")
}
