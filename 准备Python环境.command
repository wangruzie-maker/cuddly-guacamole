#!/bin/bash
# 同事通用设备：准备 Python 3.12（官方安装包 / Homebrew）
cd "$(dirname "$0")" || exit 1
chmod +x bootstrap_python.sh python_env.sh 2>/dev/null || true
echo ""
/bin/bash ./bootstrap_python.sh
ec=$?
echo ""
read -r -p "按回车键关闭此窗口…" _
exit "$ec"
