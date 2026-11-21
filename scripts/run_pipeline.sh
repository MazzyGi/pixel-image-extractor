#!/usr/bin/env bash
# Pixel 工厂镜像提取流水线（本地可运行；Actions 里被 build.yml 调用）
# 用法: run_pipeline.sh <codename> [date YYYYMMDD] [build_id] [upload_regex] [keep_factory]
set -euo pipefail

DEVICE="${1:?用法: run_pipeline.sh <codename> [date] [build_id] [upload_regex] [keep_factory]}"
DATE="${2:-}"
BUILD_ID="${3:-}"
UPLOAD_RE="${4:-^(init_boot|boot|vendor_boot|dtbo|vbmeta.*|bootloader|radio)\.img$}"
KEEP_FACTORY="${5:-false}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/work/$DEVICE"
mkdir -p "$WORK"

echo "== [1/5] 解析版本 =="
python3 "$ROOT/scripts/resolve_build.py" --device "$DEVICE" ${DATE:+--date "$DATE"} \
    ${BUILD_ID:+--build-id "$BUILD_ID"} --json > "$WORK/resolve.json"
cat "$WORK/resolve.json"
URL=$(python3 -c "import json;print(json.load(open('$WORK/resolve.json'))['url'])")
VERSION=$(python3 -c "import json;print(json.load(open('$WORK/resolve.json'))['version'])")
TAG="$DEVICE-$VERSION"

echo "== [2/5] 下载工厂包 =="
python3 "$ROOT/scripts/download.py" "$URL" "$WORK/factory.zip"

echo "== [3/5] 解压提取 =="
python3 "$ROOT/scripts/extract.py" "$WORK/factory.zip" "$WORK"

echo "== [4/5] 验证 =="
python3 "$ROOT/scripts/verify.py" "$WORK/images" --out "$WORK/verify.json"

echo "== [5/5] 生成清单 =="
python3 "$ROOT/scripts/make_release.py" "$WORK" --tag "$TAG" \
  --device "$(python3 -c "import json;print(json.load(open('$WORK/resolve.json'))['device'])")" \
  --version "$VERSION" --factory-url "$URL" \
  --factory-size "$(stat -c%s "$WORK/factory.zip")" \
  --upload-glob "$UPLOAD_RE"

echo "== 完成: $WORK =="
ls -la "$WORK" "$WORK/images" | head -40
