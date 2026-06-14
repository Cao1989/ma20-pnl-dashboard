#!/bin/bash
# 一键推送到 GitHub
# 使用方法：在你的电脑终端运行此脚本

cd "$(dirname "$0")"

# 初始化（如果还没有 git）
if [ ! -d ".git" ]; then
  git init
  git config user.email "vking@local"
  git config user.name "vking"
  git branch -M main
  git remote add origin https://Cao1989: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@github.com/Cao1989/ma20-pnl-dashboard.git
fi

git add .
git commit -m "update: MA20云端迁移 $(date '+%Y-%m-%d %H:%M')"
git push -f origin main

echo ""
echo "✅ 推送完成！"
echo "📋 下一步："
echo "1. 打开 https://github.com/Cao1989/ma20-pnl-dashboard/settings/secrets/actions"
echo "2. 添加 Secret: FEISHU_APP_ID = cli_aaa46b08cab8dceb"
echo "3. 添加 Secret: FEISHU_APP_SECRET = ZtVJXwOLOQPDpSYVgeP1Nddwf5IDWAzc"
echo "4. 打开 https://github.com/Cao1989/ma20-pnl-dashboard/settings/pages"
echo "5. Source 选 GitHub Actions，保存"
echo "6. 打开 https://github.com/Cao1989/ma20-pnl-dashboard/actions 手动触发一次测试"
