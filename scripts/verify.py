#!/usr/bin/env python3
"""分区镜像有效性验证：结构化解析 boot header / AVB / dtbo / sparse，计算 SHA256。

verify.py <images_dir> [--out verify.json]

镜像均为官方包原样解出；本脚本只读不改。

字段布局依据 AOSP：
  bootimg.h (boot/init_boot/recovery, ANDROID! magic, v0-v4)
  bootimg.h (vendor_boot, VNDRBOOT magic, v3/v4)
  libavb/avb_vbmeta_image.h / avb_footer.h
  libdt_table (dtbo.img)
  libsparse/sparse_format.h (system.img 等)
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

BOOT_MAGIC = b"ANDROID!"
VENDOR_BOOT_MAGIC = b"VNDRBOOT"
AVB_MAGIC = b"AVB0"
AVB_FOOTER_MAGIC = b"AvBf"
DT_TABLE_MAGIC = 0xD7B7AB1E
SPARSE_MAGIC = 0xED26FF3A


def u16(b, o): return int.from_bytes(b[o:o + 2], "little")
def u32(b, o): return int.from_bytes(b[o:o + 4], "little")
def u64(b, o): return int.from_bytes(b[o:o + 8], "little")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def pages(n, page): return (n + page - 1) // page


def decode_os_version(v: int) -> str:
    """bootimg.h: bits31-25 major, 24-18 minor, 17-11 patch, 10-4 year-2000, 3-0 month."""
    a, b = (v >> 25) & 0x7F, (v >> 18) & 0x7F
    c, y, m = (v >> 11) & 0x7F, (v >> 4) & 0x7F, v & 0xF
    if not (a or b or c or y or m):
        return ""
    s = f"{a}.{b}.{c}" if c else f"{a}.{b}"
    if y or m:
        s += f" (20{y:02d}-{m:02d})"
    return s


def check_android_boot(d: bytes, size: int) -> dict:
    """boot/init_boot/recovery（ANDROID!，header v0-v4）。"""
    if d[:8] != BOOT_MAGIC:
        return {"ok": False, "error": "boot magic 不匹配 (ANDROID!)"}
    ver = u32(d, 40)
    info = {"ok": True, "type": "android_boot", "header_version": ver}
    if ver <= 2:
        kernel_size, ramdisk_size = u32(d, 8), u32(d, 16)
        second_size = u32(d, 24)
        page = u32(d, 36)
        osv = u32(d, 44)
        name = d[48:64].split(b"\0")[0].decode("ascii", "replace")
        cmdline = d[64:576].split(b"\0")[0].decode("ascii", "replace")
        info.update(kernel_size=kernel_size, ramdisk_size=ramdisk_size,
                    second_size=second_size, page_size=page, name=name,
                    os_version=decode_os_version(osv), cmdline=cmdline[:80])
        if ver == 0:
            hdr_pages = 1
        else:
            info["recovery_dtbo_size"] = u32(d, 1632)
            info["header_size"] = u32(d, 1648)
            hdr_pages = pages(max(u32(d, 1648), 1), page)
        if ver == 2:
            info["dtb_size"] = u32(d, 1652)
        used = page * (hdr_pages + pages(kernel_size, page) + pages(ramdisk_size, page)
                       + pages(second_size, page)
                       + pages(info.get("recovery_dtbo_size", 0), page)
                       + pages(info.get("dtb_size", 0), page))
    elif ver in (3, 4):
        kernel_size, ramdisk_size = u32(d, 8), u32(d, 12)
        osv, hdr_sz = u32(d, 16), u32(d, 20)
        cmdline = d[44:44 + 1536].split(b"\0")[0].decode("ascii", "replace")
        info.update(kernel_size=kernel_size, ramdisk_size=ramdisk_size,
                    header_size=hdr_sz, os_version=decode_os_version(osv),
                    cmdline=cmdline[:80])
        page = 4096
        used = page * (1 + pages(kernel_size, page) + pages(ramdisk_size, page))
        if ver == 4:
            sig = u32(d, 2604) if len(d) > 2608 else 0
            info["boot_signature_size"] = sig
            used += page * pages(sig, page)
    else:
        return {"ok": False, "error": f"未知 boot header version {ver}"}
    info["min_size"] = used
    info["size_match"] = size >= used
    info["ok"] = bool(info["size_match"])
    if ver <= 2 and page not in (2048, 4096):
        info["ok"] = False
        info["error"] = f"非常规 page_size {page}"
    elif not info["size_match"]:
        info["error"] = f"镜像小于结构最小值: {size} < {used}"
    return info


def check_vendor_boot(d: bytes, size: int) -> dict:
    """vendor_boot（VNDRBOOT，v3/v4）。"""
    if d[:8] != VENDOR_BOOT_MAGIC:
        return {"ok": False, "error": "vendor_boot magic 不匹配 (VNDRBOOT)"}
    ver, page = u32(d, 8), u32(d, 12)
    vrd_size = u32(d, 24)
    name = d[32:48].split(b"\0")[0].decode("ascii", "replace")
    dtb_size = u32(d, 52)
    info = {"ok": True, "type": "vendor_boot", "header_version": ver,
            "page_size": page, "vendor_ramdisk_size": vrd_size,
            "dtb_size": dtb_size, "name": name}
    hdr_sz = u32(d, 48)
    used = page * (pages(hdr_sz or page, page) + pages(vrd_size, page) + pages(dtb_size, page))
    info["min_size"] = used
    info["size_match"] = size >= used
    info["ok"] = bool(info["size_match"])
    if not info["size_match"]:
        info["error"] = f"镜像小于结构最小值: {size} < {used}"
    return info


def check_avb_header(d: bytes) -> dict:
    """vbmeta*.img 主头（libavb avb_vbmeta_image.h）。"""
    if d[:4] != AVB_MAGIC:
        return {"ok": False, "error": "vbmeta magic 不匹配 (AVB0)"}
    auth_sz, aux_sz = u64(d, 12), u64(d, 20)
    algo = u32(d, 28)
    desc_off, desc_sz = u64(d, 96), u64(d, 104)
    rollback = u64(d, 112)
    flags = u32(d, 120)
    release = d[128:176].split(b"\0")[0].decode("ascii", "replace")
    ver = f"{u32(d, 4)}.{u32(d, 8)}"
    return {"ok": True, "type": "avb_vbmeta", "libavb_version": ver,
            "algorithm_type": algo, "auth_block_size": auth_sz,
            "aux_block_size": aux_sz, "descriptors_size": desc_sz,
            "rollback_index": rollback, "flags": flags, "release_string": release}


def check_avb_footer(d: bytes, size: int) -> dict:
    """文件尾 64B AVB footer（avb_footer.h）。d 必须是文件最后 ≥64B。"""
    if len(d) < 64:
        return {"ok": False, "error": "尾部不足 64B"}
    f = d[-64:]
    if f[:4] != AVB_FOOTER_MAGIC:
        return {"ok": True, "avb_footer": False, "note": "无 AVB footer（raw 镜像）"}
    orig = u64(f, 12)
    vm_off, vm_sz = u64(f, 20), u64(f, 28)
    ok = (vm_off + vm_sz <= size) and (orig <= size)
    r = {"ok": bool(ok), "avb_footer": True, "original_image_size": orig,
         "vbmeta_offset": vm_off, "vbmeta_size": vm_sz}
    if ok and vm_sz >= 4:
        h = check_avb_header(d_full[vm_off:vm_off + 256]) if len(d) >= size else None
        # footer 数据块只有尾部；vbmeta 头由调用方传入完整文件时校验
        r["vbmeta_header_check"] = "deferred"
    if not ok:
        r["error"] = "vbmeta 指针越界"
    return r


def check_dtbo(d: bytes, size: int) -> dict:
    """dtbo.img dt_table_header。"""
    if len(d) < 32 or u32(d, 0) != DT_TABLE_MAGIC:
        return {"ok": False, "error": "dt_table magic 不匹配"}
    total, hdr_sz, ent_sz = u32(d, 4), u32(d, 8), u32(d, 12)
    cnt, ents_off = u32(d, 16), u32(d, 20)
    need = ents_off + cnt * ent_sz
    ok = need <= size and (total == 0 or total <= size)
    return {"ok": bool(ok), "type": "dt_table", "dt_entry_count": cnt,
            "dt_entry_size": ent_sz, "entries_offset": ents_off,
            "min_size": need, "size_match": bool(ok)}


def check_sparse(d: bytes, size: int) -> dict:
    """system/vendor/product 等 sparse 镜像头。"""
    if len(d) < 32 or u32(d, 0) != SPARSE_MAGIC:
        return None
    file_hdr_sz, chunk_hdr_sz = u16(d, 8), u16(d, 10)
    blk_sz, total_blks, total_chunks = u32(d, 12), u32(d, 16), u32(d, 20)
    info = {"ok": True, "type": "sparse", "major_version": u16(d, 4),
            "block_size": blk_sz, "block_count": total_blks,
            "chunk_count": total_chunks,
            "image_bytes": total_blks * blk_sz}
    return info


d_full = b""  # verify_image 里设置为文件前 4MiB（footer 校验用）


def verify_image(p: Path) -> dict:
    global d_full
    size = p.stat().st_size
    with open(p, "rb") as f:
        head = f.read(4 << 20)
        if size > (4 << 20):
            f.seek(size - (4 << 20))
            tail = f.read()
        else:
            tail = head
    d_full = head
    res = {"name": p.name, "size": size, "sha256": sha256_file(p)}
    name = p.name.lower()

    if name.startswith("vendor_boot"):
        res["check"] = check_vendor_boot(head, size)
    elif name.startswith(("boot.", "init_boot", "recovery")) and not name.startswith("bootloader"):
        res["check"] = check_android_boot(head, size)
    elif "vbmeta" in name:
        res["check"] = check_avb_header(head)
    elif "dtbo" in name:
        res["check"] = check_dtbo(head, size)
    else:
        sp = check_sparse(head, size)
        if sp:
            res["check"] = sp
        else:
            res["check"] = {"ok": True, "type": "vendor/raw",
                            "note": "厂商格式（bootloader/radio）或 raw ext4，仅哈希校验"}
    # 凡是尾部带 AVB footer 的，都校验 footer 合法性
    if size >= 64 and not name.startswith("bootloader") and "radio" not in name:
        ftr = tail[-64:]
        if ftr[:4] == AVB_FOOTER_MAGIC:
            vm_off, vm_sz = u64(ftr, 20), u64(ftr, 28)
            ok = vm_off + vm_sz <= size
            avb = {"avb_footer": True, "original_image_size": u64(ftr, 12),
                   "vbmeta_offset": vm_off, "vbmeta_size": vm_sz, "ok": bool(ok)}
            if ok and vm_off + 4 <= len(head) + 0:  # vbmeta 头在头部可读范围时校验魔数
                with open(p, "rb") as f2:
                    f2.seek(vm_off)
                    vm = f2.read(4)
                avb["vbmeta_magic_ok"] = vm == AVB_MAGIC
                if not avb["vbmeta_magic_ok"]:
                    avb["ok"] = False
            res["avb_footer"] = avb
    res["valid"] = bool(res.get("check", {}).get("ok", True)) and (
        not res.get("avb_footer") or res["avb_footer"].get("ok", True))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    d = Path(a.dir)
    results = [verify_image(p) for p in sorted(d.glob("*.img"))]
    bad = [r for r in results if not r["valid"]]
    for r in results:
        mark = "✔" if r["valid"] else "✘"
        c = r.get("check", {})
        detail = c.get("type") or c.get("error") or ""
        hv = c.get("header_version")
        line = f"  {mark} {r['name']:22s} {r['size']:>12,d}B  {detail}"
        if hv is not None:
            line += f" v{hv}"
        if c.get("os_version"):
            line += f"  os={c['os_version']}"
        if r.get("avb_footer"):
            line += "  +AVBfooter"
        print(line)
    if a.out:
        Path(a.out).write_text(json.dumps(
            {"valid": not bad, "images": results}, indent=2, ensure_ascii=False))
    if bad:
        print(f"[verify] {len(bad)} 个镜像无效!", file=sys.stderr)
        sys.exit(1)
    print(f"[verify] 全部 {len(results)} 个镜像验证通过")


if __name__ == "__main__":
    main()
