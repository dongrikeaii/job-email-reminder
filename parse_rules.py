#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秋招邮件雷达 - 规则兜底解析器
在没有 AI 会话参与时（如 launchd 定时自动运行），用正则从邮件中抽取
公司 / 事件类型 / 截止时间 / 链接，生成 apply_events.py 可用的 events.json。

精度不如大模型，但足以兜底。置信度低于阈值的会标为 needs_review 且不写入系统 App。

用法:
    python3 parse_rules.py data/latest_scan.json -o data/events.json
    python3 parse_rules.py data/latest_scan.json --min-confidence 2
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, date

# ---------- 事件类型识别 ----------
TYPE_RULES = [
    ("ai面试", ["ai面试", "ai 面试", "智能面试", "数字人面试", "视频面试（ai", "ai-interview"]),
    ("在线测评", ["在线测评", "心理测评", "性格测评", "职业测评", "能力测评", "综合测评",
                 "认知测评", "素质测评", "测评邀请", "assessment", "online test"]),
    ("笔试", ["笔试", "在线笔试", "行测", "专业笔试", "coding challenge", "take-home"]),
    ("面试", ["面试", "interview", "群面", "单面", "终面", "一面", "二面", "三面", "复试"]),
    ("宣讲会", ["宣讲会", "空中宣讲", "open day", "开放日"]),
    ("其他", []),
]

# ---------- 时间抽取 ----------
FULL_DATE = re.compile(
    r"(20\d{2})\s*[/\-年]\s*(\d{1,2})\s*[/\-月]\s*(\d{1,2})\s*日?"
    r"[\s]*(?:(\d{1,2})\s*[:：]\s*(\d{2}))?"
)
SHORT_DATE = re.compile(
    r"(?<!\d)(\d{1,2})\s*[/\-月]\s*(\d{1,2})\s*日?"
    r"[\s]*(?:(\d{1,2})\s*[:：]\s*(\d{2}))?"
)
TIME_ONLY = re.compile(r"(?<!\d)(\d{1,2})\s*[:：]\s*(\d{2})(?!\d)")
RELATIVE = re.compile(r"(\d+)\s*(个)?\s*(小时|天|日)")
REL_CN = re.compile(r"[一二三四五六七八九十两]\s*天")

DEADLINE_CTX = re.compile(
    r"(请于|请在|须在|需在|应于|截止|截至|有效期|完成时间|请在|before|by|deadline|due|valid until|expires)",
    re.I,
)

LINK_RE = re.compile(r"https?://[^\s<>\)\]\"'，。（）]+")

# 常见公司域名映射（可自行往 config 里加）
DOMAIN_COMPANY = {
    "bytedance.com": "字节跳动", "toutiao.com": "字节跳动", "douyin.com": "字节跳动",
    "tencent.com": "腾讯", "qq.com": "腾讯",
    "alibaba-inc.com": "阿里巴巴", "taobao.com": "淘宝", "antgroup.com": "蚂蚁集团",
    "baidu.com": "百度", "meituan.com": "美团", "dianping.com": "美团",
    "jd.com": "京东", "pinduoduo.com": "拼多多", "xiaohongshu.com": "小红书",
    "huawei.com": "华为", "xiaomi.com": "小米", "oppo.com": "OPPO", "vivo.com": "vivo",
    "netease.com": "网易", "game.163.com": "网易游戏", "sina.com": "新浪", "sohu.com": "搜狐",
    "bilibili.com": "哔哩哔哩", "kuaishou.com": "快手", "didi.com": "滴滴",
    "sensetime.com": "商汤", "megvii.com": "旷视", "yitu-inc.com": "依图",
    "mihoyo.com": "米哈游", "hoyoverse.com": "米哈游", "taptap": "TapTap",
    "beisen": "北森", "zhiye": "智联招聘", "zhaopin.com": "智联招聘",
    "51job.com": "前程无忧", "liepin.com": "猎聘", "bosszhipin.com": "BOSS直聘",
    "haitou": "海投网", "yingjiesheng.com": "应届生求职网", "niuren": "牛客",
    "nowcoder.com": "牛客网", "shixiseng.com": "实习僧", "maimai": "脉脉",
    "hirevue.com": "HireVue", "codility.com": "Codility", "hackerrank.com": "HackerRank",
    "cut-e.com": "cut-e", "shl.com": "SHL", "talentq": "Talent Q",
}

NOISE_TITLE = re.compile(r"(退订|unsubscribe|查看完整|点击此处)", re.I)


def extract_company(mail):
    sender = mail.get("sender", "")
    subject = mail.get("subject", "")

    # 1) 发件人显示名
    m = re.match(r"^\s*[\"']?([^\"'<>@]{2,20})[\"']?\s*<", sender)
    if m:
        name = m.group(1).strip()
        name = re.sub(r"(招聘团队|校园招聘|校招|招聘组|人力资源部|HR|人才中心|招聘|团队)$", "", name)
        if name and len(name) >= 2:
            return name

    # 2) 域名映射
    dm = re.search(r"@([\w\.\-]+)", sender)
    if dm:
        domain = dm.group(1).lower()
        for k, v in DOMAIN_COMPANY.items():
            if k in domain:
                return v
        # 3) 退化为域名主名
        parts = domain.split(".")
        if len(parts) >= 2:
            return parts[-2].capitalize()

    # 4) 主题里的方括号
    m = re.search(r"[【\[]([^\]】]{2,15})[】\]]", subject)
    if m:
        return m.group(1).strip()
    return "未知公司"


