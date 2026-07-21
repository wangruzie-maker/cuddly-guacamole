#!/bin/bash
# 手动检测本机能力并征得同意后安装（推荐首次使用先点这个）
cd "$(dirname "$0")"
chmod +x ensure_capabilities.sh 2>/dev/null || true
echo ""
./ensure_capabilities.sh --manual
echo ""
read -r -p "按回车键关闭此窗口…" _
