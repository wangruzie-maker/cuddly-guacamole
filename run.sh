#!/usr/bin/env bash
# 一键打开 Web 小工具（推荐）
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/open_app.sh"
