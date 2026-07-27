#!/usr/bin/env bash
# 打包「解压即用」离线完整包：内置 Python + wheels + Whisper + redbook-skills
# 同事机无需联网下载依赖/模型；API Key 仍需自行填写。
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

VERSION="$(python3 - <<'PY'
import re
from pathlib import Path
text = Path("web_server.py").read_text(encoding="utf-8")
m = re.search(r'version="([0-9.]+)"', text)
print(m.group(1) if m else "0.0.0")
PY
)"
NAME="社媒选题与创作工具-离线即用版-v${VERSION}"
STAGE="$DIR/dist/${NAME}"
OUT_ZIP="$DIR/dist/${NAME}.zip"
CACHE="$DIR/dist/.offline_cache"
WHISPER_SRC="${WHISPER_SRC:-$HOME/.cache/huggingface/hub/models--Systran--faster-whisper-small}"
PBS_TAG="${PBS_TAG:-20260718}"
PY_VER="3.12.13"

mkdir -p "$CACHE" "$DIR/dist"
echo ">>> 打包 $NAME"

rm -rf "$STAGE"
mkdir -p "$STAGE"

rsync -a \
  --exclude '.git/' \
  --exclude 'output/' \
  --exclude 'dist/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.env' \
  --exclude '.DS_Store' \
  --exclude 'vendor/faster-whisper-*/' \
  --exclude 'vendor/python/' \
  --exclude 'vendor/wheels/' \
  --exclude 'vendor/ms-playwright/' \
  --exclude 'node_modules/' \
  "$DIR/" "$STAGE/"

# --- redbook-skills ---
mkdir -p "$STAGE/vendor"
if [[ -f "$DIR/vendor/redbook-skills/scripts/cdp_publish.py" ]]; then
  rsync -a --exclude '__pycache__' --exclude '.git' --exclude 'tmp' \
    "$DIR/vendor/redbook-skills/" "$STAGE/vendor/redbook-skills/"
elif [[ -f "$HOME/.cursor/skills/redbook-skills/scripts/cdp_publish.py" ]]; then
  rsync -a --exclude '__pycache__' --exclude '.git' --exclude 'tmp' \
    "$HOME/.cursor/skills/redbook-skills/" "$STAGE/vendor/redbook-skills/"
fi

# --- Whisper model ---
mkdir -p "$STAGE/vendor/faster-whisper-small"
if [[ -d "$WHISPER_SRC" ]]; then
  MODEL_BIN="$(find "$WHISPER_SRC" -name model.bin 2>/dev/null | head -1 || true)"
  if [[ -n "$MODEL_BIN" ]]; then
    MODEL_DIR="$(dirname "$MODEL_BIN")"
    echo "    Whisper: $MODEL_DIR"
    rsync -aL "$MODEL_DIR/" "$STAGE/vendor/faster-whisper-small/"
  fi
fi
if [[ ! -f "$STAGE/vendor/faster-whisper-small/model.bin" ]]; then
  echo "❌ 缺少 Whisper model.bin，请先本机跑一次转写或 ./setup_whisper.sh"
  exit 1
fi
echo "    Whisper 大小: $(du -sh "$STAGE/vendor/faster-whisper-small" | awk '{print $1}')"

# --- portable Python (arm64 + x86_64) ---
download_python() {
  local arch="$1"  # aarch64 | x86_64
  local dest_name="$2"  # arm64 | x86_64
  local fname="cpython-${PY_VER}+${PBS_TAG}-${arch}-apple-darwin-install_only.tar.gz"
  local url="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${fname}"
  local tarball="$CACHE/$fname"
  local dest="$STAGE/vendor/python/$dest_name"
  mkdir -p "$STAGE/vendor/python"
  if [[ ! -f "$tarball" ]]; then
    echo "    下载便携 Python ($dest_name)…"
    curl -fL --retry 3 -o "$tarball" "$url"
  else
    echo "    使用缓存 Python: $fname"
  fi
  rm -rf "$dest"
  mkdir -p "$dest"
  tar -xzf "$tarball" -C "$dest" --strip-components=1
  # install_only 布局: python/bin/python3
  if [[ ! -x "$dest/bin/python3" ]]; then
    echo "❌ Python 解压失败: $dest"
    exit 1
  fi
  echo "    Python $dest_name: $("$dest/bin/python3" -V)"
}

