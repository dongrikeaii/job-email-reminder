#!/bin/bash
# 一键发布到 GitHub
#
# 用法（在自己的「终端」App 里跑，不要用其他受限 shell）：
#   ./publish-github.sh                       # 默认仓库名 job-email-reminder，公开
#   ./publish-github.sh my-repo private       # 自定义仓库名与可见性
#
# 流程：检查登录 → 打包 Windows 端 zip → 建仓库并推送 → 发 Release 附 zip
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1

REPO="${1:-job-email-reminder}"
VIS="${2:-public}"
TAG="v1.0"

echo "=============================================="
echo " 秋招邮件雷达 → GitHub"
echo " 仓库：${REPO}（${VIS}）"
echo "=============================================="
echo

# ---------- 1. 登录 ----------
if ! gh auth status >/dev/null 2>&1; then
  echo "[1/4] 未登录，启动浏览器授权…"
  echo "     终端里会出现一行 “First copy your one-time code: XXXX-XXXX”，"
  echo "     把那串填进自动打开的网页即可。"
  echo
  gh auth login --web --git-protocol https
  if ! gh auth status >/dev/null 2>&1; then
    echo "登录未完成，中止。" >&2
    exit 1
  fi
else
  echo "[1/4] 已登录，跳过"
fi

OWNER="$(gh api user --jq .login 2>/dev/null)"
echo "     账号：$OWNER"
echo

# ---------- 2. 打包 Windows 端 ----------
echo "[2/4] 打包分发包…"
if [ -f ./package.sh ]; then
  ./package.sh >/dev/null 2>&1
fi
ZIP="$(dirname "$DIR")/job-mail-radar-win.zip"
[ -f "$ZIP" ] && echo "     已生成：$(basename "$ZIP")" || echo "     未生成 zip（不影响推送）"
echo

# ---------- 3. 提交并推送 ----------
echo "[3/4] 提交并推送…"
git config user.name  >/dev/null 2>&1 || git config user.name  "ethan"
git config user.email >/dev/null 2>&1 || git config user.email "ethan@users.noreply.github.com"

if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -q -m "chore: 发布前更新"
fi

if gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  echo "     仓库已存在，关联并推送…"
  git remote remove origin 2>/dev/null
  git remote add origin "https://github.com/$OWNER/$REPO.git"
  git branch -M main 2>/dev/null
  git push -u origin main
else
  gh repo create "$REPO" "--$VIS" --source=. --remote=origin --push
fi
echo

# ---------- 4. Release ----------
echo "[4/4] 发布 Release ${TAG} …"
NOTES="首个可用版本。

## 功能
- IMAP 只读扫描求职邮箱，识别测评 / 笔试 / AI面试 / 宣讲会的截止时间
- 本地网页看板：一键检索并导入，卡片实时倒计时（精度到小时）
- 跨平台：macOS 写入提醒事项与日历；Windows / Linux 导出 .ics
- 每日自动更新：打开看板即扫描，或挂 launchd / 计划任务
- 累积事件库，去重后不会丢历史条目

## 安装
**macOS**：\`git clone\` 后 \`cp config.example.json config.json\` 填邮箱与 IMAP 授权码，双击 \`start.command\`
**Windows**：下载下方 \`job-mail-radar-win.zip\`，解压后双击 \`start-windows.bat\`

## 隐私
邮件只读拉取，全程本机处理；\`config.json\` 与 \`data/\` 已在 .gitignore 中排除。"

if [ -f "$ZIP" ]; then
  gh release create "$TAG" "$ZIP" --title "$TAG 首个版本" --notes "$NOTES" 2>/dev/null \
    || gh release create "$TAG" --title "$TAG 首个版本" --notes "$NOTES"
else
  gh release create "$TAG" --title "$TAG 首个版本" --notes "$NOTES"
fi

echo
echo "完成：https://github.com/$OWNER/$REPO"
