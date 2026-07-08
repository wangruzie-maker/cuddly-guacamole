#!/bin/bash
# 正式版入口（非体验版演示数据）
cd "$(dirname "$0")"
chmod +x open_app.sh 2>/dev/null || true
./open_app.sh
echo ""
read -r -p "按回车键关闭此窗口…" _