download_python aarch64 arm64
download_python x86_64 x86_64

# --- download wheels for both mac arches (offline install) ---
mkdir -p "$STAGE/vendor/wheels"
HOST_PY=""
for c in \
  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 \
  "$STAGE/vendor/python/arm64/bin/python3" \
  "$STAGE/vendor/python/x86_64/bin/python3"
do
  if [[ -x "$c" ]]; then HOST_PY="$c"; break; fi
done
if [[ -z "$HOST_PY" ]]; then
  echo "❌ 找不到可用于下载 wheels 的 Python"
  exit 1
fi

echo "    用 $HOST_PY 下载离线 wheels…"
"$HOST_PY" -m pip install -U pip wheel -q
# 当前机架构完整下载；另一架构尽量补（失败不阻断）
download_wheels_for() {
  local platform="$1"
  echo "    pip download platform=$platform"
  "$HOST_PY" -m pip download \
    -r "$STAGE/requirements.txt" \
    -r "$STAGE/requirements-ocr.txt" \
    -d "$STAGE/vendor/wheels" \
    --python-version 312 \
    --only-binary=:all: \
    --platform "$platform" \
    --implementation cp \
    --abi cp312 \
    || "$HOST_PY" -m pip download \
      -r "$STAGE/requirements.txt" \
      -r "$STAGE/requirements-ocr.txt" \
      -d "$STAGE/vendor/wheels" \
      --python-version 312 \
      --platform "$platform" \
      || true
  if [[ -f "$STAGE/vendor/redbook-skills/requirements.txt" ]]; then
    "$HOST_PY" -m pip download \
      -r "$STAGE/vendor/redbook-skills/requirements.txt" \
      -d "$STAGE/vendor/wheels" \
      --python-version 312 \
      --only-binary=:all: \
      --platform "$platform" \
      --implementation cp \
      --abi cp312 \
      || true
  fi
}

# 本机架构用真实 pip download（含纯源码包）；跨架构仅 only-binary
HOST_ARCH="$(uname -m)"
if [[ "$HOST_ARCH" == "arm64" ]]; then
  "$HOST_PY" -m pip download \
    -r "$STAGE/requirements.txt" \
    -r "$STAGE/requirements-ocr.txt" \
    -d "$STAGE/vendor/wheels"
  if [[ -f "$STAGE/vendor/redbook-skills/requirements.txt" ]]; then
    "$HOST_PY" -m pip download -r "$STAGE/vendor/redbook-skills/requirements.txt" -d "$STAGE/vendor/wheels" || true
  fi
  download_wheels_for macosx_11_0_x86_64
else
  "$HOST_PY" -m pip download \
    -r "$STAGE/requirements.txt" \
    -r "$STAGE/requirements-ocr.txt" \
    -d "$STAGE/vendor/wheels"
  if [[ -f "$STAGE/vendor/redbook-skills/requirements.txt" ]]; then
    "$HOST_PY" -m pip download -r "$STAGE/vendor/redbook-skills/requirements.txt" -d "$STAGE/vendor/wheels" || true
  fi
  download_wheels_for macosx_11_0_arm64
fi
echo "    wheels: $(du -sh "$STAGE/vendor/wheels" | awk '{print $1}') ($(ls -1 "$STAGE/vendor/wheels" | wc -l | tr -d ' ') files)"

# --- 预装当前架构依赖到便携 Python（解压即可用） ---
preinstall_into() {
  local pyroot="$1"
  local py="$pyroot/bin/python3"
  echo "    预装依赖 → $pyroot"
  "$py" -m ensurepip --upgrade >/dev/null 2>&1 || true
  "$py" -m pip install -U pip setuptools wheel -q \
    --no-warn-script-location
  "$py" -m pip install -r "$STAGE/requirements.txt" -r "$STAGE/requirements-ocr.txt" \
    --no-index --find-links "$STAGE/vendor/wheels" \
    --no-warn-script-location
  if [[ -f "$STAGE/vendor/redbook-skills/requirements.txt" ]]; then
    "$py" -m pip install -r "$STAGE/vendor/redbook-skills/requirements.txt" \
      --no-index --find-links "$STAGE/vendor/wheels" \
      --no-warn-script-location || true
  fi
  "$py" -c "import fastapi,uvicorn,faster_whisper,websockets; print('    imports OK', fastapi.__version__)"
}

