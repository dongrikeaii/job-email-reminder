#!/bin/bash
# 安装 macOS 每日自动扫描（launchd）
#
# 说明：后台进程拿不到 AppleScript 授权（不会弹权限窗，会直接静默失败），
#       所以定时任务只做「扫描 + 解析」，把数据更新到看板；
#       真正写入提醒事项，由你在看板里点「一键检索并导入」完成。
#
# 用法:
#   ./install-schedule.sh          # 安装（每天 09:00 / 21:00）
#   ./install-schedule.sh --uninstall
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.jobmailradar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGDIR="$DIR/logs"

# 自动探测 Python：WorkBuddy 自带 > 系统 python3 > python（不含本机用户名）
PY=""
for cand in "$HOME"/.workbuddy/binaries/python/versions/*/bin/python3; do
  [ -x "$cand" ] && PY="$cand"
done
[ -n "$PY" ] || PY="$(command -v python3 || command -v python)"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl unload -w "$PLIST" 2>/dev/null
  rm -f "$PLIST"
  echo "已卸载定时任务"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"

cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$DIR/run.sh</string>
        <string>--scan-only</string>
        <string>--days</string>
        <string>7</string>
        <string>--force</string>
    </array>

    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
    </array>

    <key>RunAtLoad</key>
    <false/>

    <key>StandardOutPath</key>
    <string>$LOGDIR/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$LOGDIR/launchd.err.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
EOF

launchctl unload -w "$PLIST" 2>/dev/null
launchctl load -w "$PLIST" 2>/dev/null

# 校验是否真的进了 launchd 域。有些受限环境（如沙箱 shell）里
# launchctl load 会返回成功但实际没注册，此时会提示用户手动执行。
if launchctl list 2>/dev/null | grep -q "$LABEL"; then
  echo "已安装并加载定时任务：$LABEL"
  LOADED=1
else
  echo "已写入配置文件，但当前环境未能向 launchd 注册。" >&2
  echo "请在「终端」App 里手动执行一次：" >&2
  echo "    launchctl load -w ~/Library/LaunchAgents/$LABEL.plist" >&2
  LOADED=0
fi

echo
echo "  配置文件：$PLIST"
echo "  执行时间：每天 09:00 与 21:00"
echo "  执行内容：扫描邮箱 + 解析截止时间（不写入系统，避免后台权限失败）"
echo "  Python：  $PY"
echo "  日志：    $LOGDIR/launchd.log"
echo
echo "  查看状态：launchctl list | grep $LABEL"
[ "$LOADED" = "1" ] && echo "  立即试跑：launchctl start $LABEL"
echo "  卸载：    $0 --uninstall"
