#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
秋招邮件雷达 - 本地网页服务（跨平台，纯标准库）

启动后打开 http://127.0.0.1:8787 即可看到看板，点按钮完成检索与导入。
只监听本机回环地址，不对外暴露。

用法:
    python3 serve.py            # 默认 8787 端口
    python3 serve.py --port 9000
    python3 serve.py --no-open  # 不自动打开浏览器
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DASHBOARD = os.path.join(BASE_DIR, "dashboard.html")
COMPLETED_PATH = os.path.join(DATA_DIR, "completed.json")

sys.path.insert(0, BASE_DIR)
import countdown as CD          # noqa: E402
import backend                  # noqa: E402

AI_EVENTS = os.path.join(DATA_DIR, "events_ai.json")
RULE_OK = os.path.join(DATA_DIR, "events_confirmed.json")
RULE_RAW = os.path.join(DATA_DIR, "events.json")
IMPORT_FILE = os.path.join(DATA_DIR, "events_import.json")
# 累积事件库：每天定时扫描时，已处理过的邮件会被去重跳过，
# 若直接用当次结果覆盖，看板会被清空。故按指纹累积保存。
STORE_FILE = os.path.join(DATA_DIR, "events_store.json")


# ------------------------------------------------------------------ 数据
def _read_events_file(path, source):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    events = data.get("events", []) if isinstance(data, dict) else data
    out = []
    for e in events:
        if not isinstance(e, dict):
            continue
        c = dict(e)
        c.setdefault("source", source)
        out.append(c)
    return out


def load_completed():
    if os.path.exists(COMPLETED_PATH):
        try:
            with open(COMPLETED_PATH, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_completed(s):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(COMPLETED_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(s), f, ensure_ascii=False, indent=2)


def merge_into_store(events):
    """把本次解析结果并入累积库：同指纹覆盖，逾期超过 3 天的清理掉。"""
    store = {}
    if os.path.exists(STORE_FILE):
        try:
            with open(STORE_FILE, "r", encoding="utf-8") as f:
                for e in json.load(f).get("events", []):
                    store[e.get("id") or backend.fingerprint(e)] = e
        except Exception:
            store = {}

    now = datetime.now()
    for e in events:
        e = CD.annotate(e, now)
        e["id"] = backend.fingerprint(e)
        store[e["id"]] = e

    # 清理：截止已过 3 天以上的不再占用看板
    def _expired(e):
        h = e.get("countdown_hours")
        return h is not None and h < -72

    kept = [e for e in store.values() if not _expired(e)]
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STORE_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                   "events": kept}, f, ensure_ascii=False, indent=2)
    return len(kept)


def collect_events():
    """合并 AI 精判结果与正则结果，AI 优先去重；补倒计时与完成状态。"""
    ai = _read_events_file(AI_EVENTS, "ai")
    # 优先读累积库（跨多次扫描保留），首次运行前回退到单次解析结果
    rule = (_read_events_file(STORE_FILE, "rule")
            or _read_events_file(RULE_OK, "rule")
            or _read_events_file(RULE_RAW, "rule"))

    def key(e):
        return (str(e.get("company") or "").strip(),
                str(e.get("event_type") or "").strip(),
                str(e.get("deadline") or e.get("start") or "").strip())

    # AI 精判已覆盖的条目，正则版本不再重复展示。
    # 两边公司名写法常不一致（「联合利华」vs「联合利华（中国）有限公司」），
    # 故用子串包含判断，避免同一件事出现两个不同截止时间的条目。
    ai_items = [(str(e.get("company") or "").strip(),
                 str(e.get("event_type") or "").strip())
                for e in ai if (e.get("company") or "").strip()]

    def covered_by_ai(company, etype):
        for ac, at in ai_items:
            if at != etype:
                continue
            if company and ac and (company in ac or ac in company):
                return True
        return False

    seen, merged = set(), []
    for e in ai + rule:
        k = key(e)
        if not any(k):          # 三者都空则跳过
            continue
        if k in seen:
            continue
        if e.get("source") == "rule" and \
           covered_by_ai(str(e.get("company") or "").strip(),
                         str(e.get("event_type") or "").strip()):
            continue
        seen.add(k)
        merged.append(e)

    now = datetime.now()
    done = load_completed()
    applied = backend.load_applied()     # 已写入过系统的条目，用于显示「已导入」
    result = []
    for e in merged:
        e = CD.annotate(e, now)
        # id 用内容指纹而非下标：扫描新增条目时不会让已有 id 整体移位
        e["id"] = backend.fingerprint(e)
        e["completed"] = e["id"] in done
        e["imported"] = e["id"] in applied
        dl = CD.parse_dt(e.get("deadline") or e.get("start") or "")
        e["deadline_iso"] = dl.isoformat() if dl else ""
        result.append(e)

    # 按截止时间排序，无截止时间的排最后
    result.sort(key=lambda e: (e["deadline_iso"] == "", e["deadline_iso"]))
    return result


