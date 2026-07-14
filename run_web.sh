#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if ! python3 -c "import fastapi" 2>/dev/null; then
  echo "正在安装依赖..."
  pip3 install -r requirements.txt
fi

if ! python3 -c "from whisper_config import DEFAULT_WHISPER_MODEL; from video_script import _get_whisper_model; _get_whisper_model(DEFAULT_WHISPER_MODEL)" 2>/dev/null; then
  echo "首次使用可运行 ./setup_whisper.sh 预下载语音识别模型"
fi

HOST="${APP_HOST:-127.0.0.1}"
PORT="${APP_PORT:-8765}"
RELOAD="${APP_RELOAD:-1}"
echo "启动 Web 工具: http://${HOST}:${PORT}"
echo "（若端口被旧进程占用，请先关闭旧服务再启动）"
if [[ "$RELOAD" == "1" ]]; then
  exec python3 -m uvicorn web_server:app --host "$HOST" --port "$PORT" --reload
else
  exec python3 -m uvicorn web_server:app --host "$HOST" --port "$PORT"
fi
