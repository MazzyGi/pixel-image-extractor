#!/usr/bin/env python3
"""解析 Google 工厂镜像页面（需渲染版 HTML：表格由 JS 在点击 Acknowledge 后注入）。

数据源: developers.google.com/android/images
  <h2 id="husky" data-text=""husky" for Pixel 8 Pro">"husky" for Pixel 8 Pro</h2>
  <table><thead>Version|Flash|Download|SHA-256 Checksum</thead>
    <tr id="huskyud1a.230803.022.a3">
      <td>14.0.0 (UD1A.230803.022.A3, Sep 2023, Verizon)</td>
      <td><a href="https://flash.android.com/...">Flash</a></td>
      <td><a href="https://dl.google.com/.../husky-ud1a.230803.022.a3-factory-a95417f6.zip">Link</a></td>
      <td>a95417f6...bc</td>

用法:
  resolve_build.py --list                       # 需渲染页面（--page-cache 或自动 playwright）
  resolve_build.py --device husky --json
  resolve_build.py --device husky --date 20240630 --json
  resolve_build.py --device husky --build-id ap4a.250105.002 --json   # 大小写不敏感
"""
import argparse
import json
import re
import sys
import urllib.request

PAGE_URL = "https://developers.google.com/android/images?hl=en"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")


def fetch_rendered(timeout: int = 120) -> str:
    """Playwright 无头浏览器渲染（自动点击 Acknowledge）。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("[resolve] 需要 playwright: pip install playwright && playwright install chromium")
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(user_agent=UA)
        pg.goto(PAGE_URL, wait_until="domcontentloaded", timeout=timeout * 1000)
        pg.wait_for_timeout(2500)
        for sel in ("text=Acknowledge", "button:has-text('Acknowledge')"):
            try:
                el = pg.query_selector(sel)
                if el:
                    el.click()
                    break
            except Exception:
                pass
        pg.wait_for_timeout(5000)
        html = pg.content()
        b.close()
    if "dl.google.com" not in html:
        raise SystemExit("[resolve] 渲染后仍未发现下载链接（页面结构可能又变了）")
    return html


def parse_devices(html: str) -> dict:
    """{codename: {"name":, "builds": [{version, android, date_hint, carrier, url, sha256}]}}"""
    devices = {}
    h2s = [(m.start(), m) for m in re.finditer(
        r'<h2\s+id="([a-z0-9\-]+)"[^>]*>(.*?)</h2>', html, re.S | re.I)]
    for i, (pos, m) in enumerate(h2s):
        code = m.group(1)
        name = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        name = re.sub(r'^"([^"]+)"\s+for\s+', "", name)
        seg = html[pos: h2s[i + 1][0] if i + 1 < len(h2s) else len(html)]
        builds = []
        for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", seg, re.S | re.I):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S | re.I)
            link = re.search(r'href="(https://dl\.google\.com/dl/android/aosp/[^"]+?\.zip)"',
                             row.group(1), re.I)
            if not link or len(cells) < 4:
                continue
            cell0 = re.sub(r"<[^>]+>", " ", cells[0])
            vm = re.search(r"\(([A-Za-z0-9][A-Za-z0-9.\-_ ]*?)\s*(?:,\s*([A-Za-z]{3}\s+\d{4}))?\s*(?:,\s*([^)]+))?\)", cell0)
            version = vm.group(1).strip() if vm else ""
            date_hint = (vm.group(2) or "").strip() if vm else ""
            carrier = (vm.group(3) or "").strip() if vm else ""
            am = re.match(r"\s*(\d+(?:\.\d+)*)", cell0)
            sha = re.sub(r"<[^>]+>", "", cells[3]).strip().lower()
            if version and re.fullmatch(r"[0-9a-f]{64}", sha):
                builds.append({"version": version, "android": am.group(1) if am else "",
                               "date_hint": date_hint, "carrier": carrier,
                               "url": link.group(1), "sha256": sha})
        if builds:
            devices[code] = {"name": name, "builds": builds}
    return devices


def build_date(version: str):
    """UD1A.230803.022.A3 -> 20230803（无日期返回 None）。"""
    m = re.search(r"[.\-_](\d{2})(\d{2})(\d{2})\.", version)
    if not m:
        m2 = re.search(r"\.(\d{6})\.", version)
        if not m2:
            return None
        s = m2.group(1)
    else:
        s = "".join(m.groups())
    return "20" + s if s.isdigit() and len(s) == 6 else None


def resolve(devices: dict, code: str, date: str = "", build_id: str = "") -> dict:
    dev = devices.get(code.lower())
    if not dev:
        raise SystemExit(f"[resolve] 设备代号未找到: {code}（--list 查看全部）")
    builds = dev["builds"]
    if build_id:
        cand = [b for b in builds if b["version"].lower() == build_id.lower()]
        if not cand:
            known = "\n".join(f"    {b['version']}" for b in builds[:40])
            raise SystemExit(f"[resolve] {code} 无版本 {build_id}。可用（前40）:\n{known}")
        chosen = cand[0]
    elif date:
        cands = [(build_date(b["version"]), -i, b) for i, b in enumerate(builds)
                 if build_date(b["version"]) and build_date(b["version"]) <= date]
        if not cands:
            raise SystemExit(f"[resolve] {code} 没有 ≤{date} 的版本")
        chosen = sorted(cands, key=lambda t: (t[0], t[1]))[-1][2]
    else:
        chosen = builds[0]  # 页面顺序：最新在前
    return {"codename": code.lower(), "device": dev["name"], **chosen}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page-cache", default="")
    ap.add_argument("--no-render", action="store_true", help="只读缓存，不联网")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--device")
    ap.add_argument("--date", default="")
    ap.add_argument("--build-id", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save-page", default="", help="把渲染后的 HTML 存到该路径")
    a = ap.parse_args()

    if a.page_cache:
        html = open(a.page_cache, encoding="utf-8").read()
    else:
        html = fetch_rendered()
        if a.save_page:
            open(a.save_page, "w").write(html)
    devices = parse_devices(html)
    if not devices:
        raise SystemExit("[resolve] 未解析到任何设备（页面来源可疑）")

    if a.list:
        for code, dev in devices.items():
            print(f"{code:12s} {dev['name']:28s} {len(dev['builds']):3d} builds  latest={dev['builds'][0]['version']}")
        return
    if not a.device:
        ap.error("--device 或 --list 必选")
    r = resolve(devices, a.device, a.date, a.build_id)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"device   : {r['codename']} ({r['device']})")
        print(f"version  : {r['version']}  (Android {r['android']})")
        print(f"url      : {r['url']}")
        print(f"sha256   : {r['sha256']}")


if __name__ == "__main__":
    main()