def run_script(args, timeout=180):
    p = subprocess.run([sys.executable] + args, cwd=BASE_DIR,
                       capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return p.returncode, p.stdout or "", p.stderr or ""


def do_scan(days=7):
    """扫描邮箱并做规则解析，返回 (ok, message)"""
    scan_out = os.path.join(DATA_DIR, "latest_scan.json")
    code, out, err = run_script(["scan_mail.py", "--days", str(days)])
    if code != 0:
        return False, (err or out).strip()[-300:] or "扫描失败"

    code, out, err = run_script(["parse_rules.py", scan_out,
                                 "-o", os.path.join(DATA_DIR, "events.json")])
    if code != 0:
        return False, (err or out).strip()[-300:] or "解析失败"

    # 过滤低置信度与无截止时间的条目
    try:
        with open(os.path.join(DATA_DIR, "events.json"), "r", encoding="utf-8") as f:
            d = json.load(f)
        d["events"] = [e for e in d.get("events", [])
                       if not e.get("needs_review") and e.get("deadline")]
        with open(RULE_OK, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        n = len(d["events"])
    except Exception as e:
        return False, f"整理失败: {e}"

    # 并入累积库：本次没抓到的旧事件依然保留在看板上
    try:
        total = merge_into_store(d["events"])
    except Exception:
        total = n

    return True, f"扫描完成，本次解析 {n} 项，看板累计 {total} 项"


def load_cfg():
    try:
        with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def import_events(selected):
    """把选中的事件写入系统提醒。按指纹去重，同一条不会重复写。"""
    now = datetime.now()
    payload = []
    for e in selected:
        c = dict(e)
        cd = CD.format_countdown(e.get("deadline") or e.get("start"), now)
        prefix = f"⏳ {cd}（截止 {e.get('deadline') or e.get('start')}）"
        c["notes"] = f"{prefix}\n{e.get('notes') or ''}".strip()
        payload.append(c)
    with open(IMPORT_FILE, "w", encoding="utf-8") as f:
        json.dump({"events": payload}, f, ensure_ascii=False, indent=2)

    # 注意：这里**不能**加 --force。--force 会忽略 data/applied.json 的去重记录，
    # 导致每次点导入都往提醒事项里再写一份，产生重复条目。
    code, out, err = run_script(["apply_events.py", IMPORT_FILE])
    return code == 0, (out or err).strip()[-400:] or ("导入成功" if code == 0 else "导入失败")


def startup_scan():
    """启动时后台扫一次邮箱；若开启 auto_import_new，顺带导入尚未写入的新条目。

    这样即使不挂 launchd，每次打开看板看到的也是最新数据。
    """
    try:
        cfg = load_cfg()
        if not (cfg.get("email") and cfg.get("auth_code")):
            print("[启动扫描] 未配置邮箱，跳过")
            return
        days = int(cfg.get("scan_days", 7) or 7)
        print(f"[启动扫描] 扫描最近 {days} 天…")
        ok, msg = do_scan(days)
        print(f"[启动扫描] {msg}")

        if ok and cfg.get("auto_import_new", True):
            fresh = [e for e in collect_events()
                     if not e.get("imported") and not e.get("completed")
                     and e.get("urgency") in ("critical", "soon", "normal")]
            if fresh:
                ok2, msg2 = import_events(fresh)
                print(f"[自动导入] {len(fresh)} 条新条目 → {msg2}")
            else:
                print("[自动导入] 没有尚未导入的新条目")
    except Exception as e:
        print(f"[启动扫描] 出错: {e}")


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静音默认日志

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/dashboard.html"):
            if not os.path.exists(DASHBOARD):
                self._send(404, "缺少 dashboard.html", "text/plain; charset=utf-8")
                return
            with open(DASHBOARD, "r", encoding="utf-8") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
            return

        if path == "/api/events":
            self._send(200, {"events": collect_events(),
                             "backend": backend.detect_backend()[0],
                             "now": datetime.now().isoformat()})
            return

        if path == "/api/status":
            email = ""
            try:
                with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
                    email = json.load(f).get("email", "")
            except Exception:
                pass
            if "@" in email:
                email = email[:2] + "***" + email[email.find("@"):]
            bk, reason = backend.detect_backend()
            ts, src, human = _last_update()
            self._send(200, {"backend": bk, "reason": reason, "email": email,
                             "system": sys.platform,
                             "configured": _configured(),
                             "last_update": ts, "last_update_src": src,
                             "last_update_text": human})
            return

        if path == "/api/config":
            try:
                with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg.pop("auth_code", None)
            except Exception:
                cfg = {}
            self._send(200, cfg)
            return

        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()

        if path == "/api/scan":
            days = int(body.get("days") or 7)
            try:
                ok, msg = do_scan(days)
            except subprocess.TimeoutExpired:
                ok, msg = False, "扫描超时（>180 秒），请减少天数后重试"
            except Exception as e:
                ok, msg = False, str(e)[:300]
            events = collect_events() if ok else []
            urgent = next((e for e in events if e.get("urgency") in ("critical", "soon")), None)
            self._send(200, {
                "ok": ok, "message": msg, "events": events,
                "urgent": (f'{urgent["title"]} · {urgent["countdown_text"]}'
                           if urgent else ""),
            })
            return

        if path == "/api/import":
            ids = set(body.get("ids") or [])
            if not ids:
                self._send(200, {"ok": False, "message": "未选择任何条目"})
                return
            selected = [e for e in collect_events()
                        if e["id"] in ids and not e.get("completed")]
            if not selected:
                self._send(200, {"ok": False, "message": "所选条目均已导入或已完成"})
                return

            ok, msg = import_events(selected)
            self._send(200, {"ok": ok, "message": msg, "events": collect_events()})
            return

        if path == "/api/done":
            ev_id = body.get("id")
            undo = bool(body.get("undo"))
            ev = next((e for e in collect_events() if e["id"] == ev_id), None)
            if not ev:
                self._send(200, {"ok": False, "message": "未找到该条目"})
                return
            fp = backend.fingerprint(ev)
            done = load_completed()
            if undo:
                done.discard(fp)
            else:
                done.add(fp)
            save_completed(done)

            # 同步到系统（Mac 的提醒事项会打勾）。
            # AppleScript 首次唤起「提醒事项」可能要好几秒，且后台进程可能没权限
            # （会一直等到超时）。放到后台线程做，页面立即返回，不再卡住。
            if not undo:
                ev_snapshot = dict(ev)

                def _sync():
                    try:
                        backend.mark_complete(
                            ev_snapshot.get("company") or ev_snapshot.get("title", ""),
                            _cfg_list_name())
                    except Exception:
                        pass

                threading.Thread(target=_sync, daemon=True).start()

            self._send(200, {"ok": True, "sync": "后台同步中",
                             "events": collect_events()})
            return

        if path == "/api/email":
            # 返回某条事件对应邮件的完整正文与全部链接，供人工核对
            source_id = (body.get("source_id") or "").strip()
            subject = (body.get("subject") or "").strip()
            mail = _find_source_mail(source_id, subject)
            if not mail:
                self._send(200, {"ok": False,
                                 "message": "未找到原始邮件（可能扫描范围不含该邮件，"
                                            "试试扩大天数重新检索）"})
                return
            body_text = mail.get("body") or ""
            self._send(200, {
                "ok": True,
                "subject": mail.get("subject", ""),
                "sender": mail.get("sender", ""),
                "received_at": mail.get("received_at", ""),
                "body": body_text[:8000],
                "truncated": len(body_text) > 8000,
                "links": [{"url": u, "score": s}
                          for u, s in _rank_links(body_text)],
            })
            return

        if path == "/api/config-save":
            email = (body.get("email") or "").strip()
            code = (body.get("auth_code") or "").strip()
            host = (body.get("imap_host") or "").strip() or "imap.163.com"
            if "@" not in email:
                self._send(200, {"ok": False, "message": "邮箱地址格式不正确"})
                return
            if not code:
                self._send(200, {"ok": False, "message": "请填写授权码（不是登录密码）"})
                return

            cfg = {}
            cfg_path = os.path.join(BASE_DIR, "config.json")
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}
            if not cfg:
                example = os.path.join(BASE_DIR, "config.example.json")
                if os.path.exists(example):
                    with open(example, "r", encoding="utf-8") as f:
                        cfg = json.load(f)

            cfg["email"] = email
            cfg["auth_code"] = code
            cfg["imap_host"] = host
            cfg["imap_port"] = int(body.get("imap_port") or 993)
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)

            # 立即验证能否登录
            code_, out, err = run_script(["scan_mail.py", "--test-login"], timeout=60)
            if code_ == 0:
                self._send(200, {"ok": True, "message": "配置已保存，邮箱连接成功"})
            else:
                tail = (err or out).strip()[-200:]
                self._send(200, {"ok": False,
                                 "message": f"已保存，但连接失败：{tail}"})
            return

        if path == "/api/open-ics":
            ics_dir = os.path.join(DATA_DIR, "ics")
            if not os.path.exists(ics_dir):
                self._send(200, {"ok": False, "message": "尚无 .ics 文件"})
                return
            backend.open_path(ics_dir)
            self._send(200, {"ok": True, "message": f"已打开 {ics_dir}"})
            return

        self._send(404, {"error": "not found"})


