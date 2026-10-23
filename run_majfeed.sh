#!/usr/bin/env bash
set -euo pipefail

# 1. 补全 PATH（uv 默认装在 ~/.local/bin）
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

# 2. 固定工作目录
cd ~/MajFeed

# 3. 防止重叠运行
exec 9>/tmp/majfeed.lock
flock -n 9 || { echo "$(date -Is) 上一轮仍在运行，跳过"; exit 0; }

echo "$(date -Is) 开始"
uv run --locked --no-dev --env-file .env python src/main.py
echo "$(date -Is) 结束"