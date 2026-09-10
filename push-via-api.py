#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过 GitHub REST API 推送仓库（不依赖 git push / github.com 域名）。

适用场景：网络出口只允许访问 api.github.com 与 uploads.github.com，
git 的 HTTPS 通道与 OAuth 设备登录（github.com）被拦截时。

用法:
    python3 push-via-api.py <REPO_NAME> [--private] [--token TOKEN]
                            [--owner OWNER] [--asset 文件.zip] [--tag v1.0]

流程:
    1. 创建仓库（若已存在则复用）
    2. 用 Git Data API 一次性建树 + 提交 + 指向 main
    3. 可选：创建 Release 并上传附件（走 uploads.github.com）
"""
import argparse
import base64
import json
import mimetypes
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
UA = "job-mail-radar-publisher/1.0"


def req(method, url, token, data=None, raw=False, timeout=120):
    body = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": UA,
    }
    if data is not None:
        body = data if raw else json.dumps(data, ensure_ascii=False).encode("utf-8")
        if not raw:
            headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            payload = resp.read()
            return resp.status, (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload) if payload else {}
        except Exception:
            return e.code, {"message": payload[:400].decode("utf-8", "replace")}
    except Exception as e:
        return 0, {"message": str(e)}


def git_tracked_files(root):
    out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True)
    return [l for l in out.stdout.split("\n") if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    ap.add_argument("--owner", default="")
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--asset", default="")
    ap.add_argument("--tag", default="v1.0")
    args = ap.parse_args()

    token = args.token.strip()
    if not token:
        print("[错误] 缺少 GitHub Token。用 --token 或设置环境变量 GITHUB_TOKEN", file=sys.stderr)
        sys.exit(2)

    root = os.path.dirname(os.path.abspath(__file__))

    # --- 1. 确认身份 ---
    code, me = req("GET", f"{API}/user", token)
    if code != 200:
        print(f"[错误] Token 无效或无法访问 API（HTTP {code}）: {me.get('message')}", file=sys.stderr)
        sys.exit(3)
    owner = args.owner or me["login"]
    print(f"  已认证为: {owner}")

    # --- 2. 创建/复用仓库 ---
    code, repo = req("POST", f"{API}/user/repos", token, {
        "name": args.repo,
        "description": "秋招邮件雷达：扫描求职邮箱，识别测评/笔试/AI面试截止时间，本地网页一键检索并导入系统提醒",
        "private": args.private,
        "auto_init": False,
        "has_issues": True,
        "has_wiki": False,
    })
    if code == 201:
        print(f"  仓库已创建: {repo['full_name']}")
    elif code == 422:
        code, repo = req("GET", f"{API}/repos/{owner}/{args.repo}", token)
        if code != 200:
            print(f"[错误] 仓库已存在但无法访问: {repo.get('message')}", file=sys.stderr)
            sys.exit(4)
        print(f"  复用已有仓库: {repo['full_name']}")
    else:
        print(f"[错误] 创建仓库失败（HTTP {code}）: {repo.get('message')}", file=sys.stderr)
        sys.exit(4)

    full = repo["full_name"]
    default_branch = repo.get("default_branch") or "main"

    # --- 2.5 空仓库初始化 ---
    # 刚创建且 auto_init=false 的仓库没有任何 ref，直接 POST /git/trees 会报
    # 409 "Git Repository is empty."，故先用 Contents API 落一个初始提交。
    code, _ = req("GET", f"{API}/repos/{full}/git/ref/heads/{default_branch}", token)
    if code != 200:
        print("  空仓库，正在初始化…")
        code, init = req("PUT", f"{API}/repos/{full}/contents/README.md", token, {
            "message": "chore: 初始化仓库",
            "content": base64.b64encode(b"# job-email-reminder\n\ninitializing\n").decode("ascii"),
            "branch": default_branch,
        })
        if code not in (201, 200):
            print(f"[错误] 初始化失败（HTTP {code}）: {init.get('message')}", file=sys.stderr)
            sys.exit(4)

    # --- 3. 建树 ---
    files = git_tracked_files(root)
    if not files:
        print("[错误] git ls-files 为空，请先 git add", file=sys.stderr)
        sys.exit(5)

    tree = []
    for rel in files:
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            continue
        with open(p, "rb") as f:
            content = f.read()
        mode = "100755" if os.access(p, os.X_OK) else "100644"
        tree.append({
            "path": rel.replace(os.sep, "/"),
            "mode": mode,
            "type": "blob",
            "content": base64.b64encode(content).decode("ascii"),
            "encoding": "base64",
        })
    print(f"  待上传 {len(tree)} 个文件")

    code, t = req("POST", f"{API}/repos/{full}/git/trees", token, {"tree": tree})
    if code != 201:
        print(f"[错误] 建树失败（HTTP {code}）: {t.get('message')}", file=sys.stderr)
        sys.exit(6)

    # --- 4. 提交 ---
    msg = ("feat: 秋招邮件雷达 - 招聘邮件截止时间自动提取与提醒\n\n"
           "扫描求职邮箱，识别测评/笔试/AI面试等邀请邮件的截止时间，\n"
           "通过本地网页一键检索并导入系统提醒（macOS 提醒事项/日历，Windows/Linux 导出 .ics）。\n\n"
           "- IMAP 只读扫描 + 关键词粗筛，排除词只扫主题与正文前段，避免页脚误杀\n"
           "- 双解析路径：AI 精判（准确）与正则兜底（零成本，供定时任务）\n"
           "- 本地网页看板：一键检索导入、精确到小时的实时倒计时、分组与完成标记\n"
           "- 累积事件库，跨扫描保留，避免去重导致看板清空\n"
           "- 跨平台后端分派，自动选择 apple / outlook / ics\n"
           "- macOS launchd 与 Windows 计划任务支持，每日自动扫描")
    code, c = req("POST", f"{API}/repos/{full}/git/commits", token,
                  {"message": msg, "tree": t["sha"], "parents": []})
    if code != 201:
        print(f"[错误] 创建提交失败（HTTP {code}）: {c.get('message')}", file=sys.stderr)
        sys.exit(7)
    print(f"  提交已创建: {c['sha'][:8]}")

    # --- 5. 指向分支 ---
    code, ref = req("GET", f"{API}/repos/{full}/git/ref/heads/{default_branch}", token)
    if code == 200:
        code, ref = req("PATCH", f"{API}/repos/{full}/git/refs/heads/{default_branch}",
                        token, {"sha": c["sha"], "force": True})
    else:
        code, ref = req("POST", f"{API}/repos/{full}/git/refs", token,
                        {"ref": f"refs/heads/{default_branch}", "sha": c["sha"]})
    if code not in (200, 201):
        print(f"[错误] 更新分支失败（HTTP {code}）: {ref.get('message')}", file=sys.stderr)
        sys.exit(8)
    print(f"  {default_branch} 已指向最新提交")

    print(f"\n[OK] 推送完成: https://github.com/{full}")

    # --- 6. Release + 附件 ---
    if args.asset and os.path.isfile(args.asset):
        code, rel = req("POST", f"{API}/repos/{full}/releases", token, {
            "tag_name": args.tag,
            "name": f"v1.0 — 首个正式版",
            "body": ("首个可用版本。\n\n"
                     "**macOS**：`start.command` 启动网页看板 → 填邮箱授权码 → 一键检索并导入提醒事项/日历。\n"
                     "**Windows**：解压 `job-mail-radar-win.zip` → 双击 `start-windows.bat`。\n\n"
                     "隐私：邮件只读拉取，全程本机处理。"),
            "draft": False,
            "prerelease": False,
        })
        if code not in (201, 422):
            print(f"  [警告] 创建 Release 失败（HTTP {code}）: {rel.get('message')}")
            return
        upload_url = rel.get("upload_url", "").replace("{?name,label}", "")
        if not upload_url:
            print("  [警告] 未拿到上传地址")
            return
        upload_url = upload_url.replace(API, UPLOADS) if upload_url.startswith(API) else upload_url

        name = os.path.basename(args.asset)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(args.asset, "rb") as f:
            blob = f.read()
        r = urllib.request.Request(
            f"{upload_url}?name={urllib.parse.quote(name)}",
            data=blob,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": ctype,
                     "User-Agent": UA},
            method="POST",
        )
        try:
            with urllib.request.urlopen(r, timeout=300) as resp:
                print(f"  附件已上传: {name}（{len(blob)//1024} KB）")
        except Exception as e:
            print(f"  [警告] 附件上传失败: {e}")
            return
        print(f"  Release: https://github.com/{full}/releases/tag/{args.tag}")


if __name__ == "__main__":
    import urllib.parse  # noqa: E402
    main()
