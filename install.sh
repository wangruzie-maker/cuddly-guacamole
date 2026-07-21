#!/usr/bin/env bash
# 同事本机完整安装（写入项目 .venv，避开系统/uv 托管限制）
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo ">>> 检测并安装能力（含创建 .venv）"
bash "$DIR/ensure_capabilities.sh" --manual

echo ""
echo "安装完成。启动方式："
echo "  ./open_app.sh          # 正式使用"
echo "  ./open_demo.sh         # 体验版演示"
echo ""
echo "小红书采集库已随工具内置（vendor/redbook-skills）。"
echo "首次使用请在网页点击「登录小红书」完成扫码。"
