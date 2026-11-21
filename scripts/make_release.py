#!/usr/bin/env python3
"""生成 Release 内容：SHA256SUMS + links.md（各镜像下载地址清单）。

make_release.py <release_dir> --tag panther-AP4A.250105.002 \
  --device "Pixel 7 Pro" --version AP4A.250105.002 \
  --factory-url https://dl.google.com/... --factory-size 3440657561 --factory-sha <hex> \
  --upload-glob "^(init_boot|boot|vbmeta.*)\\.img$" \
  [--release-id 12345678]   # gh 创建 Release 后回填，用于生成附件直链

links.md 在上传完成后再次调用（带 --release-id）生成最终地址；
也生成 links.md 的“占位版本”（无 release-id 时只含官方直链与说明）。
"""
import argparse
import json
import re
from pathlib import Path

GH_DL = "https://github.com/{repo}/releases/download/{tag}/{name}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--device", default="")
    ap.add_argument("--version", required=True)
    ap.add_argument("--factory-url", default="")
    ap.add_argument("--factory-size", type=int, default=0)
    ap.add_argument("--factory-sha", default="")
    ap.add_argument("--upload-glob", default="")
    ap.add_argument("--repo", default="")
    ap.add_argument("--release-id", default="")
    a = ap.parse_args()

    d = Path(a.dir)
    imgs = sorted(d.glob("*.img"))
    upload_re = re.compile(a.upload_glob) if a.upload_glob else None

    sums = []
    for p in imgs:
        v = json.loads((d / "verify.json").read_text()) if (d / "verify.json").exists() else {}
        sums.append(p)
    # SHA256SUMS
    lines = []
    for p in imgs:
        rec = next((i for i in v.get("images", []) if i["name"] == p.name), {}) if isinstance(v, dict) else {}
        sha = rec.get("sha256", "")
        lines.append(f"{sha}  {p.name}")
    if a.factory_sha:
        lines.append(f"{a.factory_sha}  factory.zip  # {a.factory_url}")
    (d / "SHA256SUMS").write_text("\n".join(lines) + "\n")

    # links.md
    up = [p for p in imgs if not upload_re or upload_re.search(p.name)]
    big = [p for p in imgs if p.stat().st_size > 2 * 1024 ** 3]
    repo = a.repo or "YOUR_USER/YOUR_REPO"
    md = [f"# {a.device} ({a.tag.split('-')[0]}) — {a.version} 镜像下载地址\n"]
    md.append(f"- 官方完整工厂包（Google 直链，含全部镜像）: {a.factory_url}")
    if a.factory_size:
        md.append(f"  - 大小: {a.factory_size:,} B")
    md.append("")
    md.append("## Release 附件（本仓库托管）\n")
    if a.release_id:
        for p in up:
            url = GH_DL.format(repo=repo, tag=a.tag, name=p.name)
            md.append(f"- [{p.name}]({url}) — {p.stat().st_size:,} B")
    else:
        md.append("(上传后自动回填附件直链；下方为官方工厂包内的对应关系)")
    md.append(f"\n> 单附件 >2GiB 的镜像（如 {', '.join(p.name for p in big) or '无'}）超出 GitHub 上限，"
              f"请使用官方工厂包直链获取。\n")
    (d / "links.md").write_text("\n".join(md) + "\n")
    print(f"[release] 写出 SHA256SUMS ({len(imgs)}) 与 links.md (附件 {len(up)} 个)")


if __name__ == "__main__":
    main()
