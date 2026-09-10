#Requires -Version 5.1
<#
.SYNOPSIS
    查看待办 / 标记完成（Windows 下操作 Outlook 任务）
.EXAMPLE
    .\done-windows.ps1 -List
    .\done-windows.ps1 "达能"
    .\done-windows.ps1 "达能" -Undo
#>
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Keywords,
    [switch]$List,
    [switch]$Undo
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# 定位 Python（与 run-windows.ps1 相同逻辑）
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

$args_ = @((Join-Path $Root "complete.py"))
if ($List)            { $args_ += "--list" }
if ($Undo)            { $args_ += "--undo" }
if ($Keywords)        { $args_ += $Keywords }

& $pyCmd $args_
