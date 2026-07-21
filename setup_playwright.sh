#!/usr/bin/env bash
# 视频号关键词发现需要 Playwright Chromium
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
# shellcheck source=python_env.sh
source "$DIR/python_env.sh"
resolve_python_bin
if [[ -x "$DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$DIR/.venv/bin/python"
fi

export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/Library/Caches/ms-playwright}"

echo "安装 Playwright Python 包到当前环境: $PYTHON_BIN"
"$PYTHON_BIN" -m pip install playwright -q

echo "下载 Chromium 到: $PLAYWRIGHT_BROWSERS_PATH"
"$PYTHON_BIN" -m playwright install chromium

echo "完成。可重新尝试视频号「发现链接」。"