if [[ "$HOST_ARCH" == "arm64" ]]; then
  preinstall_into "$STAGE/vendor/python/arm64"
  # x86_64：若有对应 wheel 则尽量预装，失败则留给首次启动离线安装
  if "$STAGE/vendor/python/x86_64/bin/python3" -m pip install -r "$STAGE/requirements.txt" \
      --no-index --find-links "$STAGE/vendor/wheels" --no-warn-script-location 2>/tmp/x86_pip.err; then
    "$STAGE/vendor/python/x86_64/bin/python3" -m pip install -r "$STAGE/requirements-ocr.txt" \
      --no-index --find-links "$STAGE/vendor/wheels" --no-warn-script-location || true
    echo "    x86_64 预装完成"
  else
    echo "    ⚠ x86_64 预装跳过（首次打开时会用本地 wheels 安装）"
    tail -5 /tmp/x86_pip.err 2>/dev/null || true
  fi
else
  preinstall_into "$STAGE/vendor/python/x86_64"
fi

# --- optional: copy playwright browsers if present ---
PW_SRC="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/Library/Caches/ms-playwright}"
if [[ -d "$PW_SRC" ]] && find "$PW_SRC" -name 'chrome-headless-shell' -o -name 'Chromium' 2>/dev/null | head -1 | grep -q .; then
  echo "    内置 Playwright 浏览器缓存…"
  mkdir -p "$STAGE/vendor/ms-playwright"
  rsync -a "$PW_SRC/" "$STAGE/vendor/ms-playwright/" || true
  echo "    Playwright: $(du -sh "$STAGE/vendor/ms-playwright" | awk '{print $1}')"
fi

# --- markers & docs ---
cat >"$STAGE/vendor/.offline_bundle" <<EOF
offline=1
version=$VERSION
python=$PY_VER
built=$(date +%Y-%m-%dT%H:%M:%S)
arch_host=$HOST_ARCH
EOF

cat >"$STAGE/离线即用说明.txt" <<EOF
社媒选题与创作工具 · 离线即用版 v${VERSION}

1. 解压到任意文件夹（建议不要放「下载」里长期用）
2. 右键「打开小红书提取工具.command」→ 打开（首次可能被 macOS 拦截）
3. 浏览器打开后即可用；AI 功能的 TokenHub Key 找负责人要，在网页里填写

本包已内置：
- 便携 Python 3.12（Apple Silicon + Intel）
- 全部 Python 依赖（离线 wheels + 已预装）
- Whisper 语音模型
- 小红书采集库 redbook-skills

仍需本机自备：
- Google Chrome（小红书登录）
- TokenHub API Key（仅 AI 选题/文案需要）

若双击被拦截：系统设置 → 隐私与安全性 → 仍要打开
登录失败时：Chrome → 完全退出，再点「登录小红书」
EOF

chmod +x "$STAGE/"*.command "$STAGE/"*.sh "$STAGE/demo/"*.sh 2>/dev/null || true
rm -f "$STAGE/正式版.command"
# 尽量去掉隔离属性，减少同事机 Gatekeeper 麻烦
xattr -cr "$STAGE" 2>/dev/null || true

rm -f "$OUT_ZIP"
(
  cd "$DIR/dist"
  # 不用 -q，大包时显示进度太慢；保持安静即可
  ditto -c -k --sequesterRsrc --keepParent "$NAME" "$OUT_ZIP"
)

# 校验
echo ""
echo "已生成: $OUT_ZIP"
du -h "$OUT_ZIP"
unzip -l "$OUT_ZIP" | awk '
  /vendor\/\.offline_bundle/ {o=1}
  /vendor\/faster-whisper-small\/model.bin/ {m=1}
  /vendor\/python\/arm64\/bin\/python3/ {a=1}
  /vendor\/python\/x86_64\/bin\/python3/ {x=1}
  END {
    print "校验: offline_marker=" (o?"OK":"MISSING") \
          " whisper=" (m?"OK":"MISSING") \
          " py_arm64=" (a?"OK":"MISSING") \
          " py_x64=" (x?"OK":"MISSING")
  }'
echo ""
echo "发给同事：解压 → 右键打开「打开小红书提取工具.command」"
echo "API Key 请负责人单独发放，勿打进压缩包。"
