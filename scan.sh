#!/bin/bash
# 秋招邮件雷达 - 一键扫描（只输出候选邮件 JSON，供 AI 解析）
# 用法: ./scan.sh [--days 7] [--all] [--force]
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
# 自动探测 Python：WorkBuddy 自带 > 系统 python3 > python
# 自动探测 Python：WorkBuddy 自带 > 系统 python3 > python（不含本机用户名）
PY=""
for cand in "$HOME"/.workbuddy/binaries/python/versions/*/bin/python3; do
  [ -x "$cand" ] && PY="$cand"
done
[ -n "$PY" ] || PY="$(command -v python3 || command -v python)"
exec "$PY" "$DIR/scan_mail.py" "$@"