def extract_type(text):
    low = text.lower()
    for name, kws in TYPE_RULES:
        if name == "其他":
            continue
        for kw in kws:
            if kw.lower() in low:
                return name
    return "招聘事件"


def _clamp_time(h, mi):
    """把小时/分钟收敛到合法范围。

    中文邮件常写「9月12日 24:00」表示当日午夜，datetime 不接受 hour=24，
    必须在此收敛，否则 replace/构造时抛 ValueError: hour must be in 0..23。
    """
    try:
        h = int(h)
        mi = int(mi)
    except (TypeError, ValueError):
        return 23, 59
    if h == 24:              # 24:00 视为当日 23:59
        return 23, 59
    if not 0 <= h <= 23:
        h = 23
    if not 0 <= mi <= 59:
        mi = 59
    return h, mi


def _mk(y, mo, d, h=23, mi=59):
    h, mi = _clamp_time(h, mi)
    try:
        return datetime(y, mo, d, h, mi)
    except ValueError:
        return None


def extract_deadline(mail):
    """返回 (datetime|None, 置信度, 匹配原文)"""
    subject = mail.get("subject", "")
    body = mail.get("body", "")
    text = f"{subject}\n{body}"

    recv = None
    try:
        recv = datetime.strptime(mail.get("received_at", ""), "%Y-%m-%d %H:%M")
    except Exception:
        recv = datetime.now()
    base_year = (recv or datetime.now()).year

    cands = []

    # 1) 完整日期，优先取靠近截止上下文的
    for m in FULL_DATE.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        h, mi = _clamp_time(m.group(4) or 23, m.group(5) or 59)
        dt = _mk(y, mo, d, h, mi)
        if not dt:
            continue
        ctx = text[max(0, m.start() - 25):m.start()]
        conf = 3 if DEADLINE_CTX.search(ctx) else 2
        cands.append((dt, conf, m.group(0).strip()))

    # 2) 月/日（补年份，跨年时 +1）
    for m in SHORT_DATE.finditer(text):
        mo, d = int(m.group(1)), int(m.group(2))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        y = base_year
        dt = _mk(y, mo, d)
        if dt and recv and dt < recv - timedelta(days=1):
            dt = _mk(y + 1, mo, d)
        if not dt:
            continue
        h, mi = _clamp_time(m.group(3) or 23, m.group(4) or 59)
        dt = dt.replace(hour=h, minute=mi)
        ctx = text[max(0, m.start() - 25):m.start()]
        conf = 2 if DEADLINE_CTX.search(ctx) else 1
        cands.append((dt, conf, m.group(0).strip()))

    # 3) 相对时间：3天内 / 48小时
    for m in RELATIVE.finditer(text):
        n = int(m.group(1))
        unit = m.group(3)
        ctx = text[max(0, m.start() - 20):m.start()]
        if not DEADLINE_CTX.search(ctx) and not re.search(r"(内|后)", m.group(0)):
            continue
        if unit == "小时":
            dt = (recv or datetime.now()) + timedelta(hours=n)
        else:
            dt = (recv or datetime.now()) + timedelta(days=n)
        cands.append((dt, 2, m.group(0).strip()))

    if not cands:
        return None, 0, ""

    # 选置信度最高的；同分取最早的
    cands.sort(key=lambda c: (-c[1], c[0]))
    best = cands[0]
    return best[0], best[1], best[2]


def extract_link(mail):
    prefer = re.compile(r"(测评|面试|笔试|assessment|interview|test|invite|link)", re.I)
    links = [l.rstrip(".,;)]}>\"'") for l in LINK_RE.findall(mail.get("body", ""))]
    for l in links:
        if prefer.search(l):
            return l
    return links[0] if links else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scan_file")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--min-confidence", type=int, default=2,
                    help="低于该置信度的事件不写入系统 App（默认 2）")
    args = ap.parse_args()

    with open(args.scan_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    events = []
    for mail in data.get("emails", []):
        company = extract_company(mail)
        etype = extract_type(f'{mail.get("subject","")}\n{mail.get("body","")}')
        dt, conf, raw = extract_deadline(mail)
        link = extract_link(mail)

        if dt is None:
            events.append({
                "company": company,
                "event_type": etype,
                "title": f"{company} {etype}",
                "kind": "reminder",
                "deadline": None,
                "confidence": 0,
                "needs_review": True,
                "link": link,
                "notes": f'未能识别截止时间 | 主题: {mail.get("subject","")}',
                "source_subject": mail.get("subject", ""),
                "source_id": mail.get("message_id", ""),
            })
            continue

        events.append({
            "company": company,
            "event_type": etype,
            "title": f"{company} {etype}",
            "kind": "reminder",
            "deadline": dt.strftime("%Y-%m-%d %H:%M"),
            "confidence": conf,
            "needs_review": conf < args.min_confidence,
            "link": link,
            "notes": f'识别依据: {raw} | 主题: {mail.get("subject","")}',
            "source_subject": mail.get("subject", ""),
            "source_id": mail.get("message_id", ""),
        })

    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "rules",
        "events": events,
    }
    s = json.dumps(out, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(s)
        print(f"[OK] 已生成 {args.output}（{len(events)} 条，"
              f"其中 {sum(1 for e in events if e['needs_review'])} 条需人工确认）")
    else:
        print(s)


if __name__ == "__main__":
    main()
