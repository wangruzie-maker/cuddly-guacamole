#!/usr/bin/env bash
# 打包体验版 zip，发给同事解压后双击「体验版.command」即可演示
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
NAME="社媒内容提取-体验版-v1.7.0"
OUT_ZIP="$DIR/dist/${NAME}.zip"

mkdir -p "$DIR/dist"
rm -f "$OUT_ZIP"

cd "$DIR/.."
zip -r "$OUT_ZIP" "xhs-note-extractor" \
  -x "xhs-note-extractor/output/*" \
  -x "xhs-note-extractor/output/**" \
  -x "xhs-note-extractor/dist/*" \
  -x "xhs-note-extractor/**/__pycache__/*" \
  -x "xhs-note-extractor/**/*.pyc" \
  -x "xhs-note-extractor/.git/*" \
  -x "xhs-note-extractor/.git/**" \
  -x "xhs-note-extractor/**/.DS_Store"

echo ""
echo "已生成: $OUT_ZIP"
echo "发给同事后：解压 → 双击「体验版.command」→ 浏览器自动打开演示页面"
du -h "$OUT_ZIP"
