#!/bin/bash
# 正式版 / 离线即用版入口
cd "$(dirname "$0")"
# 减轻 macOS 对未签名脚本的隔离拦截
xattr -dr com.apple.quarantine . 2>/dev/null || true
chmod +x open_app.sh ensure_capabilities.sh pack_offline.sh 2>/dev/null || true
./open_app.sh
echo ""
read -r -p "按回车键关闭此窗口…" _
