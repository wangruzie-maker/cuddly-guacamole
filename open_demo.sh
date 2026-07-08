#!/usr/bin/env bash
# 体验版：预装演示数据 + 启动服务（适合汇报展示，无需 Whisper/CDP）
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

export DEMO_MODE=1
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/Library/Caches/ms-playwright}"

PORT=8765
BASE_URL="http://127.0.0.1:${PORT}"
URL="${BASE_URL}?v=1.7.0&demo=1"
PID_FILE="$DIR/output/server.pid"
LOG_FILE="$DIR/output/server.log"

mkdir -p "$DIR/output"

echo "======================================"
echo "  社媒内容提取 · 体验版"
echo "  演示数据已内置，可直接浏览效果"
echo "======================================"
echo ""

if ! python3 -c "import fastapi" 2>/dev/null; then
  echo "首次运行：安装依赖（约 1 分钟）..."
  pip3 install -r requirements.txt -q
fi

bash "$DIR/demo/load_sample_data.sh"

# 启动服务（体验版不强制杀旧进程以外的逻辑，复用 open_app 思路）
pids="$(lsof -ti :"$PORT" 2>/dev/null || true)"
if [[ -n "$pids" ]]; then
  kill $pids 2>/dev/null || true
  sleep 1
fi

echo "正在启动体验版服务..."
nohup env DEMO_MODE=1 PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
  python3 -m uvicorn web_server:app --host 127.0.0.1 --port "$PORT" >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"

ready=0
for _ in $(seq 1 40); do
  if curl -sf "${BASE_URL}/api/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.25
done

if [[ "$ready" -ne 1 ]]; then
  echo "启动失败，请查看: $LOG_FILE"
  tail -20 "$LOG_FILE" 2>/dev/null || true
  exit 1
fi

echo "体验版已就绪: $URL"
if [[ "$(uname -s)" == "Darwin" ]]; then
  open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL"
else
  echo "请手动打开: $URL"
fi

echo ""
echo "汇报提示："
echo "  · 左侧可切换「小红书 / 视频号」查看已提取样例"
echo "  · 右侧可见口播脚本、点赞等字段"
echo "  · 粘贴真实链接也可试用（需网络；转写需另运行 ./install.sh）"
echo ""
echo "停止服务: kill \$(cat \"$PID_FILE\")"
