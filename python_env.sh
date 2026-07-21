#!/usr/bin/env bash
# 统一解析本项目可用的 Python：优先创建/复用项目内 .venv，避开 uv/系统托管限制。
# 用法: source ./python_env.sh
#
# 注意：部分 uv 安装的 python3.11 用 `python -m venv` 会生成前缀为 /install 的坏环境
# （No module named 'encodings'）。选解释器时必须做可用性校验，坏 .venv 要删掉重建。

# shellcheck disable=SC2034
: "${DIR:=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

_python_is_usable() {
  local py="$1"
  [[ -n "$py" && -x "$py" ]] || return 1
  # 必须能 import encodings，且 base_prefix 真实存在（拒绝坏掉的 /install 前缀）
  "$py" - <<'PY' >/dev/null 2>&1
import sys
from pathlib import Path
import encodings  # noqa: F401
from dataclasses import dataclass

@dataclass(slots=True)
class _T:
    x: int = 0

prefix = Path(sys.base_prefix or sys.prefix or "")
# uv/standalone 损坏常见：base_prefix 停在构建期路径 /install
if str(prefix) in ("", ".", "/install") or not prefix.exists():
    raise SystemExit(1)
enc = prefix / "lib"
# Framework / Homebrew / uv 正常布局至少能看到 lib 或 Python.framework
if not enc.exists() and not (prefix / "Python").exists():
    # 再兜底：能定位 encodings.__file__
    import encodings as _e
    if not getattr(_e, "__file__", None):
        raise SystemExit(1)
raise SystemExit(0)
PY
}

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

_venv_is_usable() {
  local py
  py="$(_venv_python)" || return 1
  _python_is_usable "$py"
}

