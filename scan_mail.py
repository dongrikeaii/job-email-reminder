#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秋招邮件雷达 - 扫描器
从 163/126/QQ/Gmail 等 IMAP 邮箱拉取近期邮件，粗筛出招聘类事件邮件，
输出 JSON 供上层 LLM 精判（公司 / 事件类型 / 截止时间 / 链接）。

用法:
    python3 scan_mail.py                 # 扫描最近 N 天（默认 7）
    python3 scan_mail.py --days 30       # 扫描最近 30 天
    python3 scan_mail.py --all           # 不做关键词粗筛，输出全部近期邮件
    python3 scan_mail.py --limit 5       # 最多输出 5 封
    python3 scan_mail.py --test-login    # 只测试 IMAP 登录是否通
"""

import argparse
import email
import html
import imaplib
import json
import os
import re
import sys
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "data", "state.json")

# ---------- 163/126 需要发送 IMAP ID 命令，否则会报 Unsafe Login ----------
imaplib.Commands["ID"] = ("AUTH", "SELECTED")


def send_imap_id(conn):
    args = '("name" "job-mail-radar" "version" "1.0" "vendor" "local" "contact" "user@localhost")'
    try:
        typ, dat = conn._simple_command("ID", args)
        conn._untagged_response(typ, dat, "ID")
    except Exception:
        pass  # 部分服务器不认识 ID，忽略


# ---------- 配置 ----------
def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"[错误] 找不到配置文件 {CONFIG_PATH}", file=sys.stderr)
        print("       请先复制 config.example.json 为 config.json 并填入邮箱与授权码。", file=sys.stderr)
        sys.exit(2)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------- 去重状态 ----------
def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"processed": {}}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------- 编码 / 正文处理 ----------
def decode_mime(s):
    if not s:
        return ""
    try:
        return str(make_header(decode_header(s)))
    except Exception:
        try:
            parts = decode_header(s)
            out = []
            for b, enc in parts:
                if isinstance(b, bytes):
                    out.append(b.decode(enc or "utf-8", errors="ignore"))
                else:
                    out.append(b)
            return "".join(out)
        except Exception:
            return str(s)


def html_to_text(h):
    if not h:
        return ""
    h = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", h)
    h = re.sub(r"(?i)</td>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    h = html.unescape(h)
    h = re.sub(r"[ \t\xa0]+", " ", h)
    h = re.sub(r"\n\s*\n+", "\n", h)
    return h.strip()


def extract_links(text):
    urls = re.findall(r"https?://[^\s<>\)\]\"'，。（）]+", text)
    seen, out = set(), []
    for u in urls:
        u = u.rstrip(".,;)]}>\"'")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def get_body(msg, max_len=3000):
    plain, rich = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ("text/plain", "text/html"):
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                try:
                    txt = payload.decode(charset, errors="ignore")
                except (LookupError, UnicodeDecodeError):
                    txt = payload.decode("utf-8", errors="ignore")
                if ctype == "text/plain" and not plain:
                    plain = txt
                elif ctype == "text/html" and not rich:
                    rich = txt
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                txt = payload.decode(charset, errors="ignore")
            except (LookupError, UnicodeDecodeError):
                txt = payload.decode("utf-8", errors="ignore")
            if msg.get_content_type() == "text/html":
                rich = txt
            else:
                plain = txt

    body = plain if len(plain.strip()) > 20 else html_to_text(rich)
    if len(body.strip()) < 20 and rich:
        body = html_to_text(rich)
    body = re.sub(r"\n\s*\n+", "\n", body).strip()
    return body[:max_len]


# ---------- 招聘事件关键词 ----------
POSITIVE = [
    "测评", "在线测评", "心理测评", "性格测评", "职业测评", "能力测评", "综合测评",
    "笔试", "在线笔试", "行测", "答题", "考试",
    "面试", "AI面试", "ai面试", "视频面试", "线上面试", "面试邀请", "面试通知",
    "群面", "单面", "终面", "复试", "复面", "一面", "二面", "三面",
    "请于", "截止", "有效期", "完成时间", "须在", "需在", "请在", "过期",
    "assessment", "online test", "coding challenge", "hirevue", "interview",
    "complete your", "deadline", "due by", "expires", "valid until", "take-home",
    "宣讲会", "开放日", "签约", "offer",
]
# 主题级强排除：命中即丢弃（招聘回执、广告、系统通知）
SUBJECT_NEG = [
    "感谢您的投递", "感谢你投递", "感谢应聘", "感谢您应聘", "感谢您的应聘",
    "投递成功", "简历已收到", "已收到您的简历", "感谢您申请", "感谢信",
    "不合适", "未通过", "很遗憾", "暂不", "职位推荐", "招聘周报",
    "验证码", "账单", "发票", "账号安全", "新设备登录", "超大附件", "退订",
]
# 弱排除：仅在主题与正文前半段（避开页脚）中匹配
WEAK_NEG = ["人才库", "简历入库", "unsubscribe", "newsletter"]
# 主题级强正向：命中即采信，不再受页脚 unsubscribe / 订阅 之类干扰
SUBJECT_POS = ["测评", "笔试", "面试", "邀请", "网申", "内推", "双选",
               "完善简历", "信息更新", "问卷", "申请", "招募"]

# ---------- 时间线索正则（辅助 LLM，也用于无 LLM 时的兜底）----------
DATE_PATTERNS = [
    r"20\d{2}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*日?[\s]*\d{0,2}[:：]?\d{0,2}",
    r"\d{1,2}\s*[-/月]\s*\d{1,2}\s*日?[\s]*\d{0,2}[:：]\d{0,2}",
    r"\d{1,2}\s*[:：]\s*\d{2}",
    r"[（(]?\s*[一二三四五六七八九十两]\s*天(内|后)?\s*[)）]?",
    r"\d+\s*(个)?\s*(小时|天|日)(内|后|之内)?",
    r"(今|明|后)天",
]


def find_date_hints(text):
    hints = []
    for p in DATE_PATTERNS:
        for m in re.findall(p, text):
            s = m if isinstance(m, str) else (m[0] if m else "")
            s = s.strip()
            if s and s not in hints:
                hints.append(s)
    return hints[:25]


def score_mail(subject, body, sender):
    """粗筛打分。

    注意：几乎所有招聘邮件页脚都带 unsubscribe / 订阅 / 退订，
    在完整正文里搜这些词会把真正的测评邀请整封误杀。
    因此仅在「主题 + 正文前 1200 字」范围内做排除判断，
    且主题命中强正向信号时直接采信。
    """
    subj = (subject or "").lower()
    head = f"{subject or ''}\n{(body or '')[:1200]}".lower()

    for n in SUBJECT_NEG:
        if n.lower() in subj:
            return -1

    for p in SUBJECT_POS:
        if p in subj:
            score = 3
            hits = [f"主题:{p}"]
            for q in POSITIVE:
                if q.lower() in head:
                    score += 1
                    hits.append(q)
            return score, hits

    for n in WEAK_NEG:
        if n in head:
            return -1

    score = 0
    hits = []
    for p in POSITIVE:
        if p.lower() in head:
            score += 2 if p in ("测评", "笔试", "面试", "assessment", "interview") else 1
            hits.append(p)
    return score, hits


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None, help="扫描最近 N 天")
    ap.add_argument("--all", action="store_true", help="输出全部近期邮件（不做粗筛）")
    ap.add_argument("--limit", type=int, default=None, help="最多输出邮件数")
    ap.add_argument("--folder", default=None, help="IMAP 文件夹，默认 INBOX")
    ap.add_argument("--force", action="store_true", help="忽略去重状态，重新输出")
    ap.add_argument("--test-login", action="store_true", help="只测试登录")
    ap.add_argument("--dry-run", action="store_true", help="不更新去重状态")
    args = ap.parse_args()

    cfg = load_config()
    days = args.days or cfg.get("days", 7)
    limit = args.limit or cfg.get("max_results", 60)
    folder = args.folder or cfg.get("mailbox", "INBOX")

    host = cfg.get("imap_host", "imap.163.com")
    port = cfg.get("imap_port", 993)
    user = cfg["email"]
    password = cfg["auth_code"]

    conn = imaplib.IMAP4_SSL(host, port)
    try:
        conn.login(user, password)
        # 163/126 要求在 AUTH 状态下发送 ID 声明客户端身份，否则 SELECT/EXAMINE
        # 会返回 "Unsafe Login"。顺序必须是先 login 再 ID，反过来无效。
        send_imap_id(conn)
    except imaplib.IMAP4.error as e:
        print(f"[错误] IMAP 登录失败: {e}", file=sys.stderr)
        print("       163/126 邮箱需使用「授权码」而非登录密码，", file=sys.stderr)
        print("       开启路径：网页邮箱 → 设置 → POP3/SMTP/IMAP → 开启 IMAP 服务 → 获取授权码", file=sys.stderr)
        sys.exit(3)

    if args.test_login:
        print("[OK] IMAP 登录成功")
        typ, boxes = conn.list()
        print("可用文件夹：")
        for b in (boxes or []):
            print("  ", b.decode("utf-8", errors="ignore"))
        return

    typ, _ = conn.select(folder, readonly=True)
    if typ != "OK":
        # 回退：从 LIST 结果中取真实文件夹名。163 的中文目录以 modified UTF-7
        # 返回（如 &dcVr0mWHTvZZOQ-），直接传中文会触发 UnicodeEncodeError。
        _, boxes = conn.list()
        typ = "NO"
        for b in boxes or []:
            raw = b.decode("utf-8", errors="ignore")
            m = re.search(r'"([^"]+)"\s*$', raw)
            name = m.group(1) if m else raw.split()[-1]
            if name.strip().upper() == folder.strip().upper():
                typ, _ = conn.select(name, readonly=True)
                if typ == "OK":
                    folder = name
                    break
        if typ != "OK":
            print(f"[错误] 无法选择文件夹 {folder}", file=sys.stderr)
            sys.exit(4)

    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    typ, data = conn.search(None, f'(SINCE "{since}")')
    if typ != "OK":
        typ, data = conn.search(None, "ALL")
    ids = data[0].split() if data and data[0] else []

    state = load_state()
    processed = state.setdefault("processed", {})

    results = []
    scanned = 0
    for mid in reversed(ids):  # 新的在前
        if len(results) >= limit:
            break
        scanned += 1
        typ, msg_data = conn.fetch(mid, "(RFC822)")
        if typ != "OK" or not msg_data or not msg_data[0]:
            continue
        try:
            msg = email.message_from_bytes(msg_data[0][1])
        except Exception:
            continue

        subject = decode_mime(msg.get("Subject", ""))
        sender = decode_mime(msg.get("From", ""))
        to = decode_mime(msg.get("To", ""))
        try:
            dt = parsedate_to_datetime(msg.get("Date"))
            recv = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            recv = ""

        mid_str = msg.get("Message-ID", "").strip() or mid.decode()
        if not args.force and mid_str in processed:
            continue

        body = get_body(msg, cfg.get("body_max_len", 3000))
        links = extract_links(body)

        sc = score_mail(subject, body, sender)
        if args.all:
            keep, score, hits = True, 0, []
        else:
            if sc == -1:
                continue
            score, hits = sc
            keep = score >= 2
        if not keep:
            continue

        results.append({
            "message_id": mid_str,
            "subject": subject,
            "sender": sender,
            "to": to,
            "received_at": recv,
            "score": score,
            "keyword_hits": hits,
            "date_hints": find_date_hints(f"{subject}\n{body}"),
            "links": links[:8],
            "body": body,
        })

    try:
        conn.close()
    except Exception:
        pass
    conn.logout()

    if not args.dry_run:
        for r in results:
            processed[r["message_id"]] = {
                "subject": r["subject"],
                "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        # 只保留最近 500 条
        if len(processed) > 500:
            keep = sorted(processed.items(), key=lambda kv: kv[1].get("scanned_at", ""))[-500:]
            state["processed"] = dict(keep)
        save_state(state)

    out = {
        "account": user,
        "folder": folder,
        "days": days,
        "scanned": scanned,
        "matched": len(results),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "emails": results,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
