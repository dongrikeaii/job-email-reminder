#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把一次解析结果并入累积事件库。

用途：定时任务（launchd / 计划任务）每天跑 `run.sh --scan-only` 时，
已处理过的邮件会被 scan_mail 的去重逻辑跳过，当次结果可能为空。
若直接用当次结果覆盖，看板上的旧事件会全部消失。
因此解析结果一律并入 data/events_store.json，按内容指纹去重。

用法:
    python3 merge_store.py [events.json]
默认读取 data/events_confirmed.json
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import serve  # noqa: E402


def main():
    src = (sys.argv[1] if len(sys.argv) > 1
           else os.path.join(BASE_DIR, "data", "events_confirmed.json"))
    if not os.path.exists(src):
        print(f"[跳过] 不存在 {src}")
        return 0
    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)
    events = data.get("events", []) if isinstance(data, dict) else data
    total = serve.merge_into_store(events)
    print(f"累积库现有 {total} 项（本次并入 {len(events)} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
