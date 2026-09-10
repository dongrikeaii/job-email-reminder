#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清理「提醒事项」里的重复条目。

背景：早期版本导入时带了 --force，会忽略去重记录，同一条可能被写了多次。
本脚本按「标题 + 截止日期」判定重复，保留最先的一条，删除其余。

⚠ 安全设计：
  - 默认只列出会删哪些，**不动任何数据**（dry-run）
  - 必须显式加 --apply 才真正删除，且需再输一次 y 确认
  - 只作用于 config.json 里 reminder_list 指定的列表（默认「求职待办」）

用法:
    python3 cleanup_reminders.py                 # 预览
    python3 cleanup_reminders.py --apply         # 确认后删除
    python3 cleanup_reminders.py --list 其他列表  # 指定列表
"""
import argparse
import json
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def esc(x):
    return str(x).replace("\\", "\\\\").replace('"', '\\"')


def run(script, timeout=120):
    try:
        p = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "执行超时（提醒事项可能弹出了授权窗口）"


LIST_SCRIPT = '''
tell application "Reminders"
    if not (exists list "{name}") then return "NOLIST"
    set targetList to list "{name}"
    set outText to ""
    set oneItem to 0
    repeat with oneReminder in reminders of targetList
        set oneItem to oneItem + 1
        set nameText to name of oneReminder
        set dueText to ""
        try
            set dueText to (due date of oneReminder) as string
        end try
        set outText to outText & oneItem & "|" & nameText & "|" & dueText & "\\n"
    end repeat
    return outText
end tell
'''

DELETE_SCRIPT = '''
tell application "Reminders"
    set targetList to list "{name}"
    set seenKeys to {{}}
    set deleteCount to 0
    set totalCount to count of reminders of targetList
    repeat with idx from totalCount to 1 by -1
        set oneReminder to item idx of reminders of targetList
        set nameText to name of oneReminder
        set dueText to ""
        try
            set dueText to (due date of oneReminder) as string
        end try
        set itemKey to nameText & "|" & dueText
        if seenKeys contains itemKey then
            delete oneReminder
            set deleteCount to deleteCount + 1
        else
            set end of seenKeys to itemKey
        end if
    end repeat
    return deleteCount as string
end tell
'''


def fetch(list_name):
    code, out, err = run(LIST_SCRIPT.format(name=esc(list_name)))
    if code != 0:
        print(f"[错误] 读取失败：{err or out}", file=sys.stderr)
        print("       若是权限问题，请在「终端」App 里运行本脚本并点「好」。",
              file=sys.stderr)
        sys.exit(1)
    if out == "NOLIST":
        print(f"[提示] 列表「{list_name}」不存在，无需清理")
        sys.exit(0)
    items = []
    for line in out.split("\n"):
        if "|" in line:
            idx, name, due = line.split("|", 2)
            items.append((idx.strip(), name.strip(), due.strip()))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正执行删除（默认只预览）")
    ap.add_argument("--list", default=None, help="提醒事项列表名")
    args = ap.parse_args()

    list_name = args.list
    if not list_name:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                list_name = json.load(f).get("reminder_list", "求职待办")
        except Exception:
            list_name = "求职待办"

    items = fetch(list_name)
    if not items:
        print(f"列表「{list_name}」是空的")
        return

    seen, dup = {}, []
    for idx, name, due in items:
        key = f"{name}|{due}"
        if key in seen:
            dup.append((idx, name, due))
        else:
            seen[key] = idx

    print(f"列表「{list_name}」共 {len(items)} 条，发现重复 {len(dup)} 条\n")
    if not dup:
        print("没有重复项，无需清理。")
        return

    print("下列重复项将被删除（保留同名同截止时间的第一条）：")
    for idx, name, due in dup:
        print(f"   - {name}　截止 {due or '(无)'}")

    if not args.apply:
        print("\n这是预览，未做任何改动。确认无误后执行：")
        print(f"   python3 {os.path.basename(__file__)} --apply")
        return

    print()
    ans = input("确认删除以上条目？输入 y 继续，其他任意键取消：").strip().lower()
    if ans != "y":
        print("已取消。")
        return

    code, out, err = run(DELETE_SCRIPT.format(name=esc(list_name)))
    if code != 0:
        print(f"[失败] {err or out}", file=sys.stderr)
        sys.exit(1)
    print(f"\n[完成] 已删除 {out} 条重复项。")


if __name__ == "__main__":
    main()
