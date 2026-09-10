#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秋招邮件雷达 - ICS 导出（免权限兜底方案）
当系统不给 AppleScript 自动化权限时，用本脚本生成 .ics 日历文件，
双击即可导入「日历」App（也可拖入 Google Calendar）。

用法:
    python3 export_ics.py data/events.json -o data/求职日程.ics
    python3 export_ics.py data/events.json -o out.ics --open   # 生成后直接打开
"""

import argparse
import os
import subprocess
import uuid
from datetime import datetime, timedelta


def parse_dt(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def ics_escape(s):
    if not s:
        return ""
    return (str(s).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def fold(line):
    """RFC5545 折行：单行不超过 75 字节"""
    b = line.encode("utf-8")
    if len(b) <= 73:
        return line
    out, cur = [], b""
    for ch in line:
        e = ch.encode("utf-8")
        if len(cur) + len(e) > 73:
            out.append(cur.decode("utf-8"))
            cur = b" " + e
        else:
            cur += e
    out.append(cur.decode("utf-8"))
    return "\r\n".join(out)


def build_ics(events, cal_name="求职日程", alarm_minutes=60):
    now = datetime.now().strftime("%Y%m%dT%H%M%S")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//job-mail-radar//ZH-CN//", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{ics_escape(cal_name)}"]

    n = 0
    for ev in events:
        if ev.get("needs_review"):
            continue
        start = parse_dt(ev.get("start")) or parse_dt(ev.get("deadline"))
        if not start:
            continue
        end = parse_dt(ev.get("end")) or (start + timedelta(hours=1))

        title = ev.get("title") or f'{ev.get("company","")} {ev.get("event_type","")}'
        desc = ev.get("notes") or ""
        if ev.get("link"):
            desc = f'链接: {ev["link"]}\n{desc}'.strip()

        uid = ev.get("source_id") or str(uuid.uuid4())
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@jobmailradar",
            f"DTSTAMP:{now}",
            f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{ics_escape(title)}",
            f"DESCRIPTION:{ics_escape(desc)}",
        ]
        if ev.get("link"):
            lines.append(f"URL:{ics_escape(ev['link'])}")
        lines += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"TRIGGER:-PT{int(alarm_minutes)}M",
            f"DESCRIPTION:{ics_escape(title)}",
            "END:VALARM",
            "END:VEVENT",
        ]
        n += 1

    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines), n


def export_events(events, path, cal_name="求职日程", alarm_minutes=60):
    """导出到指定路径，返回写入的事件数。供 backend 的 ics 模式调用。"""
    ics, n = build_ics(events, cal_name, alarm_minutes)
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(ics)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events_file")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--open", action="store_true", help="生成后用默认方式打开")
    ap.add_argument("--calendar-name", default="求职日程")
    ap.add_argument("--alarm", type=int, default=60)
    args = ap.parse_args()

    import json
    with open(args.events_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    events = data.get("events", []) if isinstance(data, dict) else data

    n = export_events(events, args.output, args.calendar_name, args.alarm)
    print(f"[OK] 已生成 {args.output}（{n} 个事件）")
    if args.open:
        try:
            from backend import open_path
            open_path(os.path.abspath(args.output))
        except Exception:
            subprocess.run(["open", args.output])


if __name__ == "__main__":
    main()
