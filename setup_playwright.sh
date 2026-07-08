#!/usr/bin/env bash
# 视频号关键词发现需要 Playwright Chromium
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/Library/Caches/ms-playwright}"

echo "安装 Playwright Python 包..."
pip3 install playwright -q

echo "下载 Chromium 到: $PLAYWRIGHT_BROWSERS_PATH"
python3 -m playwright install chromium

echo "完成。可重新尝试视频号「发现链接」。"
