#!/usr/bin/env bash
# 将演示样例数据写入 output/（体验版用）
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
SAMPLE="$DIR/demo/sample_data"
OUT="$DIR/output"

mkdir -p "$OUT/channels"
cp "$SAMPLE/xhs_accumulated.json" "$OUT/accumulated.json"
cp "$SAMPLE/channels_accumulated.json" "$OUT/channels/accumulated.json"
touch "$OUT/.demo_mode"
echo "已加载体验版演示数据（小红书 2 条 + 视频号 2 条）"
