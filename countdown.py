#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
倒计时计算 —— 网页、按钮输出、系统提醒三处共用同一套算法。
精度到小时：不足 1 小时按分钟显示，逾期显示已过时长。
"""

from datetime import datetime

DT_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M",
              "%Y-%m-%d", "%Y年%m月%d日 %H:%M", "%Y年%m月%d日")


def parse_dt(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt in DT_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def hours_left(deadline, now=None):
    """剩余小时数（向下取整）。逾期为负数。无法解析返回 None。"""
    d = parse_dt(deadline)
    if d is None:
        return None
    now = now or datetime.now()
    delta = d - now
    total = delta.total_seconds()
    # 向下取整：剩 41.9 小时显示 41
    return int(total // 3600) if total >= 0 else -int((-total + 3599) // 3600)


def format_countdown(deadline, now=None, compact=False):
    """格式化倒计时文案。

    compact=False -> '剩 1 天 18 小时' / '剩 41 小时' / '剩 45 分钟' / '已逾期 3 小时'
    compact=True  -> '41h' / '-3h'
    """
    d = parse_dt(deadline)
    if d is None:
        return ""
    h = hours_left(deadline, now)
    if h is None:
        return ""

    if compact:
        return f"{h}h"

    if h < 0:
        # h 的单位是小时，转成天要除 24（曾漏除，导致「已逾期 455 天」实为 455 小时）
        od, oh = divmod(-h, 24)
        return f"已逾期 {od} 天 {oh} 小时" if od else f"已逾期 {oh} 小时"

    if h < 1:
        mins = max(1, int((d - (now or datetime.now())).total_seconds() // 60))
        return f"剩 {mins} 分钟"

    days, hours = divmod(h, 24)
    if days > 0:
        return f"剩 {days} 天 {hours} 小时"
    return f"剩 {hours} 小时"


def urgency(deadline, now=None):
    """紧急度分级：overdue / critical(<24h) / soon(<72h) / normal / dubious(>120天，多半解析错) / unknown"""
    h = hours_left(deadline, now)
    if h is None:
        return "unknown"
    if h < 0:
        return "overdue"
    if h > 120 * 24:
        return "dubious"
    if h < 24:
        return "critical"
    if h < 72:
        return "soon"
    return "normal"


def annotate(ev, now=None):
    """给事件字典补上倒计时字段，返回新字典。"""
    out = dict(ev)
    dl = ev.get("deadline") or ev.get("start") or ""
    out["countdown_hours"] = hours_left(dl, now)
    out["countdown_text"] = format_countdown(dl, now)
    out["urgency"] = urgency(dl, now)
    return out


if __name__ == "__main__":
    import sys
    now = datetime(2026, 9, 9, 22, 0)
    for s in ("2026-09-11 15:56", "2026-09-12 08:02", "2026-09-09 15:31",
              "2026-09-09 22:30", "2026-10-01 10:00", "", "乱写"):
        print(f"{s or '(空)':<20} -> {format_countdown(s, now) or '(无)':<18} "
              f"[{urgency(s, now)}]  compact={format_countdown(s, now, True)}")
