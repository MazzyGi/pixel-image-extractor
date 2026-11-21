#!/usr/bin/env python3
"""生成 Release 内容：SHA256SUMS + links.md（各镜像下载地址清单）。

make_release.py <work_dir> --tag panther-AP4A.250105.002 \
  --device "Pixel 7" --version AP4A.250105.002 \
  --factory-url https://dl.google.com/... --factory-sha <hex> \
  --upload-glob "^(init_boot|boot|vbmeta.*)\\.img$" --repo USER/REPO [--release-id N]

带 --release-id 时 links.md 写入附件直链（--repo 必填）；否则附件区留待回填。
"""
import argparse
import hashlib
import re
from pathlib import Path

GH_DL = "https://github.com/{repo}/releases/download/{tag}/{name}"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def fmt(n):
    for u in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or u == "GiB":
            return f"{n:.1f}{u}"
        n /= 1024


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
    imgs = sorted(d.glob("images/*.img"))
    upload_re = re.compile(a.upload_glob) if a.upload_glob else None
    repo = a.repo or "USER/REPO"

    # SHA256SUMS
    lines = []
    for p in imgs:
        lines.append(f"{sha256_file(p)}  images/{p.name}")
    if a.factory_sha:
        lines.append(f"{a.factory_sha}  factory.zip   # 官方 SHA-256; {a.factory_url}")
    (d / "SHA256SUMS").write_text("\n".join(lines) + "\n")

    # links.md
    up = [p for p in imgs if not upload_re or upload_re.search(p.name)]
    md = [f"# {a.device} ({a.tag.split('-')[0]}) — {a.version} 镜像下载地址\n",
          f"官方完整工厂包（含全部镜像，Google 直链）: {a.factory_url}"]
    if a.factory_size:
        md.append(f"- 大小: {a.factory_size:,} B")
    if a.factory_sha:
        md.append(f"- 官方 SHA-256: `{a.factory_sha}`")
    md.append("\n## 本仓库 Release 附件直链\n")
    if a.release_id:
        for p in up:
            url = GH_DL.format(repo=repo, tag=a.tag, name=p.name)
            md.append(f"- [{p.name}]({url}) — {fmt(p.stat().st_size)}  (`{sha256_file(p)}`)")
    else:
        for p in up:
            md.append(f"- {p.name} — {fmt(p.stat().st_size)}（上传后地址为 "
                      f"`https://github.com/{repo}/releases/download/{a.tag}/{p.name}`）")
    md.append("\n## 官方包内全部镜像（未上传的大镜像请从工厂包直链获取）\n")
    for p in imgs:
        md.append(f"- `{p.name}` — {fmt(p.stat().st_size)}")
    (d / "links.md").write_text("\n".join(md) + "\n")
    print(f"[release] SHA256SUMS {len(imgs)} 项; links.md 附件 {len(up)} 个")


if __name__ == "__main__":
    main()
