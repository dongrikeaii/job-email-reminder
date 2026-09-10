#!/bin/bash
# 打包成可分发的 zip，供其他电脑（Windows / macOS / Linux）安装
#
# 自动排除：
#   config.json      含 IMAP 授权码
#   data/            含已下载的邮件正文
#   logs/ __pycache__/
#
# 用法: ./package.sh [输出路径]
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$(dirname "$DIR")/job-mail-radar-win.zip}"
STAGE="$(mktemp -d)/job-mail-radar"

mkdir -p "$STAGE"
cd "$DIR" || exit 1

# 复制全部源码（不含排除项）
rsync -a --exclude 'config.json' \
         --exclude 'data/' \
         --exclude 'logs/' \
         --exclude '__pycache__/' \
         --exclude '.git/' \
         --exclude '*.pyc' \
         ./ "$STAGE/" 2>/dev/null || {
  # 无 rsync 时退回 tar
  tar --exclude='config.json' --exclude='./data' --exclude='./logs' \
      --exclude='./__pycache__' --exclude='./.git' -cf - . | (cd "$STAGE" && tar -xf -)
}

# 技能文件随包分发，供 Windows 安装脚本复制到 ~/.workbuddy/skills
cp ~/.workbuddy/skills/job-mail-radar/SKILL.md "$STAGE/SKILL.md" 2>/dev/null || true

# 保证目录结构存在
mkdir -p "$STAGE/data" "$STAGE/logs"
touch "$STAGE/data/.gitkeep" "$STAGE/logs/.gitkeep"

# PowerShell 5.1 需要 UTF-8 BOM 才能正确读中文
for f in "$STAGE"/*.ps1; do
  [ -f "$f" ] || continue
  if ! head -c 3 "$f" | grep -q $'\xef\xbb\xbf'; then
    printf '\xef\xbb\xbf' > "$f.bom" && cat "$f" >> "$f.bom" && mv "$f.bom" "$f"
  fi
done
# .bat 用 GBK 更稳（chcp 65001 已在文件内设置，故保持 UTF-8 无 BOM）

rm -f "$OUT"
(cd "$(dirname "$STAGE")" && zip -rq "$OUT" job-mail-radar -x '*.DS_Store')

echo "已打包: $OUT"
echo "内容："
(cd "$STAGE" && find . -type f | sort | sed 's|^\./|  |')
echo
echo "体积: $(du -h "$OUT" | cut -f1)"
rm -rf "$(dirname "$STAGE")"
