#!/usr/bin/env bash
# 能力检测与安装
#   ./ensure_capabilities.sh           # 自动模式（启动工具时调用）：齐全则静默；缺失才询问安装
#   ./ensure_capabilities.sh --manual  # 手动模式：打印清单，再决定是否安装
set -eo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
# shellcheck source=python_env.sh
source "$DIR/python_env.sh"

MODE="auto"
for arg in "$@"; do
  case "$arg" in
    --manual|-m) MODE="manual" ;;
    --auto|-a) MODE="auto" ;;
    -h|--help)
      echo "用法: $0 [--manual|--auto]"
      exit 0
      ;;
  esac
done

resolve_python_bin
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/Library/Caches/ms-playwright}"

MISSING=()
OPTIONAL_MISSING=()
STATUS_LINES=()

check_import() {
  local mod
  mod="$1"
  "$PYTHON_BIN" -c "import $mod" >/dev/null 2>&1
}

# bash 3.2 + set -u 下避免 ${var:+...} / 同行 multi-local 的坑
mark() {
  local name state note suffix
  name="${1:-}"
  state="${2:-}"
  note="${3:-}"
  suffix=""
  if [[ -n "$note" ]]; then
    suffix=" - ${note}"
  fi
  if [[ "$state" == "ok" ]]; then
    STATUS_LINES[${#STATUS_LINES[@]}]="  [OK] ${name}${suffix}"
  elif [[ "$state" == "optional_missing" ]]; then
    STATUS_LINES[${#STATUS_LINES[@]}]="  [--] ${name} (optional)${suffix}"
    OPTIONAL_MISSING[${#OPTIONAL_MISSING[@]}]="$name"
  else
    STATUS_LINES[${#STATUS_LINES[@]}]="  [X] ${name} (missing)${suffix}"
    MISSING[${#MISSING[@]}]="$name"
  fi
}

redbook_ready() {
  local root
  for root in \
    "$DIR/vendor/redbook-skills" \
    "$DIR/.cursor/skills/redbook-skills" \
    "$HOME/.cursor/skills/redbook-skills"
  do
    if [[ -f "$root/scripts/cdp_publish.py" ]]; then
      return 0
    fi
  done
  return 1
}

install_redbook_skills() {
  local dest="$DIR/vendor/redbook-skills"
  local src=""
  mkdir -p "$DIR/vendor"
  if [[ -f "$dest/scripts/cdp_publish.py" ]]; then
    echo "    已内置: vendor/redbook-skills"
    return 0
  fi
  for src in \
    "$HOME/.cursor/skills/redbook-skills" \
    "$DIR/.cursor/skills/redbook-skills"
  do
    if [[ -f "$src/scripts/cdp_publish.py" ]]; then
      echo "    从 $src 复制到 vendor/redbook-skills …"
      rsync -a --exclude '__pycache__' --exclude '.git' --exclude 'tmp' "$src/" "$dest/"
      return 0
    fi
  done
  echo "    ⚠ 未找到 redbook-skills 源文件，小红书采集将不可用。"
  return 1
}

whisper_ready() {
  "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
from pathlib import Path
from whisper_config import DEFAULT_WHISPER_MODEL

def ok(root: Path) -> bool:
    if not root.exists():
        return False
    for p in root.rglob("model.bin"):
        try:
            if p.is_file() and p.stat().st_size > 1_000_000:
                return True
        except OSError:
            continue
    return False

if ok(Path("vendor") / f"faster-whisper-{DEFAULT_WHISPER_MODEL}"):
    raise SystemExit(0)
cache = Path.home() / ".cache/huggingface/hub" / f"models--Systran--faster-whisper-{DEFAULT_WHISPER_MODEL}"
raise SystemExit(0 if ok(cache) else 1)
PY
}

playwright_ready() {
  "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
from pathlib import Path
import os
root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")).expanduser()
if not root.exists():
    raise SystemExit(1)
ok = any(root.rglob("chrome-headless-shell")) or any(root.rglob("Chromium")) or any(root.rglob("chrome"))
raise SystemExit(0 if ok else 1)
PY
}

scan_capabilities() {
  MISSING=()
  OPTIONAL_MISSING=()
  STATUS_LINES=()

  local py_ver
  py_ver="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % (sys.version_info[0], sys.version_info[1]))' 2>/dev/null || echo "?")"
  STATUS_LINES[${#STATUS_LINES[@]}]="  [i] Python: $PYTHON_BIN ($py_ver)"
  if [[ -x "$DIR/.venv/bin/python" ]]; then
    STATUS_LINES[${#STATUS_LINES[@]}]="  [i] Using project .venv"
  else
    STATUS_LINES[${#STATUS_LINES[@]}]="  [i] .venv not created yet (will create on install)"
  fi

  if redbook_ready; then
    mark "小红书采集（redbook-skills）" ok "vendor 或本机已就绪"
  else
    mark "小红书采集（redbook-skills）" missing "随工具内置/安装"
  fi

  if check_import fastapi && check_import uvicorn; then
    mark "核心服务（fastapi/uvicorn）" ok
  else
    mark "核心服务（fastapi/uvicorn）" missing
  fi

  if check_import requests && check_import openpyxl && check_import jieba; then
    mark "通用依赖（requests/openpyxl/jieba）" ok
  else
    mark "通用依赖（requests/openpyxl/jieba）" missing
  fi

  if check_import websockets; then
    mark "CDP 依赖（websockets）" ok
  else
    mark "CDP 依赖（websockets）" missing
  fi

  if check_import faster_whisper; then
    mark "口播转写库（faster-whisper）" ok
  else
    mark "口播转写库（faster-whisper）" missing
  fi

  if whisper_ready; then
    mark "Whisper 语音模型（small）" ok
  else
    mark "Whisper 语音模型（small）" missing "约 500MB，完整包已内置时可免下载"
  fi

  if check_import rapidocr_onnxruntime || check_import rapidocr; then
    mark "图片 OCR（rapidocr）" ok
  else
    if _python_is_too_new_for_ocr "$PYTHON_BIN"; then
      mark "图片 OCR（rapidocr）" optional_missing "当前 Python≥3.13 无适配轮子，建议改用 3.12 重建 .venv"
    else
      mark "图片 OCR（rapidocr）" missing "将装入 .venv"
    fi
  fi

  if check_import playwright && playwright_ready; then
    mark "视频号 Playwright Chromium" ok
  else
    mark "视频号 Playwright Chromium" optional_missing "仅关键词发现需要"
  fi
}

print_report() {
  echo "========================================"
  echo " Capability check"
  echo " Mode: $MODE"
  echo "========================================"
  local i
  i=0
  while [[ $i -lt ${#STATUS_LINES[@]} ]]; do
    echo "${STATUS_LINES[$i]}"
    i=$((i + 1))
  done
  echo "----------------------------------------"
  if [[ ${#MISSING[@]} -eq 0 ]]; then
    echo "Core capabilities: ready"
  else
    echo "Core missing: ${#MISSING[@]} item(s)"
  fi
  if [[ ${#OPTIONAL_MISSING[@]} -gt 0 ]]; then
    echo "Optional/limited: ${#OPTIONAL_MISSING[@]} item(s)"
  fi
  echo "Note: packages install into project .venv (not system/uv Python)."
  echo "      Fill TokenHub API Key in the web UI when needed."
  echo "========================================"
}

do_install() {
  echo ""
  ensure_project_venv || {
    echo "无法创建虚拟环境，安装中止。"
    return 1
  }
  export PYTHON_BIN
  echo "    安装目标: $PYTHON_BIN"

  echo ""
  echo ">>> 安装核心 Python 依赖到 .venv…"
  if ! "$PYTHON_BIN" -m pip install -r requirements.txt; then
    echo "    完整 requirements 失败，尝试精简核心包…"
    "$PYTHON_BIN" -m pip install "fastapi>=0.110" "uvicorn[standard]>=0.27" requests pydantic \
      "faster-whisper>=1.0" openpyxl Pillow zhconv jieba websockets || {
      echo "    ❌ 核心依赖安装失败。请检查网络，或改用 Python 3.12：brew install python@3.12"
      return 1
    }
  fi

  if [[ -f "$DIR/vendor/redbook-skills/requirements.txt" ]]; then
    "$PYTHON_BIN" -m pip install -r "$DIR/vendor/redbook-skills/requirements.txt" -q || true
  fi

  echo ""
  echo ">>> 安装图片 OCR（可选，需 Python 3.10–3.12）…"
  if _python_is_too_new_for_ocr "$PYTHON_BIN"; then
    echo "    跳过：当前为 Python ≥3.13，rapidocr-onnxruntime 无可用轮子。"
    echo "    解决：安装 python@3.12 后执行 rm -rf .venv && ./ensure_capabilities.sh --manual"
  elif [[ -f "$DIR/requirements-ocr.txt" ]]; then
    if "$PYTHON_BIN" -m pip install -r "$DIR/requirements-ocr.txt"; then
      echo "    OCR 已安装。"
    else
      echo "    ⚠ OCR 安装失败，图片 OCR 暂不可用；其它功能不受影响。"
    fi
  fi

  echo ""
  echo ">>> 安装小红书采集能力（redbook-skills）…"
  install_redbook_skills || true

  if ! whisper_ready; then
    echo ""
    echo ">>> 准备 Whisper 模型…"
    if [[ -d "$DIR/vendor/faster-whisper-small" ]] && find "$DIR/vendor/faster-whisper-small" -name model.bin 2>/dev/null | grep -q .; then
      echo "    已使用压缩包内置模型：vendor/faster-whisper-small"
    else
      echo "    从镜像下载（HF_ENDPOINT=$HF_ENDPOINT）…"
      PYTHON_BIN="$PYTHON_BIN" bash "$DIR/setup_whisper.sh" || echo "    ⚠ Whisper 下载失败，可稍后重试: ./setup_whisper.sh"
    fi
  fi

  if [[ ${#OPTIONAL_MISSING[@]} -gt 0 ]]; then
    # 仅当缺失项包含 Playwright 时询问
    local need_pw=0
    local i=0
    while [[ $i -lt ${#OPTIONAL_MISSING[@]} ]]; do
      if [[ "${OPTIONAL_MISSING[$i]}" == *"Playwright"* ]]; then
        need_pw=1
      fi
      i=$((i + 1))
    done
    if [[ "$need_pw" -eq 1 ]]; then
      echo ""
      if [[ -t 0 ]]; then
        read -r -p "是否安装 Playwright Chromium（视频号发现）？[y/N] " pans
        if [[ "$pans" =~ ^[Yy]$ ]]; then
          PYTHON_BIN="$PYTHON_BIN" bash "$DIR/setup_playwright.sh" || echo "    ⚠ Playwright 安装失败，可稍后: ./setup_playwright.sh"
        else
          echo "    已跳过 Playwright。"
        fi
      else
        echo "    非交互环境，已跳过 Playwright。需要时运行: ./setup_playwright.sh"
      fi
    fi
  fi

  mkdir -p "$DIR/output"
  date +%s >"$DIR/output/.capabilities_installed_at"
  echo ""
  echo "安装流程结束。可双击「打开小红书提取工具.command」启动。"
  echo "（依赖位于 .venv，与系统/uv Python 隔离。）"
}

prompt_yes_default() {
  # macOS .command / 管道场景下 stdin 可能不是 tty；不要因 /dev/tty 失败而中断
  local msg="$1" ans=""
  if [[ -t 0 ]]; then
    read -r -p "$msg" ans || true
  else
    # 尝试控制终端；失败则默认同意（安装场景更友好）
    ans="$( { read -r -p "$msg" x < /dev/tty && echo "$x"; } 2>/dev/null || true )"
    if [[ -z "$ans" ]]; then
      echo "$msg Y（无法交互，默认同意并继续安装）"
      ans="Y"
    fi
  fi
  ans="${ans:-Y}"
  [[ "$ans" =~ ^[Yy]$ ]]
}

# ---------- main ----------
scan_capabilities

if [[ "$MODE" == "manual" ]]; then
  print_report
  echo ""
  if [[ ${#MISSING[@]} -eq 0 && ${#OPTIONAL_MISSING[@]} -eq 0 ]]; then
    echo "全部能力已安装，无需操作。"
    exit 0
  fi
  if [[ ${#MISSING[@]} -eq 0 ]]; then
    echo "核心已齐。若要补装可选能力，可继续。"
  fi
  if prompt_yes_default "是否现在安装/补齐？[Y/n] "; then
    do_install
    resolve_python_bin
    scan_capabilities
    echo ""
    print_report
    exit 0
  fi
  echo "已取消。"
  exit 0
fi

# auto 模式：核心齐全则完全静默
if [[ ${#MISSING[@]} -eq 0 ]]; then
  exit 0
fi

echo ">>> 检测到核心能力缺失（共 ${#MISSING[@]} 项）。"
echo "    建议先双击「检测并安装能力.command」查看清单；或在此直接安装。"
echo "    安装将写入项目 .venv，可规避「externally-managed-environment / uv」报错。"
echo ""
i=0
while [[ $i -lt ${#MISSING[@]} ]]; do
  echo "  • ${MISSING[$i]}"
  i=$((i + 1))
done
echo ""

if prompt_yes_default "是否现在安装缺失能力？[Y/n] "; then
  do_install
  exit 0
fi
echo "已跳过。部分功能可能不可用，仍可尝试启动主界面。"
exit 0
