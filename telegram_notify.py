#!/usr/bin/env python3
"""Kirim link 720p ke Telegram — label jelas FRESH vs STALE (capture gagal).

Bukan bandingin URL: status dari cocote/capture_status.json (ditulis m3u8_capture.py).
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

STATUS_PATH = Path("cocote/capture_status.json")
LIVE_URL_PATH = Path("cocote/live_url.txt")


def load_status() -> dict:
    if not STATUS_PATH.exists():
        return {
            "ok": False,
            "fresh": False,
            "reason": "capture_status.json missing (capture mungkin gagal sebelum tulis status)",
            "captured_at": "",
            "checked_at": "",
            "url": "",
            "resolution": "",
        }
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "ok": False,
            "fresh": False,
            "reason": f"status_parse_error: {e}",
            "captured_at": "",
            "checked_at": "",
            "url": "",
            "resolution": "",
        }


def load_url(st: dict) -> str:
    if st.get("url"):
        return str(st["url"]).strip()
    if LIVE_URL_PATH.exists():
        return LIVE_URL_PATH.read_text(encoding="utf-8").strip()
    return ""


def build_text(st: dict, url: str) -> str:
    fresh = bool(st.get("fresh") or st.get("ok"))
    reason = st.get("reason") or ("ok" if fresh else "unknown")
    res = st.get("resolution") or "?"
    captured_at = st.get("captured_at") or "-"
    checked_at = st.get("checked_at") or "-"

    if fresh:
        header = "✅ <b>720p FRESH</b> — capture run ini <b>BERHASIL</b>"
        note = "Link di bawah dari capture <b>baru</b> (bukan file lama di repo)."
    else:
        header = "⚠️ <b>720p STALE</b> — capture run ini <b>GAGAL</b>"
        note = (
            "Link di bawah (kalau ada) dari <b>file lama di git / run sebelumnya</b>. "
            "Jangan anggap fresh hanya karena URL kelihatan valid."
        )

    lines = [
        header,
        "",
        f"📌 status: <code>{'FRESH' if fresh else 'STALE'}</code>",
        f"📌 capture_ok: <code>{bool(st.get('ok'))}</code>",
        f"📌 reason: <code>{reason}</code>",
        f"📌 resolution: <code>{res}</code>",
        f"📌 captured_at: <code>{captured_at}</code>",
        f"📌 checked_at: <code>{checked_at}</code>",
        "",
        note,
        "",
    ]
    if url:
        lines += [f"<pre>{url}</pre>", "", "📋 /record"]
    else:
        lines += ["(tidak ada URL di live_url.txt / status)"]
    return "\n".join(lines)


def main() -> None:
    token = os.environ["BOT_TOKEN"]
    chat_id = os.environ["CHAT_ID"]
    st = load_status()
    url = load_url(st)
    text = build_text(st, url)

    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "parse_mode": "HTML", "text": text}
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        method="POST",
    )
    r = urllib.request.urlopen(req)
    print(r.read().decode()[:200])
    print(
        f"[notify] fresh={bool(st.get('fresh') or st.get('ok'))} "
        f"reason={st.get('reason')} url_len={len(url)}"
    )


if __name__ == "__main__":
    main()
