#!/usr/bin/env python3
"""解压工厂包，提取全部 *.img，并给出精确分区镜像清单。

工厂包布局:
  panther-xxx.zip
    panther-xxx/
      image-panther-xxx.zip     <- boot.img / init_boot.img / vendor_boot.img / dtbo.img / vbmeta*.img / system.img ...
      bootloader-panther-*.zip  <- bootloader.img
      radio-panther-*.zip       <- radio.img
      flash-all / flash-base ...

extract.py <factory.zip> <outdir>
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

AVB = (b"AVB0", b"AvBf")


def q(s):
    return str(s).replace("'", "'\\''")


def main():
    factory = Path(sys.argv[1]).resolve()
    outdir = Path(sys.argv[2]).resolve()
    work = outdir / "_work"
    work.mkdir(parents=True, exist_ok=True)

    print(f"[extract] 解压工厂包 {factory.name}")
    subprocess.run(["unzip", "-o", "-q", str(factory), "-d", str(work)], check=True)

    top = next(p for p in work.iterdir() if p.is_dir())
    imgs_dir = outdir / "images"
    imgs_dir.mkdir(exist_ok=True)

    manifest = []
    # image-*.zip 内的分区镜像
    for z in sorted(top.glob("image-*.zip")):
        with zipfile.ZipFile(z) as zf:
            for name in zf.namelist():
                if name.endswith(".img"):
                    zf.extract(name, imgs_dir)
                    p = imgs_dir / name
                    manifest.append({"name": name, "path": str(p.relative_to(outdir)),
                                     "size": p.stat().st_size, "source": z.name})
    # bootloader-*.zip / radio-*.zip
    for z in sorted(list(top.glob("bootloader-*.zip")) + list(top.glob("radio-*.zip"))):
        with zipfile.ZipFile(z) as zf:
            for name in zf.namelist():
                if name.endswith(".img"):
                    zf.extract(name, imgs_dir)
                    p = imgs_dir / name
                    manifest.append({"name": name, "path": str(p.relative_to(outdir)),
                                     "size": p.stat().st_size, "source": z.name})

    if not manifest:
        raise SystemExit("[extract] 未找到任何 .img")

    # 保留 flash-all 脚本供参考
    for f in top.glob("flash-all*"):
        shutil.copy2(f, outdir / f.name)

    print(f"[extract] 提取 {len(manifest)} 个镜像 -> {imgs_dir}")
    for m in manifest:
        print(f"    {m['name']:20s} {m['size']:>12,d} B  <- {m['source']}")
    (outdir / "manifest.json").write_text(__import__("json").dumps(manifest, indent=2))
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
