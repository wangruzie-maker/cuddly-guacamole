#!/usr/bin/env bash
# 一键启动服务并在浏览器中打开小红书提取工具
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PORT=8765
EXPECTED_VERSION="1.22.0"
BASE_URL="http://127.0.0.1:${PORT}"
URL="${BASE_URL}?v=${EXPECTED_VERSION}"
PID_FILE="$DIR/output/server.pid"
LOG_FILE="$DIR/output/server.log"

mkdir -p "$DIR/output"

export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/Library/Caches/ms-playwright}"

server_mode() {
  curl -sf "${BASE_URL}/api/health" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('mode',''))" 2>/dev/null || true
}

health_ok() {
  curl -sf "${BASE_URL}/api/health" >/dev/null 2>&1
}

server_version() {
  curl -sf "${BASE_URL}/api/health" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('version',''))" 2>/dev/null || true
}

routes_ok() {
  curl -sf "${BASE_URL}/api/health" >/dev/null 2>&1
}

ensure_deps() {
  if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "正在安装依赖..."
    pip3 install -r requirements.txt
  fi
  if ! python3 -c "import playwright" 2>/dev/null; then
    pip3 install playwright -q
  fi
  if [[ ! -f "${PLAYWRIGHT_BROWSERS_PATH}/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell" ]]; then
    echo "首次视频号发现需下载 Chromium: ./setup_playwright.sh"
  fi
}

kill_port() {
  local pids
  pids="$(lsof -ti :"$PORT" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "停止端口 ${PORT} 上的旧服务..."
    kill $pids 2>/dev/null || true
    sleep 1
    pids="$(lsof -ti :"$PORT" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      kill -9 $pids 2>/dev/null || true
      sleep 0.5
    fi
  fi
  rm -f "$PID_FILE"
}

start_server() {
  ensure_deps
  kill_port
  rm -f "$DIR/output/.demo_mode"
  echo "正在启动正式版服务 (v${EXPECTED_VERSION})..."
  nohup env PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
    python3 -m uvicorn web_server:app --host 127.0.0.1 --port "$PORT" >>"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
}

needs_restart() {
  if ! health_ok; then
    return 0
  fi
  if [[ "$(server_mode)" == "demo" ]]; then
    echo "检测到体验版服务，正在切换为正式版…"
    return 0
  fi
  local ver
  ver="$(server_version)"
  if [[ "$ver" != "$EXPECTED_VERSION" ]]; then
    echo "检测到旧版本服务 (v${ver:-未知})，需要更新到 v${EXPECTED_VERSION}"
    return 0
  fi
  if ! routes_ok; then
    echo "检测到服务缺少历史/OCR 接口，需要重启"
    return 0
  fi
  return 1
}

open_browser() {
  if [[ "$(uname -s)" == "Darwin" ]]; then
    open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL"
  else
    echo "请手动在浏览器打开: $URL"
    return 1
  fi
}

# 每次打开都重启服务，确保加载最新代码
start_server
ready=0
for _ in $(seq 1 40); do
  if health_ok && routes_ok; then
    ready=1
    break
  fi
  sleep 0.25
done
if [[ "$ready" -ne 1 ]]; then
  echo "启动失败，请查看日志: $LOG_FILE"
  tail -30 "$LOG_FILE" 2>/dev/null || true
  exit 1
fi
echo "服务已启动: ${BASE_URL} (v${EXPECTED_VERSION})"

if open_browser; then
  echo "已在浏览器中打开。"
else
  echo "浏览器未能自动打开，请复制地址: $URL"
fi

echo ""
echo "停止服务: kill \$(cat \"$PID_FILE\")"
