#!/usr/bin/env python3
"""
gen_trans7_token.py — Generate Wowza SecureToken URL for Trans7 (pure Python, no browser).

Algorithm reversed from detikVideo.core.js:
  Secret: 258eed02421df5e2
  Hash input: trans7-sec/smil:trans7.smil?{secret}&wowzatokenendtime={ms}&wowzatokenstarttime=0
  SHA256 → base64 → URL-safe (+→-, /→_, keep = padding)

Output: full playlist.m3u8 URL with valid token.
"""
import base64
import hashlib
import sys
import time
import urllib.parse


SECRET = "258eed02421df5e2"
ST_URL_PREFIX = "trans7-sec/smil:"
ST_URL_POSTFIX = "trans7.smil"
EXPIRE_MINUTES = 15


def generate_token_url() -> tuple[str, int, str]:
    """Return (url, endtime_ms, hash_token)."""
    now_ms = int(time.time() * 1000)
    end_ms = now_ms + EXPIRE_MINUTES * 60 * 1000
    start = "0"

    hash_input = f"{ST_URL_PREFIX}{ST_URL_POSTFIX}?{SECRET}&wowzatokenendtime={end_ms}&wowzatokenstarttime={start}"
    sha = hashlib.sha256(hash_input.encode()).digest()
    b64 = base64.b64encode(sha).decode()
    # URL-safe: + → -, / → _, keep = padding
    token = b64.replace("+", "-").replace("/", "_")

    url = (
        f"https://video.detik.com/{ST_URL_PREFIX}{ST_URL_POSTFIX}/playlist.m3u8"
        f"?wowzatokenstarttime={start}"
        f"&wowzatokenendtime={end_ms}"
        f"&wowzatokenhash={urllib.parse.quote(token, safe='')}"
    )
    return url, end_ms, token


def main():
    url, end_ms, token = generate_token_url()
    expire_human = time.strftime("%Y-%m-%d %H:%M:%S WIB", time.localtime(end_ms / 1000))
    print(f"TOKEN_URL={url}")
    print(f"EXPIRE_MS={end_ms}")
    print(f"EXPIRE_AT={expire_human}")
    print(f"HASH={token}")

    # Also write to file for GHA steps
    import os
    out_dir = os.environ.get("GITHUB_WORKSPACE", ".")
    out_path = os.path.join(out_dir, "trans7_url.txt")
    with open(out_path, "w") as f:
        f.write(url + "\n")
    print(f"[saved] {out_path}")


if __name__ == "__main__":
    main()
