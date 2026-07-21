#!/usr/bin/env bash
# 为同事通用 Mac 准备可用的 Python 3.12（官方安装包或 Homebrew）
# 不依赖开发者本机的 uv / 自定义环境。
set -eo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
# shellcheck source=python_env.sh
source "$DIR/python_env.sh"

# 官方 macOS Universal2 安装包（Intel + Apple Silicon 通用）
PY_VER="3.12.10"
PY_PKG_URL="https://www.python.org/ftp/python/${PY_VER}/python-${PY_VER}-macos11.pkg"
PY_PKG_LOCAL="$DIR/output/python-${PY_VER}-macos11.pkg"

echo "========================================"
echo " 准备 Python 环境（同事通用 Mac）"
echo "========================================"
echo "推荐：Python 3.12（兼容采集 / 转写 / OCR）"
echo "不要用损坏的 uv 自定义 Python；优先官方安装包或 Homebrew。"
echo ""

if py="$(_pick_system_python)"; then
  ver="$("$py" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo "?")"
  echo "已检测到可用解释器："
  echo "  $py ($ver)"
  if _python_is_too_new_for_ocr "$py"; then
    echo ""
    echo "⚠ 当前是 Python ≥3.13，主功能可用，但图片 OCR 可能装不上。"
    echo "  若需要 OCR，建议再装官方 3.12（可与现有版本共存）。"
  else
    echo ""
    echo "可以直接双击「检测并安装能力.command」继续。"
    exit 0
  fi
else
  echo "未检测到 Python 3.10–3.12 可用解释器。"
  echo "（系统自带 /usr/bin/python3 经常是 3.9，不能用。）"
fi

echo ""
echo "请选择安装方式："
echo "  1) 官方安装包（推荐，适合大多数同事，约 40MB）"
echo "  2) Homebrew：brew install python@3.12（已装 brew 时）"
echo "  3) 仅打开下载页面，我自己装"
echo "  0) 取消"
echo ""

ans="1"
if [[ -t 0 ]]; then
  read -r -p "请输入选项 [1/2/3/0]，默认 1: " ans || true
elif [[ -r /dev/tty ]]; then
  read -r -p "请输入选项 [1/2/3/0]，默认 1: " ans < /dev/tty || true
fi
ans="${ans:-1}"

case "$ans" in
  2)
    if ! command -v brew >/dev/null 2>&1; then
      echo "未检测到 Homebrew。可先安装：https://brew.sh"
      echo "或改选官方安装包（选项 1）。"
      exit 1
    fi
    echo ">>> brew install python@3.12 …"
    brew install python@3.12
    echo ""
    echo "完成。请重新双击「检测并安装能力.command」。"
    ;;
  3)
    open "https://www.python.org/downloads/release/python-31210/" 2>/dev/null || true
    echo "已尝试打开下载页。请安装 macOS 64-bit universal2 installer，"
    echo "安装勾选 “Add Python to PATH” / 默认选项，完成后重新「检测并安装能力」。"
    ;;
  0)
    echo "已取消。"
    exit 0
    ;;
  *)
    mkdir -p "$DIR/output"
    echo ">>> 下载官方 Python ${PY_VER} …"
    echo "    $PY_PKG_URL"
    if command -v curl >/dev/null 2>&1; then
      curl -L --fail --retry 3 -o "$PY_PKG_LOCAL" "$PY_PKG_URL"
    else
      echo "缺少 curl，请改用选项 3 打开网页下载。"
      exit 1
    fi
    echo ">>> 打开安装包（按提示下一步即可）…"
    open "$PY_PKG_LOCAL"
    echo ""
    echo "安装完成后："
    echo "  1. 关闭本窗口"
    echo "  2. 再双击「检测并安装能力.command」"
    echo "  3. 同意安装依赖后，再打开工具"
    ;;
esac
