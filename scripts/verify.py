#!/usr/bin/env python3
"""
verify.py — Verify recording integrity via SHA256 hash comparison.

Usage:
  python3 verify.py <release_tag>         # fetch release .txt, show metadata + hashes
  python3 verify.py <release_tag> <file>  # verify local file against release hash
  python3 verify.py list                  # list recent releases with hashes

Env vars:
  GITHUB_REPOSITORY — owner/repo (auto-set in GHA)
  GH_TOKEN          — GitHub token for API access (optional, for private repos)
"""
import hashlib
import json
import os
import sys
import urllib.request


REPO = os.environ.get("GITHUB_REPOSITORY", "wosufemi-netizen/wosufemi")
GH_TOKEN = os.environ.get("GH_TOKEN", "")
TG_API = "https://api.telegram.org/bot{}".format(os.environ.get("BOT_TOKEN", ""))
CHAT_ID = os.environ.get("CHAT_ID", "")


def gh_api(path):
    """Fetch GitHub API."""
    url = "https://api.github.com/repos/{}/{}".format(REPO, path)
    headers = {"Accept": "application/vnd.github+json"}
    if GH_TOKEN:
        headers["Authorization"] = "Bearer {}".format(GH_TOKEN)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print("[gh] API error: {}".format(e))
        return None


def sha256_file(filepath):
    """Compute SHA256 of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def fetch_release_txt(tag):
    """Fetch release .txt metadata."""
    release = gh_api("releases/tags/{}".format(tag))
    if not release:
        return None

    # Find .txt asset
    for asset in release.get("assets", []):
        if asset["name"].endswith(".txt"):
            txt_url = asset["browser_download_url"]
            req = urllib.request.Request(txt_url)
            if GH_TOKEN:
                req.add_header("Authorization", "Bearer {}".format(GH_TOKEN))
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.read().decode()
            except Exception as e:
                print("[fetch] .txt error: {}".format(e))
                return None

    # Fallback: parse release body
    body = release.get("body", "")
    if body:
        return body

    return None


def parse_metadata(txt_content):
    """Parse release .txt metadata."""
    meta = {}
    for line in txt_content.split("\n"):
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
    return meta


def list_releases():
    """List recent releases with hashes."""
    releases = gh_api("releases?per_page=10")
    if not releases:
        print("No releases found")
        return

    lines = ["<b>📋 Recent releases</b>", ""]
    for r in releases[:10]:
        tag = r["tag_name"]
        title = r.get("title", tag)
        txt_content = fetch_release_txt(tag)
        meta = parse_metadata(txt_content) if txt_content else {}
        sha_orig = meta.get("sha256_orig", "N/A")[:16]
        sha_hevc = meta.get("sha256_hevc", "N/A")[:16]
        size = meta.get("size", "?")
        dur = meta.get("durasi", "?")
        lines.append("• <code>{}</code>".format(tag))
        lines.append("  {} | {} | {}".format(dur, size, title[:30]))
        lines.append("  🔒 <code>{}</code>...".format(sha_orig))
        if sha_hevc != "N/A":
            lines.append("  🔒 <code>{}</code>... (HEVC)".format(sha_hevc))
        lines.append("")

    tg_send("\n".join(lines))


def verify_release(tag, local_file=None):
    """Verify a release's integrity."""
    txt_content = fetch_release_txt(tag)
    if not txt_content:
        print("❌ Release {} not found or no .txt asset".format(tag))
        return False

    meta = parse_metadata(txt_content)
    sha_orig = meta.get("sha256_orig", "")
    sha_hevc = meta.get("sha256_hevc", "")

    print("📋 Release: {}".format(tag))
    print("  File: {}".format(meta.get("file", "?")))
    print("  Size: {}".format(meta.get("size", "?")))
    print("  Durasi: {}".format(meta.get("durasi", "?")))
    print("  Resolusi: {}".format(meta.get("resolusi", "?")))
    print("  Codec: {}".format(meta.get("codec", "?")))
    print("  Bitrate: {}".format(meta.get("bitrate", "?")))
    print("  SHA256 (orig): {}".format(sha_orig or "N/A"))
    print("  SHA256 (HEVC): {}".format(sha_hevc or "N/A"))

    if local_file:
        if not os.path.isfile(local_file):
            print("❌ File not found: {}".format(local_file))
            return False

        local_hash = sha256_file(local_file)
        print("\n🔒 Local file SHA256: {}".format(local_hash))

        if local_hash == sha_orig:
            print("✅ MATCH — file integrity verified (original)")
            return True
        elif local_hash == sha_hevc:
            print("✅ MATCH — file integrity verified (HEVC)")
            return True
        else:
            print("❌ MISMATCH — file may be corrupted or different version")
            print("  Expected orig: {}".format(sha_orig))
            print("  Expected HEVC: {}".format(sha_hevc))
            print("  Got:           {}".format(local_hash))
            return False

    return True


def tg_send(text):
    """Send message to Telegram."""
    if not TG_API or not CHAT_ID:
        return
    data = json.dumps({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(
        TG_API + "/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=30)
    except Exception as e:
        print("[tg] send gagal: {}".format(e))


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  verify.py <release_tag>         — show release metadata + hashes")
        print("  verify.py <release_tag> <file>  — verify local file against release hash")
        print("  verify.py list                  — list recent releases with hashes")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "list":
        list_releases()
    elif len(sys.argv) >= 3:
        ok = verify_release(arg, sys.argv[2])
        sys.exit(0 if ok else 1)
    else:
        ok = verify_release(arg)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
