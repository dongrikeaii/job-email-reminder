#!/bin/bash
# 把「求职待办」里的提醒标记为完成
# 用法:
#   ./done.sh --list              列出待办与状态
#   ./done.sh "达能"               标为完成（支持模糊匹配）
#   ./done.sh "达能" "雀巢"         一次多个
#   ./done.sh "达能" --undo        撤销完成
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
# 自动探测 Python：WorkBuddy 自带 > 系统 python3 > python
# 自动探测 Python：WorkBuddy 自带 > 系统 python3 > python（不含本机用户名）
PY=""
for cand in "$HOME"/.workbuddy/binaries/python/versions/*/bin/python3; do
  [ -x "$cand" ] && PY="$cand"
done
[ -n "$PY" ] || PY="$(command -v python3 || command -v python)"
exec "$PY" "$DIR/complete.py" "$@"
