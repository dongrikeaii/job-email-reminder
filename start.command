#!/bin/bash
# 双击启动看板（macOS）
# 从「终端」启动会继承终端的提醒事项权限，网页上的导入按钮才能真正写入
#
# 启动时会先在后台跑一次扫描（--scan-only），
# 这样即使没有装定时任务，每次打开看板看到的也是最新数据。
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1

# 自动探测 Python：WorkBuddy 自带 > 系统 python3 > python（不含本机用户名）
PY=""
for cand in "$HOME"/.workbuddy/binaries/python/versions/*/bin/python3; do
  [ -x "$cand" ] && PY="$cand"
done
[ -n "$PY" ] || PY="$(command -v python3 || command -v python)"

if [ -z "$PY" ]; then
  echo "未找到 Python 3，请先安装或联系管理员配置路径。"
  read -r -p "按回车退出..."
  exit 1
fi

# 后台刷新一次数据（不阻塞开网页；失败也不影响看板打开）
( "$PY" merge_store.py data/events_confirmed.json >/dev/null 2>&1
  bash "$DIR/run.sh" --scan-only --days 7 --force >/dev/null 2>&1 ) &

exec "$PY" serve.py
