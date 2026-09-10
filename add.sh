#!/bin/bash
# 手动补录一条事件（比如电话通知的面试）
# 用法:
#   ./add.sh --company "字节跳动" --type "AI面试" --deadline "2026-09-12 23:59" --link "https://..."
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
# 自动探测 Python：WorkBuddy 自带 > 系统 python3 > python
# 自动探测 Python：WorkBuddy 自带 > 系统 python3 > python（不含本机用户名）
PY=""
for cand in "$HOME"/.workbuddy/binaries/python/versions/*/bin/python3; do
  [ -x "$cand" ] && PY="$cand"
done
[ -n "$PY" ] || PY="$(command -v python3 || command -v python)"

COMPANY=""; TYPE="招聘事件"; DEADLINE=""; LINK=""; NOTES=""
while [ $# -gt 0 ]; do
  case "$1" in
    --company) COMPANY="$2"; shift 2;;
    --type) TYPE="$2"; shift 2;;
    --deadline) DEADLINE="$2"; shift 2;;
    --link) LINK="$2"; shift 2;;
    --notes) NOTES="$2"; shift 2;;
    *) echo "未知参数: $1"; exit 1;;
  esac
done

if [ -z "$DEADLINE" ]; then echo "必须提供 --deadline \"YYYY-MM-DD HH:MM\""; exit 1; fi

cat > "$DIR/data/manual_event.json" <<EOF
{"events":[{"company":"$COMPANY","event_type":"$TYPE","title":"$COMPANY $TYPE",
"kind":"reminder","deadline":"$DEADLINE","link":"$LINK","notes":"$NOTES"}]}
EOF

"$PY" "$DIR/apply_events.py" "$DIR/data/manual_event.json"
