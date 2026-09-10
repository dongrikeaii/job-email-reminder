#!/bin/bash
# 秋招邮件雷达 - 全自动流水线（供 launchd 定时调用，也可手动执行）
#   扫描邮箱 → 规则解析 → 写入「提醒事项」/「日历」
#
# 用法:
#   ./run.sh                # 一键跑完整流程
#   ./run.sh --days 30      # 扫描最近 30 天
#   ./run.sh --dry-run      # 只预览，不写入
#   ./run.sh --scan-only    # 只扫描解析，不写系统 App（定时任务默认用这个）
set -u

# 把 --scan-only 从传给 scan_mail.py 的参数里剔除
SCAN_ONLY=0
ARGS=()
for a in "$@"; do
  if [ "$a" = "--scan-only" ]; then SCAN_ONLY=1; else ARGS+=("$a"); fi
done

DIR="$(cd "$(dirname "$0")" && pwd)"
# 自动探测 Python：WorkBuddy 自带 > 系统 python3 > python（不含本机用户名）
PY=""
for cand in "$HOME"/.workbuddy/binaries/python/versions/*/bin/python3; do
  [ -x "$cand" ] && PY="$cand"
done
[ -n "$PY" ] || PY="$(command -v python3 || command -v python)"
mkdir -p "$DIR/data" "$DIR/logs"

LOG="$DIR/logs/run-$(date +%Y%m%d).log"
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 开始扫描 =====" >>"$LOG"

# 1) 扫描（${ARGS[@]+...} 写法：兼容 bash 3.2 的 set -u 空数组）
if ! "$PY" "$DIR/scan_mail.py" ${ARGS[@]+"${ARGS[@]}"} >"$DIR/data/latest_scan.json" 2>>"$LOG"; then
  echo "扫描失败，详见 $LOG" >&2
  exit 1
fi
N=$("$PY" -c "import json;print(json.load(open('$DIR/data/latest_scan.json')).get('matched',0))" 2>/dev/null || echo 0)
echo "匹配到 $N 封候选邮件" >>"$LOG"

# 2) 规则解析
"$PY" "$DIR/parse_rules.py" "$DIR/data/latest_scan.json" -o "$DIR/data/events.json" >>"$LOG" 2>&1

# 3) 剔除需要人工确认的低置信度条目
"$PY" - "$DIR/data/events.json" "$DIR/data/events_confirmed.json" <<'EOF' >>"$LOG" 2>&1
import json,sys
d=json.load(open(sys.argv[1]))
d["events"]=[e for e in d["events"] if not e.get("needs_review") and e.get("deadline")]
json.dump(d,open(sys.argv[2],"w"),ensure_ascii=False,indent=2)
print("确认写入:",len(d["events"]))
EOF

# 3.5) 并入累积事件库，保证看板不会因邮件去重而被清空
"$PY" "$DIR/merge_store.py" "$DIR/data/events_confirmed.json" >>"$LOG" 2>&1

# 4) 写入系统 App
if [ "$SCAN_ONLY" = "1" ]; then
  echo "（--scan-only 模式，跳过写入；打开看板点「导入」即可写入）" 2>&1 | tee -a "$LOG"
elif [ "${1:-}" = "--dry-run" ]; then
  "$PY" "$DIR/apply_events.py" "$DIR/data/events_confirmed.json" --dry-run 2>&1 | tee -a "$LOG"
else
  "$PY" "$DIR/apply_events.py" "$DIR/data/events_confirmed.json" 2>&1 | tee -a "$LOG"
fi

echo "===== 结束 =====" >>"$LOG"
