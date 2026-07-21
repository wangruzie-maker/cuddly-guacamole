#!/usr/bin/env bash
# 同事本机完整安装（链接提取 + 口播转写 + 可选 Playwright）
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo ">>> 1/3 安装 Python 依赖"
pip3 install -r requirements.txt

echo ""
echo ">>> 2/3 下载 Whisper 语音识别模型（small，国内建议镜像）"
if [[ -z "${HF_ENDPOINT:-}" ]]; then
  export HF_ENDPOINT="https://hf-mirror.com"
  echo "    使用镜像: $HF_ENDPOINT"
fi
bash "$DIR/setup_whisper.sh"

echo ""
echo ">>> 3/3 可选：Playwright（视频号发现 / 浏览器备用）"
read -r -p "是否安装 Playwright Chromium？[y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
  bash "$DIR/setup_playwright.sh"
else
  echo "    已跳过。需要时可运行: ./setup_playwright.sh"
fi

echo ""
echo "安装完成。启动方式："
echo "  ./open_app.sh          # 正式使用"
echo "  ./open_demo.sh         # 体验版演示"
echo ""
echo "小红书采集库已随工具内置（vendor/redbook-skills）。"
echo "首次使用请在网页点击「登录小红书」完成扫码。"