def _configured():
    try:
        with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
            c = json.load(f)
        return bool(c.get("email")) and bool(c.get("auth_code"))
    except Exception:
        return False


SCAN_FILES = ("latest_scan.json", "all_scan.json")


def _iter_scan_mails():
    """遍历已保存的扫描结果里的原始邮件（懒加载，只读一次后缓存）。"""
    cache = getattr(_iter_scan_mails, "_cache", None)
    if cache is not None:
        return cache
    mails = []
    for name in SCAN_FILES:
        p = os.path.join(DATA_DIR, name)
        if not os.path.exists(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                mails.extend(json.load(f).get("emails", []))
        except Exception:
            continue
    _iter_scan_mails._cache = mails
    return mails


def _find_source_mail(source_id="", subject=""):
    """按 Message-ID 精确匹配，失败再按主题匹配（AI 精判条目的 id 是合成的）。"""
    mails = _iter_scan_mails()
    if source_id:
        for m in mails:
            if (m.get("message_id") or "").strip() == source_id:
                return m
    if subject:
        subj = subject.strip()
        for m in mails:
            if (m.get("subject") or "").strip() == subj:
                return m
        # 退一步：包含匹配，避免主题前后被加了前缀
        for m in mails:
            s = (m.get("subject") or "").strip()
            if s and (s in subj or subj in s):
                return m
    return None


def _rank_links(body_text):
    try:
        import parse_rules as PR
        return PR.extract_links_all({"body": body_text}, top=10)
    except Exception:
        import re
        urls = re.findall(r"https?://[^\s<>)\]\"'，。（）]+", body_text)
        seen, out = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append((u, 0))
        return out[:10]


def _cfg_list_name():
    try:
        with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
            return json.load(f).get("reminder_list", "求职待办")
    except Exception:
        return "求职待办"


def _last_update():
    """最近一次扫描/解析的时间，取数据文件中最新的修改时间。"""
    newest = None
    src = None
    for p, label in ((os.path.join(DATA_DIR, "events_confirmed.json"), "规则解析"),
                     (os.path.join(DATA_DIR, "events_ai.json"), "AI 精判"),
                     (os.path.join(DATA_DIR, "latest_scan.json"), "邮件扫描")):
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if newest is None or mt > newest:
            newest, src = mt, label
    if newest is None:
        return None, None, "从未扫描"
    dt = datetime.fromtimestamp(newest)
    mins = (datetime.now() - dt).total_seconds() / 60
    if mins < 2:
        text = "刚刚"
    elif mins < 60:
        text = f"{int(mins)} 分钟前"
    elif mins < 60 * 24:
        text = f"{int(mins / 60)} 小时前"
    else:
        text = f"{int(mins / 1440)} 天前"
    return dt.strftime("%Y-%m-%d %H:%M"), src, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    port = args.port
    for _ in range(10):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    else:
        print("找不到可用端口", file=sys.stderr)
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"
    bk, reason = backend.detect_backend()
    print(f"秋招邮件雷达看板已启动: {url}")
    print(f"写入后端: {bk}（{reason}）")
    print("按 Ctrl+C 停止\n")

    if not args.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    # 打开即更新：后台扫一次邮箱，避免每次都要手动点检索
    threading.Thread(target=startup_scan, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        httpd.shutdown()


if __name__ == "__main__":
    main()
