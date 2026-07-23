#!/usr/bin/env python3
"""
m3u8_capture.py - Capture playlist .m3u8 (Playwright headless).

Alur:
  1. Buka Chromium
  2. Navigasi ke embed player
  3. Fetch API -> master playlist
  4. Parse variant, lock 720p
  5. Simpan wosufemi/captured.m3u8 + live_url.txt
  6. Tulis wosufemi/capture_status.json (sukses/gagal) — dipakai notify

Catatan: URL token rotate 1-2 jam. Bukan link permanen.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright

VIDEO_ID = "x8qckyq"
PLAYER_URL = f"https://geo.dailymotion.com/player/x15a7g.html?video={VIDEO_ID}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
OUT_DIR = "wosufemi"
OUT = os.path.join(OUT_DIR, "captured.m3u8")
LIVE_URL = os.path.join(OUT_DIR, "live_url.txt")
STATUS_FILE = os.path.join(OUT_DIR, "capture_status.json")
PRIORITY = ["720", "480", "240"]
WIB = timezone(timedelta(hours=7))


def _now_iso() -> str:
    # WIB (UTC+7) — contoh: 2026-07-23T17:58:56+07:00
    return datetime.now(WIB).strftime("%Y-%m-%dT%H:%M:%S+07:00")


def write_status(ok: bool, reason: str = "", url: str = "", res: str = "") -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    payload = {
        "ok": bool(ok),
        "fresh": bool(ok),  # True hanya kalau capture run ini berhasil
        "reason": reason or ("ok" if ok else "unknown"),
        "captured_at": _now_iso() if ok else "",
        "checked_at": _now_iso(),
        "url": url,
        "resolution": res,
        "source": "m3u8_capture.py",
    }
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    print(f"[status] ok={ok} fresh={ok} reason={payload['reason']}")


def pick_variant(master_body):
    lines = master_body.splitlines()
    variants = []
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            name = ""
            if 'NAME="' in line:
                name = line.split('NAME="')[1].split('"')[0]
            if i + 1 < len(lines) and lines[i + 1].startswith("https://"):
                url = lines[i + 1].split("#")[0]
                variants.append((name, url))
    for p in PRIORITY:
        for name, url in variants:
            if name == p or f"live-{p}" in url:
                return url, variants
    if variants:
        return variants[0][1], variants
    return "", []


def main():
    result = None
    try:
        with sync_playwright() as p:
            launch_kwargs = {"headless": True}
            if os.environ.get("CAPTURE_USE_CHROME") == "1":
                launch_kwargs["channel"] = "chrome"
            b = p.chromium.launch(**launch_kwargs)
            ctx = b.new_context(user_agent=UA)
            pg = ctx.new_page()
            print(f"[*] buka {PLAYER_URL}")
            pg.goto(PLAYER_URL, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(6000)
            print("[*] fetch master playlist dari page context...")
            result = pg.evaluate(
                """async () => {
                const api = 'https://geo.dailymotion.com/video/x8qckyq.json?legacy=true&geo=1&player-id=x15a7g&publisher-id=x2virdk&locale=id&dmV1st=4975e6cb-4f89-8c56-cb06-3e7775a8c1ee&dmTs=' + (Math.floor(Date.now()/1000)%1000000) + '&is_native_app=0&app=idm.internet.download.manager.plus&dmViewId=1jtncqgbk6a3020c78f&parallelCalls=1';
                const d = await (await fetch(api, {credentials:'include'})).json();
                const m3u8 = d.qualities.auto[0].url;
                const r = await fetch(m3u8, {credentials:'include'});
                const t = await r.text();
                return {status: r.status, url: m3u8, body: t};
            }"""
            )
            b.close()
    except Exception as e:
        write_status(False, reason=f"playwright_error: {e}")
        print(f"[!] exception: {e}")
        sys.exit(1)

    if not result or result.get("status") != 200 or not result.get("body"):
        write_status(False, reason=f"master_fetch_failed: {str(result)[:180]}")
        print(f"[!] gagal: {str(result)[:200]}")
        sys.exit(1)

    master_url = result["url"]
    master_body = result["body"]
    print(f"[+] MASTER 200 ({master_url[:120]})")
    print(master_body[:1500])

    chosen, variants = pick_variant(master_body)
    if not chosen:
        write_status(False, reason="no_variant_in_master")
        print("[!] gak ada variant ditemukan di master body")
        sys.exit(1)

    print(f"[+] variant ditemukan: {len(variants)} -> pilih: {chosen[:120]}")

    os.makedirs(OUT_DIR, exist_ok=True)
    ts = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
    full = [
        "#EXTM3U",
        f"# capture-from: {PLAYER_URL}",
        f"# generated: {ts}",
        "",
        master_body.rstrip(),
        "",
        "# all-variants:",
    ]
    for name, url in variants:
        full.append(f"#   {name}: {url}")
    out = "\n".join(full) + "\n"
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"[+] disimpan ke {OUT} ({len(out)} bytes)")

    url_720 = chosen
    if "live-240" in url_720:
        url_720 = url_720.replace("live-240", "live-720")
    with open(LIVE_URL, "w", encoding="utf-8") as f:
        f.write(url_720 + "\n")
    print(f"[+] {LIVE_URL} -> {url_720[:120]}")

    m = re.search(r"live-(\d+)", url_720)
    res = f"{m.group(1)}p" if m else "unknown"
    write_status(True, reason="capture_ok", url=url_720, res=res)
    if "live-720" in url_720:
        print("[OK] 720p locked")
    else:
        print(f"[OK] resolved to {res}")


if __name__ == "__main__":
    main()
