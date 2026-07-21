#!/usr/bin/env bash
# 预下载 Whisper small 模型（默认），避免首次口播转写失败
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
# shellcheck source=python_env.sh
source "$DIR/python_env.sh"
resolve_python_bin
if [[ -x "$DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$DIR/.venv/bin/python"
fi

"$PYTHON_BIN" << 'PY'
from whisper_config import DEFAULT_WHISPER_MODEL
from video_script import _get_whisper_model

print(f"正在下载/校验 Whisper {DEFAULT_WHISPER_MODEL} 模型（仅首次需要）…")
_get_whisper_model(DEFAULT_WHISPER_MODEL)
print("模型就绪。")
PY
