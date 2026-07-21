#!/bin/bash
# 正式版入口：启动前会检测缺失能力并征求同意后安装
cd "$(dirname "$0")"
chmod +x open_app.sh ensure_capabilities.sh 2>/dev/null || true
./open_app.sh
echo ""
read -r -p "按回车键关闭此窗口…" _
