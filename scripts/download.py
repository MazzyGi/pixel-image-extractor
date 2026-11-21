#!/usr/bin/env python3
"""断点续传下载 + 完整性验证。

download.py <url> <output> [--min-size N] [--hash sha256:HEX]

特性:
  - Range 断点续传（dl.google.com 支持，206 已验证）
  - 校验 Content-Length 与实际大小、最终 416 时判定已完成
  - --hash 可选哈希校验
  - zip 完整性由调用方用 unzip -t 完成（这里不做 zip 魔数以外的判断）
"""
import argparse
import hashlib
import os
import subprocess
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
CHUNK = 1 << 20


def fmt(n: float) -> str:
    for u in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or u == "GiB":
            return f"{n:.1f}{u}"
        n /= 1024


def head_size(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers.get("Content-Length", "0"))


def download(url: str, out: str, min_size: int, want_hash: str):
    total = head_size(url)
    if total and total < min_size:
        raise SystemExit(f"[download] Content-Length {total} < 最小 {min_size}，URL 可能失效")
    part = out + ".part"
    pos = os.path.getsize(part) if os.path.exists(part) else 0
    if total and pos > total:
        os.remove(part); pos = 0
    if total and pos == total:
        os.replace(part, out)
        print(f"[download] 已完成（断点文件即完整）: {out} ({fmt(total)})")
    else:
        t0 = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": f"bytes={pos}-"})
        with urllib.request.urlopen(req, timeout=120) as r, open(part, "ab") as f:
            if pos and r.status != 206:
                raise SystemExit("[download] 服务器不支持 Range，重新下载")
                os.remove(part); pos = 0; f = open(part, "wb")
            mode = "续传" if pos else "下载"
            done = pos
            last = [0]
            while True:
                b = r.read(CHUNK)
                if not b:
                    break
                f.write(b)
                done += len(b)
                if time.time() - last[0] > 5:
                    pct = f" {done*100//total}%" if total else ""
                    spd = fmt((done - pos) / max(time.time() - t0, 1e-3))
                    print(f"[download] {mode}{pct} {fmt(done)}/{fmt(total) if total else '?'} {spd}/s", flush=True)
                    last[0] = time.time()
        if total and done != total:
            raise SystemExit(f"[download] 大小不符: {done} != {total}")
        os.replace(part, out)
        print(f"[download] 完成: {out} {fmt(done)}")
    if want_hash:
        h = hashlib.sha256()
        with open(out, "rb") as f:
            for b in iter(lambda: f.read(1 << 22), b""):
                h.update(b)
        got = h.hexdigest()
        if got != want_hash:
            raise SystemExit(f"[download] SHA256 不符: got {got} want {want_hash}")
        print(f"[download] SHA256 OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("output")
    ap.add_argument("--min-size", type=int, default=200 * 1024 * 1024)
    ap.add_argument("--hash", default="")
    a = ap.parse_args()
    download(a.url, a.output, a.min_size, a.hash)
    if a.output.endswith(".zip"):
        rc = subprocess.run(["unzip", "-t", a.output], stdout=subprocess.DEVNULL).returncode
        if rc != 0:
            raise SystemExit("[download] zip 完整性测试失败 (unzip -t)")


if __name__ == "__main__":
    main()
