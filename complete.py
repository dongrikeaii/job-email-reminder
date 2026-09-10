#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秋招邮件雷达 - 完成状态管理
把「求职待办」里的提醒标记为已完成（真正同步到系统提醒事项，iPhone 上也会同步打勾）。

用法:
    python3 complete.py --list                 # 列出待办清单与状态
    python3 complete.py "达能"                  # 把名字含「达能」的标为完成
    python3 complete.py "达能" "雀巢"            # 一次标多个
    python3 complete.py "达能" --undo           # 取消完成（改回待办）
"""

import argparse
import json
import os
import subprocess
import sys

# Windows 控制台中文输出保险
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from backend import detect_backend, list_items, mark_complete  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_list_name():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("reminder_list", "求职待办")
        except Exception:
            pass
    return "求职待办"


def esc(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def run(script):
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def list_items(list_name):
    # 变量名一律用带 Text/Flag 后缀的长名：
    # AppleScript 中短标识符（如 st / d）易与应用字典术语冲突，
    # 运行时才暴露 -2741「预期是表达式」，编译期查不出来。
    script = f'''
tell application "Reminders"
    if not (exists list "{esc(list_name)}") then return ""
    set targetList to list "{esc(list_name)}"
    set outText to ""
    repeat with oneItem in (reminders of targetList)
        set doneFlag to (completed of oneItem)
        set nameText to (name of oneItem)
        set dueText to ""
        try
            set dueText to ((due date of oneItem) as string)
        end try
        set outText to outText & doneFlag & "|" & nameText & "|" & dueText & "\\n"
    end repeat
    return outText
end tell
'''
    code, out, err = run(script)
    if code != 0:
        print(f"[错误] 无法读取提醒事项: {err}", file=sys.stderr)
        sys.exit(1)
    items = []
    for line in out.split("\n"):
        if "|" in line:
            st, name, d = line.split("|", 2)
            done = st.strip().lower() == "true"
            items.append(("已完成" if done else "待完成", name.strip(), d.strip()))
    return items


def toggle(list_name, keyword, completed):
    flag = "true" if completed else "false"
    script = f'''
tell application "Reminders"
    if not (exists list "{esc(list_name)}") then return "NOTFOUND"
    set targetList to list "{esc(list_name)}"
    set outText to ""
    repeat with oneItem in (reminders of targetList)
        if (name of oneItem) contains "{esc(keyword)}" then
            set completed of oneItem to {flag}
            set outText to outText & (name of oneItem) & "\\n"
        end if
    end repeat
    return outText
end tell
'''
    code, out, err = run(script)
    if code != 0:
        print(f"[错误] {err}", file=sys.stderr)
        return False
    if out == "NOTFOUND":
        print(f"[跳过] 列表「{list_name}」不存在，请先运行写入命令")
        return False
    if not out:
        print(f"[未匹配] 没有名字含「{keyword}」的提醒")
        return False
    for n in out.split("\n"):
        if n.strip():
            print(f"[{'已完成' if completed else '已恢复待办'}] {n.strip()}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keywords", nargs="*", help="要匹配的关键词")
    ap.add_argument("--list", action="store_true", help="列出待办清单")
    ap.add_argument("--undo", action="store_true", help="取消完成")
    ap.add_argument("--list-name", default=None)
    ap.add_argument("--backend", default=None, choices=["apple", "outlook", "ics"])
    args = ap.parse_args()

    list_name = args.list_name or load_list_name()
    backend, reason = detect_backend(args.backend)

    # 非 macOS 平台统一走 backend（Outlook COM / ics）
    if backend != "apple":
        if args.list or not args.keywords:
            items = list_items(list_name, backend=backend)
            if not items:
                print(f"列表「{list_name}」为空或不存在（后端：{backend}）")
                return
            print(f"=== {list_name}（后端：{backend}）===")
            for it in items:
                mark = "✓" if it["completed"] else "·"
                due = f'  — 截止 {it["due"]}' if it.get("due") else ""
                print(f'  [{mark}] {it["title"]}{due}')
            todo = sum(1 for i in items if not i["completed"])
            print(f"\n共 {len(items)} 项，待完成 {todo} 项")
            return
        for kw in args.keywords:
            ok, msg = mark_complete(kw, list_name, backend=backend, undo=args.undo)
            print(f"[{'OK' if ok else '失败'}] {kw}: {msg}")
        return

    if args.list or not args.keywords:
        items = list_items(list_name)
        if not items:
            print(f"列表「{list_name}」为空或不存在")
            return
        print(f"=== {list_name} ===")
        for st, name, d in items:
            mark = "✓" if st == "已完成" else "·"
            print(f"  [{mark}] {name}{'  — 截止 ' + d if d else ''}")
        todo = sum(1 for i in items if i[0] == "待完成")
        print(f"\n共 {len(items)} 项，待完成 {todo} 项")
        return

    for kw in args.keywords:
        toggle(list_name, kw, not args.undo)


if __name__ == "__main__":
    main()
