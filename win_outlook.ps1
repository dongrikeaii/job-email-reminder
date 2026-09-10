#Requires -Version 5.1
<#
.SYNOPSIS
    job-mail-radar 的 Windows 后端：通过 Outlook COM 写入任务/日历。

.DESCRIPTION
    由 backend.py 调用，参数与返回值一律走 UTF-8 文件，避免控制台编码问题。
    结果文件第一行是 OK / ERR，其余行为消息（list 时第二行是 JSON 数组）。

.EXAMPLE
    .\win_outlook.ps1 -Action create-reminder -PayloadFile in.json -ResultFile out.txt
#>
param(
    [Parameter(Mandatory = $true)][string]$Action,
    [Parameter(Mandatory = $true)][string]$PayloadFile,
    [Parameter(Mandatory = $true)][string]$ResultFile
)

$ErrorActionPreference = "Stop"

function Write-Result {
    param([string]$Status, [string]$Message)
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($ResultFile, "$Status`r`n$Message", $enc)
}

function Read-Payload {
    $enc = [System.Text.UTF8Encoding]::new($false)
    $txt = [System.IO.File]::ReadAllText($PayloadFile, $enc)
    return ($txt | ConvertFrom-Json)
}

function Parse-Date {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }
    # 注意：PowerShell 不支持 \uXXXX 转义，中文日期格式必须直接写汉字
    $formats = @("yyyy-MM-dd HH:mm", "yyyy-MM-dd HH:mm:ss",
                 "yyyy/MM/dd HH:mm", "yyyy-MM-dd",
                 "yyyy年M月d日 HH:mm", "yyyy年M月d日")
    foreach ($f in $formats) {
        try { return [datetime]::ParseExact($Value.Trim(), $f, $null) } catch { }
    }
    try { return [datetime]::Parse($Value) } catch { return $null }
}

function Get-OutlookFolder {
    param($Namespace, [int]$DefaultFolderType, [string]$Name)
    $root = $Namespace.GetDefaultFolder($DefaultFolderType)
    if ([string]::IsNullOrWhiteSpace($Name)) { return $root }
    if ($Name -eq $root.Name) { return $root }
    foreach ($f in $root.Folders) {
        if ($f.Name -eq $Name) { return $f }
    }
    try {
        $new = $root.Folders.Add($Name, $DefaultFolderType)
        return $new
    } catch {
        return $root   # 建不了子文件夹就落到默认文件夹
    }
}

function New-OutlookApp {
    try {
        $ol = New-Object -ComObject Outlook.Application
        if ($null -eq $ol) { throw "Outlook.Application 返回空" }
        return $ol
    } catch {
        throw "无法启动 Outlook COM： $($_.Exception.Message)。`n" +
              "常见原因：未安装 Outlook 桌面版，或当前使用的是「新版 Outlook」（不支持 COM）。`n" +
              "可改用 .ics 模式：python apply_events.py events.json --backend ics"
    }
}

# ------------------------------------------------------------------ 主流程
try {
    $payload = Read-Payload
    $ol   = New-OutlookApp
    $ns   = $ol.GetNamespace("MAPI")

    switch ($Action) {

        "create-reminder" {
            # olTaskItem = 3, olFolderTasks = 13
            $due = Parse-Date $payload.deadline
            if ($null -eq $due) { throw "截止日期无法解析：$($payload.deadline)" }

            $folder = Get-OutlookFolder -Namespace $ns -DefaultFolderType 13 -Name $payload.folder
            $item = $ol.CreateItem(3)
            $item.Subject = [string]$payload.title
            $body = @()
            if ($payload.link)  { $body += "链接: $($payload.link)" }
            if ($payload.notes) { $body += [string]$payload.notes }
            $item.Body = ($body -join "`r`n")
            $item.DueDate = $due
            $alarm = [int]$payload.alarm_minutes
            if ($alarm -gt 0) {
                $remindAt = $due.AddMinutes(-$alarm)
                # Outlook 不接受早于当前时刻的提醒时间，否则会抛异常
                if ($remindAt -gt (Get-Date)) {
                    $item.ReminderSet  = $true
                    $item.ReminderTime = $remindAt
                }
            }
            $item.Save()
            if ($folder -ne $null) { try { $item.Move($folder) | Out-Null } catch { } }
            Write-Result "OK" "Outlook 任务 · $($payload.folder) → $($payload.title)"
        }

        "create-event" {
            # olAppointmentItem = 1, olFolderCalendar = 9
            $start = Parse-Date $payload.start
            if ($null -eq $start) { throw "开始时间无法解析：$($payload.start)" }
            $end = Parse-Date $payload.end
            if ($null -eq $end) { $end = $start.AddHours(1) }

            $folder = Get-OutlookFolder -Namespace $ns -DefaultFolderType 9 -Name $payload.folder
            $item = $ol.CreateItem(1)
            $item.Subject  = [string]$payload.title
            $body = @()
            if ($payload.link)  { $body += "链接: $($payload.link)" }
            if ($payload.notes) { $body += [string]$payload.notes }
            $item.Body = ($body -join "`r`n")
            $item.Start  = $start
            $item.End    = $end
            $item.Location = ""
            $alarm = [int]$payload.alarm_minutes
            if ($alarm -gt 0) {
                $item.ReminderSet = $true
                $item.ReminderMinutesBeforeStart = $alarm
            }
            $item.Save()
            if ($folder -ne $null) { try { $item.Move($folder) | Out-Null } catch { } }
            Write-Result "OK" "Outlook 日历 · $($payload.folder) → $($payload.title)"
        }

        "list" {
            $folder = Get-OutlookFolder -Namespace $ns -DefaultFolderType 13 -Name $payload.folder
            $rows = @()
            foreach ($it in $folder.Items) {
                $due = ""
                try {
                    if ($it.DueDate -gt [datetime]"1900-01-01") {
                        $due = $it.DueDate.ToString("yyyy-MM-dd HH:mm")
                    }
                } catch { }
                $rows += [pscustomobject]@{
                    title     = [string]$it.Subject
                    due       = $due
                    completed = [bool]$it.Complete
                }
            }
            $json = $rows | ConvertTo-Json -Compress -Depth 4
            if (-not $json) { $json = "[]" }
            Write-Result "OK" $json
        }

        "complete" {
            $folder = Get-OutlookFolder -Namespace $ns -DefaultFolderType 13 -Name $payload.folder
            $kw = [string]$payload.keyword
            $hit = $null
            foreach ($it in $folder.Items) {
                if ([string]$it.Subject -like "*$kw*") { $hit = $it; break }
            }
            if ($null -eq $hit) { throw "未找到匹配「$kw」的待办" }
            $hit.Complete = $true
            $hit.Save()
            Write-Result "OK" "已完成：$($hit.Subject)"
        }

        "uncomplete" {
            $folder = Get-OutlookFolder -Namespace $ns -DefaultFolderType 13 -Name $payload.folder
            $kw = [string]$payload.keyword
            $hit = $null
            foreach ($it in $folder.Items) {
                if ([string]$it.Subject -like "*$kw*") { $hit = $it; break }
            }
            if ($null -eq $hit) { throw "未找到匹配「$kw」的待办" }
            $hit.Complete = $false
            $hit.Save()
            Write-Result "OK" "已撤销完成：$($hit.Subject)"
        }

        "ping" {
            Write-Result "OK" "Outlook COM 可用"
        }

        default { throw "未知操作：$Action" }
    }
}
catch {
    Write-Result "ERR" $_.Exception.Message
    exit 1
}
exit 0
