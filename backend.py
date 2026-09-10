#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
平台后端抽象层
把「写入系统提醒/日历」这一层按平台分派：
    darwin  -> AppleScript（提醒事项 / 日历）
    windows -> Outlook COM（任务 / 约会），不可用时退回 .ics 文件
    linux   -> 仅 .ics 文件

设计要点
--------
1. 跨进程一律用「临时文件」传参和回传结果，不走命令行参数，
   彻底规避 Windows 控制台 GBK/UTF-8 编码问题。
2. 所有后端返回统一结构 (ok: bool, msg: str)。
3. 写入前做去重，指纹存在 data/applied.json，避免定时任务重复灌入。
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WIN_PS = os.path.join(BASE_DIR, "win_outlook.ps1")
APPLIED_PATH = os.path.join(BASE_DIR, "data", "applied.json")

SYSTEM = platform.system().lower()  # darwin | windows | linux


# ---------------------------------------------------------------- 去重指纹
def fingerprint(ev):
    kind = (ev.get("kind") or "reminder").lower()
    key = "|".join([
        kind,
        str(ev.get("company") or ""),
        str(ev.get("event_type") or ""),
        str(ev.get("deadline") or ev.get("start") or ""),
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def load_applied():
    if os.path.exists(APPLIED_PATH):
        try:
            with open(APPLIED_PATH, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def mark_applied(fp):
    s = load_applied()
    s.add(fp)
    os.makedirs(os.path.dirname(APPLIED_PATH), exist_ok=True)
    with open(APPLIED_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(s), f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 后端探测
def detect_backend(prefer=None):
    """返回 (backend_name, reason)。backend: apple | outlook | ics"""
    if prefer in ("apple", "outlook", "ics"):
        return prefer, "用户指定"
    if SYSTEM == "darwin":
        return "apple", "macOS 原生"
    if SYSTEM == "windows":
        # 不使用 Outlook COM：新版 Outlook 不支持，且 COM 需要装 Office。
        # 统一导出 .ics，双击即可导入 Windows「日历」App，零依赖。
        return "ics", "Windows 统一导出 .ics（双击导入系统日历）"
    return "ics", f"{SYSTEM} 无原生提醒后端，使用 .ics 文件"


def _ps_outlook_available():
    ps = r"""
try {
  $ol = New-Object -ComObject Outlook.Application
  if ($ol -ne $null) { Write-Output "OK"; exit 0 }
  Write-Output "NULL"; exit 1
} catch { Write-Output $_.Exception.Message; exit 1 }
"""
    code, out, err = _run_powershell(ps)
    if code == 0 and out.strip().startswith("OK"):
        return True, ""
    return False, (out or err).strip()[:120] or "未安装 Outlook 桌面版"


def _find_powershell():
    for name in ("powershell", "pwsh"):
        p = _which(name)
        if p:
            return p
    for candidate in (
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        r"C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe",
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def _which(name):
    from shutil import which
    return which(name)


def _run_powershell(script):
    ps = _find_powershell()
    if not ps:
        return 1, "", "未找到 PowerShell"
    try:
        p = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True, timeout=120,
        )
        out = p.stdout.decode("utf-8", errors="replace")
        err = p.stderr.decode("utf-8", errors="replace")
        return p.returncode, out, err
    except subprocess.TimeoutExpired:
        return 1, "", "PowerShell 执行超时"


# ---------------------------------------------------------------- 事件写入
def create(ev, list_name, cal_name, alarm_minutes, backend=None, force=False):
    """写入单条事件，返回 (ok, msg)。"""
    backend = backend or detect_backend()[0]
    kind = (ev.get("kind") or "reminder").lower()
    fp = fingerprint(ev)

    if not force and fp in load_applied():
        return True, "已存在（跳过重复写入）"

    if backend == "apple":
        ok, msg = _create_apple(ev, list_name, cal_name, alarm_minutes)
    elif backend == "outlook":
        ok, msg = _create_outlook(ev, list_name, cal_name, alarm_minutes)
    else:
        ok, msg = _create_ics(ev, list_name, cal_name, alarm_minutes)

    if ok:
        mark_applied(fp)
    return ok, msg


# ---- macOS / AppleScript
def _create_apple(ev, list_name, cal_name, alarm_minutes):
    import apply_events as A  # 复用已验证的 AppleScript 构造逻辑
    kind = (ev.get("kind") or "reminder").lower()
    if kind == "event":
        script = A.build_event_script(ev, cal_name, alarm_minutes)
        target = f"日历 · {cal_name}"
    else:
        script = A.build_reminder_script(ev, list_name, alarm_minutes)
        target = f"提醒事项 · {list_name}"
    if script is None:
        return False, "缺少有效时间"
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if p.returncode == 0:
        return True, target
    return False, (p.stderr or p.stdout).strip()[:200]


# ---- Windows / Outlook COM
def _create_outlook(ev, list_name, cal_name, alarm_minutes):
    if not os.path.exists(WIN_PS):
        return False, f"缺少 {WIN_PS}"
    kind = (ev.get("kind") or "reminder").lower()
    action = "create-event" if kind == "event" else "create-reminder"
    payload = {
        "title": ev.get("title") or f'{ev.get("company","")} {ev.get("event_type","")}',
        "start": ev.get("start") or ev.get("deadline") or "",
        "end": ev.get("end") or "",
        "deadline": ev.get("deadline") or ev.get("start") or "",
        "link": ev.get("link") or "",
        "notes": ev.get("notes") or "",
        "folder": cal_name if kind == "event" else list_name,
        "alarm_minutes": int(ev.get("remind_before_minutes", alarm_minutes) or 0),
    }
    return _call_win_ps(action, payload)


def _call_win_ps(action, payload):
    """通过临时文件与 PowerShell 交换数据，规避编码问题。"""
    fd, in_path = tempfile.mkstemp(suffix=".json", prefix="jmr_in_")
    os.close(fd)
    out_path = in_path.replace("jmr_in_", "jmr_out_").replace(".json", ".txt")
    try:
        with open(in_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

        ps = (
            f'& "{WIN_PS}" -Action "{action}" '
            f'-PayloadFile "{in_path}" -ResultFile "{out_path}"'
        )
        code, out, err = _run_powershell(ps)

        result = ""
        if os.path.exists(out_path):
            with open(out_path, "r", encoding="utf-8", errors="replace") as f:
                result = f.read().strip()

        # 结果文件第一行 OK/ERR，其余为消息
        lines = result.splitlines()
        status = lines[0].strip() if lines else ""
        msg = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        if status == "OK":
            return True, msg or "已写入 Outlook"
        return False, msg or (err or out).strip()[:200] or f"退出码 {code}"
    finally:
        for p in (in_path, out_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass


# ---- 通用兜底 / .ics
def _create_ics(ev, list_name, cal_name, alarm_minutes):
    try:
        import export_ics as E
    except ImportError:
        return False, "缺少 export_ics.py"
    out_dir = os.path.join(BASE_DIR, "data", "ics")
    os.makedirs(out_dir, exist_ok=True)
    safe = "".join(c for c in (ev.get("title") or "event")
                   if c not in '\\/:*?"<>|').strip() or "event"
    path = os.path.join(out_dir, f"{safe}.ics")
    try:
        E.export_events([ev], path, alarm_minutes=alarm_minutes)
        return True, f"已生成 {os.path.relpath(path, BASE_DIR)}"
    except Exception as e:
        return False, str(e)[:200]


# ---------------------------------------------------------------- 完成状态
def list_items(list_name, backend=None):
    """返回 [{'title':str,'due':str,'completed':bool}, ...]"""
    backend = backend or detect_backend()[0]
    if backend == "apple":
        import complete as C
        return [{"title": n, "due": d, "completed": st == "已完成"}
                for st, n, d in C.list_items(list_name)]
    if backend == "outlook":
        ok, msg = _call_win_ps("list", {"folder": list_name})
        if not ok:
            print(f"[错误] {msg}", file=sys.stderr)
            return []
        try:
            data = json.loads(msg or "[]")
            if isinstance(data, dict):
                data = [data]
            return [{"title": r.get("title", ""), "due": r.get("due", ""),
                     "completed": bool(r.get("completed"))} for r in data]
        except Exception as e:
            print(f"[错误] 解析 Outlook 返回失败: {e}", file=sys.stderr)
            return []
    print("[提示] 当前为 .ics 后端，无系统待办列表可读", file=sys.stderr)
    return []


def mark_complete(keyword, list_name, backend=None, undo=False):
    """标记/取消完成，返回 (ok, msg)"""
    backend = backend or detect_backend()[0]
    if backend == "apple":
        import complete as C
        ok = C.toggle(list_name, keyword, completed=not undo)
        return ok, ("已在提醒事项中更新" if ok else f"未匹配「{keyword}」")
    if backend == "outlook":
        action = "uncomplete" if undo else "complete"
        return _call_win_ps(action, {"folder": list_name, "keyword": keyword})
    return False, "当前为 .ics 后端，无系统待办可标记"


def open_path(path):
    """跨平台用默认程序打开。"""
    try:
        if SYSTEM == "darwin":
            subprocess.run(["open", path], check=False)
        elif SYSTEM == "windows":
            os.startfile(path)  # noqa: S606 - 仅打开用户自己的文件
        else:
            subprocess.run(["xdg-open", path], check=False)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    b, reason = detect_backend()
    print(f"系统: {platform.system()} ({platform.release()})")
    print(f"后端: {b}  ——  {reason}")
