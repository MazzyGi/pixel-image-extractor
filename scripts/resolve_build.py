#!/usr/bin/env python3
"""解析 Google 工厂镜像页面，解析设备代号 -> 按日期/版本选定工厂包。

页面结构（developers.google.com/android/images）：
  <h2 id="panther">Pixel 7 Pro</h2>
  ...
  <table> ... <td>13.0 (TQ3A.230805.001)</td><td><a href="https://dl.google.com/...zip">Link</a></td> ...

支持:
  resolve_build.py --list
  resolve_build.py --device panther --json
  resolve_build.py --device panther --date 20250105 --json
  resolve_build.py --device panther --build-id AP4A.250105.002 --json
"""
import argparse
import json
import re
import sys
import urllib.request

PAGE_URL = "https://developers.google.com/android/images?hl=en"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")


def fetch_page(url: str = PAGE_URL, timeout: int = 120) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def strip_tags(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    return html


# --- 设备代号表：h2 id 即官方页面锚点；日期规则在 resolve() 里使用 ---
DEVICE_NAMES = {
    "sailfish": "Pixel", "marlin": "Pixel XL",
    "walleye": "Pixel 2", "taimen": "Pixel 2 XL",
    "blueline": "Pixel 3", "crosshatch": "Pixel 3 XL",
    "sargo": "Pixel 3a", "bonito": "Pixel 3a XL",
    "flame": "Pixel 4", "coral": "Pixel 4 XL",
    "sunfish": "Pixel 4a", "bramble": "Pixel 4a (5G)", "redfin": "Pixel 5",
    "barbet": "Pixel 5a", "raven": "Pixel 6 Pro", "oriole": "Pixel 6",
    "bluejay": "Pixel 6a", "cheetah": "Pixel 7 Pro", "panther": "Pixel 7",
    "lynx": "Pixel 7a", "felix": "Pixel Fold", "tangorpro": "Pixel Tablet",
    "shiba": "Pixel 8", "husky": "Pixel 8 Pro", "akita": "Pixel 8a",
    "comet": "Pixel 9 Pro Fold", "komodo": "Pixel 9 Pro XL", "caiman": "Pixel 9 Pro",
    "tokay": "Pixel 9", "tegu": "Pixel 9a", "snowy": "Pixel 10", "blazer": "Pixel 10 Pro",
    "mustang": "Pixel 10 Pro XL", "sirena": "Pixel 10 Pro Fold",
}


def parse_devices(html: str) -> dict:
    """返回 {codename: {"name": str, "builds": [ {"version","android","url","sha"} ... ]}}"""
    text = strip_tags(html)
    devices = {}
    # 每个 h2/h3 锚点后到下一个锚点之间的表格属于该设备
    anchors = [(m.start(), m) for m in re.finditer(
        r'<h[23]\s+id="([a-z0-9\-]+)"[^>]*>(.*?)</h[23]>', html, re.I)]
    for i, (pos, m) in enumerate(anchors):
        code = m.group(1)
        name = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        seg_html = html[pos: anchors[i + 1][0] if i + 1 < len(anchors) else len(html)]
        seg_text = strip_tags(seg_html)
        builds = []
        # 行: <tr><td>13.0 (TQ3A.230805.001)</td> ... <a href="....zip">
        for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", seg_html, re.S | re.I):
            cells = [re.sub(r"<[^>]+>", " ", c).strip()
                     for c in re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S | re.I)]
            link = re.search(r'href="(https://dl\.google\.com/dl/android/aosp/[^"]+?\.zip)"',
                             row.group(1), re.I)
            if not link or not cells:
                continue
            cell0 = cells[0]
            vm = re.search(r"\(([A-Z0-9][A-Za-z0-9.\-_]+)\)", cell0)
            version = vm.group(1) if vm else (cell0.split()[-1] if cell0 else "")
            am = re.match(r"(\d+(?:\.\d+)*)", cell0)
            android = am.group(1) if am else ""
            builds.append({"version": version, "android": android,
                           "url": link.group(1), "cell": cell0})
        if builds:
            devices[code] = {"name": name, "builds": builds}
    return devices


BUILD_DATE_RE = re.compile(r"[.\-_](\d{8})[.\-_]?$|\d+\.(\d{6})")  # AP4A.250105.002 / UPB4.230623.005


def build_date(version: str):
    """从版本号提取构建日期 YYYYMMDD；无则 None。"""
    m = re.search(r"(\d{2})(\d{2})(\d{2})\.\d+$", version)  # 250105.002 -> 25 01 05
    if not m:
        return None
    return "20" + "".join(m.groups())


def resolve(devices: dict, code: str, date: str = "", build_id: str = "") -> dict:
    dev = devices.get(code)
    if not dev:
        raise SystemExit(f"[resolve] 设备代号未在页面找到: {code}（--list 查看全部）")
    builds = dev["builds"]
    chosen = None
    if build_id:
        cand = [b for b in builds if b["version"] == build_id]
        if not cand:
            known = "\n".join(f"    {b['version']}" for b in builds[:40])
            raise SystemExit(f"[resolve] {code} 没有版本 {build_id}。可用版本（前40）:\n{known}")
        chosen = cand[0]
    elif date:
        cands = [(build_date(b["version"]), i, b) for i, b in enumerate(builds)
                 if build_date(b["version"]) and build_date(b["version"]) <= date]
        if not cands:
            raise SystemExit(f"[resolve] {code} 没有早于等于 {date} 的版本")
        chosen = sorted(cands, key=lambda t: (t[0], t[1]), reverse=True)[0][2]
    else:
        chosen = builds[0]  # 页面顺序：最新在前
    return {"codename": code, "device": dev["name"], **chosen}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page-cache", default="")          # 已下载页面路径（离线/本地复用）
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--device")
    ap.add_argument("--date", default="")
    ap.add_argument("--build-id", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    html = open(args.page_cache, encoding="utf-8").read() if args.page_cache else fetch_page()
    devices = parse_devices(html)

    if args.list:
        for code, dev in devices.items():
            print(f"{code:12s} {dev['name']:24s} {len(dev['builds'])} builds  latest={dev['builds'][0]['version']}")
        return

    if not args.device:
        ap.error("--device 或 --list 必选")

    r = resolve(devices, args.device, args.date, args.build_id)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"device   : {r['codename']} ({r['device']})")
        print(f"version  : {r['version']}  (Android {r['android']})")
        print(f"url      : {r['url']}")


if __name__ == "__main__":
    main()
