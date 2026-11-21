#!/usr/bin/env bash
# 创建/更新 Release 并上传镜像附件（在 Actions 里运行，gh 已内置认证）
# publish_release.sh <device> <tag> <version> <upload_regex> <keep_factory>
set -euo pipefail

DEVICE="$1"; TAG="$2"; VERSION="$3"; UPLOAD_RE="$4"; KEEP_FACTORY="$5"
REPO="${REPO:?}"; GH_TOKEN="${GH_TOKEN:?}"
export GH_TOKEN

DIR="work/$DEVICE"
IMGS="$DIR/images"

# 1. 选取要上传的镜像
mapfile -t UPLOAD < <(python3 - "$IMGS" "$UPLOAD_RE" <<'EOF'
import re, sys, pathlib
d, pat = sys.argv[1], sys.argv[2]
rx = re.compile(pat)
for p in sorted(pathlib.Path(d).glob("*.img")):
    if rx.search(p.name):
        print(p)
EOF
)
echo "将上传 ${#UPLOAD[@]} 个镜像:"
printf '  %s\n' "${UPLOAD[@]:-（无匹配）}"

# 2. GitHub 单附件上限 2GiB（留 8MiB 余量）
LIMIT=$(( (2*1024 - 8) * 1024 * 1024 ))
ASSETS=()
for f in "${UPLOAD[@]}"; do
  if [ "$(stat -c%s "$f")" -gt "$LIMIT" ]; then
    echo "::warning::$(basename "$f") 超过 2GiB 上限，跳过上传（官方直链可获取）"
  else
    ASSETS+=("$f")
  fi
done
[ "$KEEP_FACTORY" = "true" ] && [ "$(stat -c%s "$DIR/factory.zip")" -le "$LIMIT" ] && ASSETS+=("$DIR/factory.zip")

# 3. 报告文件
for f in SHA256SUMS links.md verify.json resolve.json; do
  [ -f "$DIR/$f" ] && cp "$DIR/$f" "/tmp/$f"
done
# links.md / SHA256SUMS 放到上传列表
[ -f "$DIR/SHA256SUMS" ] && ASSETS+=("$DIR/SHA256SUMS")
[ -f "$DIR/links.md" ]   && ASSETS+=("$DIR/links.md")

# 4. Release 说明
DEVICE_NAME=$(python3 -c "import json;print(json.load(open('$DIR/resolve.json'))['device'])")
cat > "$DIR/notes.md" <<EOF
# $DEVICE_NAME ($DEVICE) — $VERSION

官方工厂包: $FACTORY_URL
本 Release 由 GitHub Actions 自动构建，镜像均为官方包原样解出（未修改任何字节）。

## 镜像下载地址

见附件列表与 \`links.md\`；每个镜像的 SHA256 见 \`SHA256SUMS\`。

## 验证

\`verify.json\` 为结构化验证报告（boot header / AVB / dtbo / sparse）。
EOF
# 回填官方链接
FACTORY_URL=$(python3 -c "import json;print(json.load(open('$DIR/resolve.json'))['url'])")
sed -i "s|^官方工厂包: .*|官方工厂包: $FACTORY_URL|" "$DIR/notes.md"

# 5. 创建 Release（存在则复用）并上传
if ! gh release view "$TAG" -R "$REPO" >/dev/null 2>&1; then
  gh release create "$TAG" -R "$REPO" --title "$TAG" --notes-file "$DIR/notes.md" --latest
else
  gh release edit "$TAG" -R "$REPO" --notes-file "$DIR/notes.md" --latest >/dev/null
fi

printf '%s\n' "${ASSETS[@]}" | xargs -r gh release upload "$TAG" -R "$REPO" --clobber
echo "== Release 完成: https://github.com/$REPO/releases/tag/$TAG =="
gh release view "$TAG" -R "$REPO" --json assets -q '.assets[].name'
