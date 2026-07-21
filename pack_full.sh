#!/usr/bin/env bash
# 打包「发给同事」的完整能力压缩包：代码 + 内置 Whisper small + 说明
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
NAME="社媒选题与创作工具-完整版-v${VERSION}"
STAGE="$DIR/dist/${NAME}"
OUT_ZIP="$DIR/dist/${NAME}.zip"
WHISPER_SRC="${WHISPER_SRC:-$HOME/.cache/huggingface/hub/models--Systran--faster-whisper-small}"

echo ">>> 打包 $NAME"

rm -rf "$STAGE"
mkdir -p "$STAGE"

# 复制项目（排除体积大/隐私/缓存；Whisper 大模型单独拷入）
rsync -a \
  --exclude '.git/' \
  --exclude 'output/' \
  --exclude 'dist/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.env' \
  --exclude '.DS_Store' \
  --exclude 'vendor/faster-whisper-*/' \
  --exclude 'node_modules/' \
  "$DIR/" "$STAGE/"

# 确保内置 redbook-skills（小红书采集）
if [[ ! -f "$STAGE/vendor/redbook-skills/scripts/cdp_publish.py" ]]; then
  mkdir -p "$STAGE/vendor"
  if [[ -f "$DIR/vendor/redbook-skills/scripts/cdp_publish.py" ]]; then
    rsync -a --exclude '__pycache__' --exclude '.git' "$DIR/vendor/redbook-skills/" "$STAGE/vendor/redbook-skills/"
  elif [[ -f "$HOME/.cursor/skills/redbook-skills/scripts/cdp_publish.py" ]]; then
    rsync -a --exclude '__pycache__' --exclude '.git' --exclude 'tmp' \
      "$HOME/.cursor/skills/redbook-skills/" "$STAGE/vendor/redbook-skills/"
  else
    echo "    ⚠ 未找到 redbook-skills，压缩包内将缺少小红书采集能力"
  fi
fi
if [[ -f "$STAGE/vendor/redbook-skills/scripts/cdp_publish.py" ]]; then
  echo "    已内置 redbook-skills: $(du -sh "$STAGE/vendor/redbook-skills" | awk '{print $1}')"
fi

# 内置 Whisper small（优先用本机已下载缓存）
mkdir -p "$STAGE/vendor/faster-whisper-small"
if [[ -d "$WHISPER_SRC" ]]; then
  MODEL_BIN="$(find "$WHISPER_SRC" -name model.bin 2>/dev/null | head -1 || true)"
  if [[ -n "$MODEL_BIN" ]]; then
    MODEL_DIR="$(dirname "$MODEL_BIN")"
    echo "    写入内置 Whisper: $MODEL_DIR"
    # HF 缓存多为指向 blobs 的符号链接，必须解引用复制实体文件
    rsync -aL "$MODEL_DIR/" "$STAGE/vendor/faster-whisper-small/"
  else
    echo "    ⚠ 未找到 model.bin，压缩包将不含内置模型（同事需联网下载）"
  fi
else
  echo "    ⚠ 本机无 Whisper 缓存，压缩包将不含内置模型"
  echo "      可先运行: ./setup_whisper.sh"
fi

VENDOR_SIZE="$(du -sh "$STAGE/vendor/faster-whisper-small" 2>/dev/null | awk '{print $1}')"
echo "    vendor/faster-whisper-small 大小: ${VENDOR_SIZE:-0}"
if [[ ! -f "$STAGE/vendor/faster-whisper-small/model.bin" ]]; then
  echo "    ⚠ 内置模型不完整（缺少 model.bin），同事首次仍需联网下载"
fi

# 入口权限
chmod +x "$STAGE/"*.command "$STAGE/"*.sh "$STAGE/demo/"*.sh 2>/dev/null || true
# 去掉重复入口（若仍存在）
rm -f "$STAGE/正式版.command"

# 确保有 .env 模板
[[ -f "$STAGE/.env.example" ]] || true

rm -f "$OUT_ZIP"
(
  cd "$DIR/dist"
  zip -r -q "$OUT_ZIP" "$NAME"
)

echo ""
echo "已生成: $OUT_ZIP"
du -h "$OUT_ZIP"
echo ""
echo "发给同事：解压 → 双击「打开小红书提取工具.command」→ 按提示同意安装缺失能力"
echo "API（TokenHub）请同事在网页自行填写；采集/转写/OCR 不强制 API。"
