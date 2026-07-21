#!/bin/bash
# 手动检测本机能力并征得同意后安装（推荐首次使用先点这个）
cd "$(dirname "$0")" || exit 1
chmod +x ensure_capabilities.sh python_env.sh open_app.sh 2>/dev/null || true
echo ""
echo "正在检测能力（bash $(/bin/bash --version | head -1)）…"
echo ""
/bin/bash ./ensure_capabilities.sh --manual
ec=$?
echo ""
if [[ $ec -ne 0 ]]; then
  echo "检测/安装未完成（退出码 $ec）。可把上方报错截图发负责人。"
fi
echo ""
read -r -p "按回车键关闭此窗口…" _
exit "$ec"
