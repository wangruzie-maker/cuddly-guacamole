#!/bin/bash
cd "$(dirname "$0")"
chmod +x open_demo.sh demo/load_sample_data.sh 2>/dev/null || true
./open_demo.sh
echo ""
read -r -p "按回车键关闭此窗口…" _
