#Requires -Version 5.1
<#
.SYNOPSIS
    Windows 完整流水线：扫描邮箱 → 规则解析 → 导出 .ics（或写入 Outlook）

.PARAMETER ScanOnly
    只扫描解析，不写系统。用于「打开看板即刷新数据」和定时任务。
#>
param(
    [int]$Days = 7,
    [switch]$DryRun,
    [switch]$ScanOnly,
    [string]$Backend
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$logDir = Join-Path $Root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$log = Join-Path $logDir ("run-{0}.log" -f (Get-Date -Format "yyyyMMdd"))
Add-Content -Path $log -Value ("===== {0} 开始扫描 =====" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss")) -Encoding UTF8

# 定位 Python
$pyCmd = $null
$wb = Join-Path $env:USERPROFILE ".workbuddy\binaries\python\versions"
if (Test-Path $wb) {
    $found = Get-ChildItem -Path $wb -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue |
             Sort-Object FullName -Descending | Select-Object -First 1
    if ($found) { $pyCmd = @($found.FullName) }
}
if (-not $pyCmd) {
    foreach ($c in @("py", "python", "python3")) {
        try {
            if ($c -eq "py") { & py -3 -c "0" 2>$null; if ($LASTEXITCODE -eq 0) { $pyCmd = @("py", "-3"); break } }
            else { & $c -c "0" 2>$null; if ($LASTEXITCODE -eq 0) { $pyCmd = @($c); break } }
        } catch { }
    }
}
if (-not $pyCmd) { Write-Host "未找到 Python" -ForegroundColor Red; exit 1 }

$scanOut = Join-Path $Root "data\latest_scan.json"
$evOut   = Join-Path $Root "data\events.json"
$evOk    = Join-Path $Root "data\events_confirmed.json"

# 1) 扫描
Write-Host "[1/3] 扫描邮箱（最近 $Days 天）..." -ForegroundColor Cyan
& $pyCmd (Join-Path $Root "scan_mail.py") --days $Days 2>&1 | Tee-Object -Variable scanLog | Out-Null
$scanLog | Add-Content -Path $log -Encoding UTF8
if (-not (Test-Path $scanOut)) { Write-Host "扫描失败，详见 $log" -ForegroundColor Red; exit 1 }
$matched = (& $pyCmd -c "import json;print(json.load(open(r'$scanOut',encoding='utf-8')).get('matched',0))" 2>$null)
Write-Host "      命中 $matched 封候选邮件"

# 2) 规则解析
Write-Host "[2/3] 解析截止时间..." -ForegroundColor Cyan
& $pyCmd (Join-Path $Root "parse_rules.py") $scanOut -o $evOut 2>&1 | Out-Null

# 3) 过滤低置信度 + 写入
Write-Host "[3/3] 写入提醒..." -ForegroundColor Cyan
$filter = @'
import json,sys
src,dst = sys.argv[1], sys.argv[2]
d = json.load(open(src, encoding="utf-8"))
d["events"] = [e for e in d.get("events", []) if not e.get("needs_review") and e.get("deadline")]
json.dump(d, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("待写入:", len(d["events"]))
'@
$filterPath = Join-Path $Root "data\_filter_tmp.py"
[System.IO.File]::WriteAllText($filterPath, $filter, (New-Object System.Text.UTF8Encoding($false)))
& $pyCmd $filterPath $evOut $evOk
Remove-Item $filterPath -Force -ErrorAction SilentlyContinue

# 3) 只扫描模式：并入累积事件库后直接返回（供看板启动 / 定时任务使用）
if ($ScanOnly) {
    Write-Host "[3/3] 更新看板数据..." -ForegroundColor Cyan
    & $pyCmd (Join-Path $Root "merge_store.py") $evOk 2>&1 | Tee-Object -Variable mlog
    $mlog | Add-Content -Path $log -Encoding UTF8
    Add-Content -Path $log -Value "===== 结束（ScanOnly） =====" -Encoding UTF8
    Write-Host "完成。日志：$log" -ForegroundColor Gray
    exit 0
}

$applyArgs = @((Join-Path $Root "apply_events.py"), $evOk)
if ($DryRun)  { $applyArgs += "--dry-run" }
if ($Backend) { $applyArgs += @("--backend", $Backend) }
& $pyCmd $applyArgs 2>&1 | Tee-Object -Variable applyLog
$applyLog | Add-Content -Path $log -Encoding UTF8

Add-Content -Path $log -Value "===== 结束 =====" -Encoding UTF8
Write-Host ""
Write-Host "完成。日志：$log" -ForegroundColor Gray