_candidate_pythons() {
  # 显式路径优先（避开 ~/.local 里 uv 软链抢 PATH，防止生成 /install 坏 venv）
  local paths=(
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
    /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11
    /Library/Frameworks/Python.framework/Versions/3.10/bin/python3.10
    /opt/homebrew/opt/python@3.12/bin/python3.12
    /opt/homebrew/opt/python@3.11/bin/python3.11
    /opt/homebrew/opt/python@3.10/bin/python3.10
    /usr/local/opt/python@3.12/bin/python3.12
    /usr/local/opt/python@3.11/bin/python3.11
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13
    /Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14
    /usr/local/bin/python3.12
    /usr/local/bin/python3.11
    /usr/local/bin/python3.10
    /usr/local/bin/python3.14
    /usr/local/bin/python3
  )
  local p c resolved
  for p in "${paths[@]}"; do
    if [[ -x "$p" ]]; then
      echo "$p"
    fi
  done
  # PATH 里的解释器放后面；uv (~/.local) 更容易做出损坏 venv，再往后排
  local normal_list="" uv_list=""
  for c in python3.12 python3.11 python3.10 python3.13 python3.14 python3; do
    if command -v "$c" >/dev/null 2>&1; then
      resolved="$(command -v "$c")"
      case "$resolved" in
        */.local/*|*uv/python*) uv_list="$uv_list$resolved
" ;;
        *) normal_list="$normal_list$resolved
" ;;
      esac
    fi
  done
  printf "%s" "$normal_list"
  printf "%s" "$uv_list"
}

_pick_system_python() {
  local cand ver major minor seen=""
  # bash 3.2 无进程替换，改用换行列表
  local list
  list="$(_candidate_pythons | awk '!a[$0]++')"
  while IFS= read -r cand; do
    [[ -n "$cand" ]] || continue
    _python_is_usable "$cand" || continue
    ver="$("$cand" -c 'import sys; print("%d.%d" % (sys.version_info[0], sys.version_info[1]))' 2>/dev/null || echo "0.0")"
    major="${ver%%.*}"
    minor="${ver#*.}"
    major="${major:-0}"
    minor="${minor:-0}"
    if [[ "$major" -gt 3 ]] || { [[ "$major" -eq 3 ]] && [[ "$minor" -ge 10 ]]; }; then
      echo "$cand"
      return 0
    fi
  done <<EOF
$list
EOF
  return 1
}

_python_is_too_new_for_ocr() {
  local py="$1" ver minor
  ver="$("$py" -c 'import sys; print("%d.%d" % (sys.version_info[0], sys.version_info[1]))' 2>/dev/null || echo "0.0")"
  minor="${ver#3.}"
  if [[ "$ver" == 3.* ]] && [[ "$minor" =~ ^[0-9]+$ ]] && [[ "$minor" -ge 13 ]]; then
    return 0
  fi
  return 1
}

_create_venv_with() {
  local sys_py="$1"
  rm -rf "$DIR/.venv"
  if ! "$sys_py" -m venv "$DIR/.venv"; then
    return 1
  fi
  if ! _venv_is_usable; then
    echo "    ⚠ 用 $sys_py 生成的 .venv 不可用（常见于损坏的 uv Python），已丢弃。"
    rm -rf "$DIR/.venv"
    return 1
  fi
  return 0
}

ensure_project_venv() {
  local sys_py venv_py cand tried="" list ver

  # 已有坏掉的 .venv（/install / encodings 缺失）→ 删掉重建
  if _venv_python >/dev/null 2>&1; then
    if _venv_is_usable; then
      PYTHON_BIN="$(_venv_python)"
      return 0
    fi
    echo ">>> 检测到损坏的 .venv（无法 import encodings），将删除并重建…"
    rm -rf "$DIR/.venv"
  fi

  echo ">>> 创建项目虚拟环境 .venv（避免系统/uv 托管 Python 无法 pip install）"

  list="$(_candidate_pythons | awk '!a[$0]++')"
  while IFS= read -r cand; do
    [[ -n "$cand" ]] || continue
    case " $tried " in
      *" $cand "*) continue ;;
    esac
    tried="$tried $cand"
    _python_is_usable "$cand" || continue
    ver="$("$cand" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo "?")"
    echo "    尝试基础解释器: $cand ($ver)"
    if _python_is_too_new_for_ocr "$cand"; then
      echo "    ⚠ Python ≥3.13：OCR 可能无轮子，但可先装核心功能。"
    fi
    if _create_venv_with "$cand"; then
      venv_py="$(_venv_python)"
      "$venv_py" -m pip install -U pip setuptools wheel -q 2>/dev/null || true
      PYTHON_BIN="$venv_py"
      echo "    已就绪: $PYTHON_BIN"
      return 0
    fi
  done <<EOF
$list
EOF

  echo "    ❌ 无法创建可用的虚拟环境。"
  echo ""
  if [[ -f "$DIR/bootstrap_python.sh" ]]; then
    echo "    将启动「准备 Python 环境」引导（适合同事通用 Mac）…"
    if [[ -t 0 ]] || [[ -r /dev/tty ]]; then
      /bin/bash "$DIR/bootstrap_python.sh" || true
    else
      echo "    请双击：准备Python环境.command"
      echo "    或安装官方 Python 3.12：https://www.python.org/downloads/"
    fi
  else
    echo "      请安装官方 Python 3.12 后重试："
    echo "        https://www.python.org/downloads/"
    echo "      或: brew install python@3.12"
  fi
  echo "      然后: rm -rf .venv && ./ensure_capabilities.sh --manual"
  return 1
}

resolve_python_bin() {
  if [[ -n "${PYTHON_BIN:-}" && -x "${PYTHON_BIN}" ]] && _python_is_usable "${PYTHON_BIN}"; then
    return 0
  fi
  if _venv_is_usable; then
    PYTHON_BIN="$(_venv_python)"
    export PYTHON_BIN
    return 0
  fi
  # 坏 venv 清掉，避免后续继续用
  if _venv_python >/dev/null 2>&1; then
    rm -rf "$DIR/.venv"
  fi
  if PYTHON_BIN="$(_pick_system_python)"; then
    export PYTHON_BIN
    return 0
  fi
  PYTHON_BIN="$(command -v python3 || true)"
  export PYTHON_BIN
}

# 被 source 时不自动执行；被直接执行时打印路径
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  DIR="$(cd "$(dirname "$0")" && pwd)"
  resolve_python_bin
  echo "${PYTHON_BIN:-}"
fi
