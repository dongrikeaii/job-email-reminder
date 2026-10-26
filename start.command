#!/bin/bash
# 双击启动看板（macOS）
# 从「终端」启动会继承终端的提醒事项权限，网页上的导入按钮才能真正写入
#
# 启动后 serve.py 会在后台自动扫描最近 N 天（默认 7）并把新条目导入提醒事项，
# 同时自动打开浏览器。全过程无需点任何按钮。
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

# 扫描统一交给 serve.py 的启动扫描处理（它会连扫带导入一起做）。
# 这里不再单独跑一次：run.sh 带 --force 会把 7 天内的邮件全部标记成「已处理」，
# 紧接着 serve.py 的常规扫描就会一封都读不到，自动导入随之失效。

exec "$PY" serve.py
