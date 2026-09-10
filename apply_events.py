#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秋招邮件雷达 - 落库器
把结构化事件写入 macOS「提醒事项」和「日历」。

用法:
    python3 apply_events.py events.json           # 写入（自动选择平台后端）
    python3 apply_events.py events.json --dry-run # 只预览要执行的动作
    python3 apply_events.py events.json --backend ics      # 强制导出 .ics
    python3 apply_events.py events.json --backend outlook  # 强制走 Outlook COM
    python3 apply_events.py events.json --force    # 忽略去重，重复写入

平台后端:
    macOS    -> AppleScript 写入「提醒事项」/「日历」
    Windows  -> Outlook COM 写入「任务」/「日历」；不可用时自动退回 .ics
    Linux    -> 仅 .ics 文件

events.json 格式:
{
  "events": [
    {
      "company": "字节跳动",
      "event_type": "ai_interview",
      "title": "字节跳动 AI面试",
      "kind": "reminder" | "event",       # reminder=提醒事项, event=日历
      "start": "2026-09-12 14:00",        # event 必填
      "end":   "2026-09-12 15:00",        # 可选，默认 +1h
      "deadline": "2026-09-12 23:59",     # reminder 必填
      "link": "https://...",
      "notes": "补充说明"
    }
  ]
}
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

# Windows 控制台默认 GBK，中文输出会抛 UnicodeEncodeError，强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from backend import create, detect_backend  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_PATH = os.path.join(BASE_DIR, "logs", "apply.log")


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def esc(s):
    """AppleScript 字符串转义"""
    if s is None:
        return ""
    s = str(s).replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", "\\n").replace("\r", "")
    return s


def parse_dt(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M",
                "%Y-%m-%d", "%Y年%m月%d日 %H:%M", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def dt_snippet(varname, dt):
    """生成 AppleScript date 对象。

    macOS 新版（12+）中 date 的 year/month/day/hours 等属性已变为只读，
    逐个赋值会报 -10003「不允许进行访问」。改用 ISO 字符串直接构造：
    `date "2026-09-10 10:00:00"`，在中英文区域下均已验证可正确解析。
    """
    return f'set {varname} to date "{dt.strftime("%Y-%m-%d %H:%M:%S")}"'


def build_reminder_script(ev, list_name, alarm_minutes=60):
    # 支持单条事件用 remind_before_minutes 覆盖全局提前量
    cfg_alarm = ev.get("remind_before_minutes", alarm_minutes)
    d = parse_dt(ev.get("deadline")) or parse_dt(ev.get("start"))
    if d is None:
        return None
    title = ev.get("title") or f'{ev.get("company","")} {ev.get("event_type","")}'
    notes = ev.get("notes") or ""
    if ev.get("link"):
        notes = f'链接: {ev["link"]}\n{notes}'.strip()

    # 说明：Reminders 的 reminder 在部分系统版本上不支持 `remind me date`
    # 属性（运行时报 -2741 语法错误，因为 osacompile 不加载应用字典故编译期
    # 发现不了）。默认关闭该属性，只写 due date；需要可自行开启开关。
    return f'''
tell application "Reminders"
    if not (exists list "{esc(list_name)}") then
        try
            make new list with properties {{name:"{esc(list_name)}"}}
        on error
            make new list at end of lists with properties {{name:"{esc(list_name)}"}}
        end try
    end if
    set targetList to list "{esc(list_name)}"
    {dt_snippet("d", d)}
    tell targetList
        set r to make new reminder with properties {{name:"{esc(title)}", body:"{esc(notes)}", due date:d}}
    end tell
    return name of r
end tell
'''


def build_event_script(ev, cal_name, alarm_minutes):
    s = parse_dt(ev.get("start"))
    if s is None:
        return None
    e = parse_dt(ev.get("end")) or (s + timedelta(hours=1))
    title = ev.get("title") or f'{ev.get("company","")} {ev.get("event_type","")}'
    desc = ev.get("notes") or ""
    if ev.get("link"):
        desc = f'链接: {ev["link"]}\n{desc}'.strip()
    url = ev.get("link") or ""

    alarm = ""
    if alarm_minutes and alarm_minutes > 0:
        alarm = f'''
        tell newEvent
            make new display alarm at end of display alarms with properties {{trigger interval:-{int(alarm_minutes)}}}
        end tell'''

    return f'''
tell application "Calendar"
    if not (exists calendar "{esc(cal_name)}") then
        try
            make new calendar with properties {{name:"{esc(cal_name)}"}}
        on error
            make new calendar at end of calendars with properties {{name:"{esc(cal_name)}"}}
        end try
    end if
    set targetCal to calendar "{esc(cal_name)}"
    {dt_snippet("sDate", s)}
    {dt_snippet("eDate", e)}
    tell targetCal
        set newEvent to make new event with properties {{summary:"{esc(title)}", start date:sDate, end date:eDate, description:"{esc(desc)}", url:"{esc(url)}"}}
    end tell{alarm}
    return summary of newEvent
end tell
'''


def run_osascript(script):
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events_file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list-name", default=None)
    ap.add_argument("--calendar-name", default=None)
    ap.add_argument("--backend", default=None,
                    choices=["apple", "outlook", "ics"],
                    help="强制指定写入后端，默认按平台自动选择")
    ap.add_argument("--force", action="store_true",
                    help="忽略去重记录，强制重复写入")
    args = ap.parse_args()

    with open(args.events_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    events = data.get("events", []) if isinstance(data, dict) else data

    cfg = load_config()
    list_name = args.list_name or cfg.get("reminder_list", "求职待办")
    cal_name = args.calendar_name or cfg.get("calendar_name", "求职日程")
    alarm = cfg.get("alarm_minutes_before", 60)

    backend, reason = detect_backend(args.backend)
    print(f"写入后端: {backend}（{reason}）\n")

    ok = fail = skip = 0
    for ev in events:
        kind = (ev.get("kind") or "reminder").lower()
        target = f'日历 · {cal_name}' if kind == "event" else f'提醒事项 · {list_name}'
        title = ev.get("title") or ev.get("company") or "(无标题)"

        if not (ev.get("deadline") or ev.get("start")):
            print(f"[跳过] {title} —— 缺少有效时间")
            skip += 1
            continue

        if args.dry_run:
            print(f"[预览] {target} → {title}")
            ok += 1
            continue

        good, msg = create(ev, list_name, cal_name, alarm,
                           backend=backend, force=args.force)
        if good:
            print(f"[已写入] {msg}")
            ok += 1
        else:
            print(f"[失败] {title}: {msg}")
            fail += 1

        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as lf:
            lf.write(f'{datetime.now():%Y-%m-%d %H:%M:%S}\t{0 if good else 1}\t{target}\t{title}\n')

    print(f"\n完成：成功 {ok}，失败 {fail}，跳过 {skip}")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
