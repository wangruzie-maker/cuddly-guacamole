#!/usr/bin/env bash
# 统一解析本项目可用的 Python：优先创建/复用项目内 .venv，避开 uv/Homebrew 的 externally-managed-environment。
# 用法: source ./python_env.sh

# shellcheck disable=SC2034
: "${DIR:=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

_venv_python() {
  if [[ -x "$DIR/.venv/bin/python" ]]; then
    echo "$DIR/.venv/bin/python"
    return 0
  fi
  if [[ -x "$DIR/.venv/Scripts/python.exe" ]]; then
    echo "$DIR/.venv/Scripts/python.exe"
    return 0
  fi
  return 1
}

# 优先 3.12/3.11/3.10（OCR / onnxruntime 兼容面最好），再才是更新版本。
_pick_system_python() {
  local cand ver major minor
  for cand in python3.12 python3.11 python3.10 python3.13 python3.14 python3; do
    if ! command -v "$cand" >/dev/null 2>&1; then
      continue
    fi
    if ! "$cand" - <<'PY' >/dev/null 2>&1
from dataclasses import dataclass
@dataclass(slots=True)
class _T:
    x: int = 0
PY
    then
      continue
    fi
    ver="$("$cand" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || true)"
    major="${ver%%.*}"
    minor="${ver#*.}"
    # 需要 ≥3.10
    if [[ "$major" -gt 3 ]] || { [[ "$major" -eq 3 ]] && [[ "$minor" -ge 10 ]]; }; then
      command -v "$cand"
      return 0
    fi
  done
  command -v python3
}

_python_is_too_new_for_ocr() {
  local py="$1" ver minor
  ver="$("$py" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")"
  minor="${ver#3.}"
  if [[ "$ver" == 3.* ]] && [[ "$minor" =~ ^[0-9]+$ ]] && [[ "$minor" -ge 13 ]]; then
    return 0
  fi
  return 1
}

ensure_project_venv() {
  local sys_py venv_py
  if venv_py="$(_venv_python)"; then
    PYTHON_BIN="$venv_py"
    return 0
  fi

  sys_py="$(_pick_system_python)"
  echo ">>> 创建项目虚拟环境 .venv（避免系统/uv 托管 Python 无法 pip install）"
  echo "    基础解释器: $sys_py ($("$sys_py" -c 'import sys; print(sys.version.split()[0])'))"

  if _python_is_too_new_for_ocr "$sys_py"; then
    echo "    ⚠ 当前 Python ≥3.13，图片 OCR（rapidocr-onnxruntime）可能无适配轮子。"
    echo "      建议安装 Python 3.12 后删除 .venv 再重新「检测并安装能力」。"
    echo "      macOS: brew install python@3.12"
  fi

  if ! "$sys_py" -m venv "$DIR/.venv"; then
    echo "    ❌ 创建虚拟环境失败。请确认已安装 Python 3.10–3.12。"
    return 1
  fi

  venv_py="$(_venv_python)" || {
    echo "    ❌ 虚拟环境已创建但找不到 python 可执行文件。"
    return 1
  }
  # 先升级 pip，减少旧 pip 装包失败
  "$venv_py" -m pip install -U pip setuptools wheel -q || true
  PYTHON_BIN="$venv_py"
  echo "    已就绪: $PYTHON_BIN"
  return 0
}

resolve_python_bin() {
  # 若调用方已指定且可用，尊重之；否则优先 .venv
  if [[ -n "${PYTHON_BIN:-}" && -x "${PYTHON_BIN}" ]]; then
    return 0
  fi
  if PYTHON_BIN="$(_venv_python)"; then
    export PYTHON_BIN
    return 0
  fi
  PYTHON_BIN="$(_pick_system_python)"
  export PYTHON_BIN
}

# 被 source 时自动解析；被直接执行时打印路径
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  DIR="$(cd "$(dirname "$0")" && pwd)"
  resolve_python_bin
  echo "$PYTHON_BIN"
fi
