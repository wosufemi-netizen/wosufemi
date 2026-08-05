#!/usr/bin/env python3
"""rec_progress.py - Record HLS with ffmpeg + live Telegram progress bar.

Env vars:
  BOT_TOKEN, CHAT_ID/TELEGRAM_CHAT_ID — Telegram bot
  DURATION — total recording seconds
  M3U8_URL — primary URL (master playlist)
  CHUNK_URL — fallback URL (chunklist, optional)
  HEADERS — ffmpeg HTTP headers (optional)
  PROGRESS_FILE — ffmpeg -progress temp file (default /tmp/rec_progress)
"""
import json, os, subprocess, sys, threading, time, urllib.request
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")
DURATION = int(os.environ.get("DURATION", "300"))
M3U8_URL = os.environ.get("M3U8_URL", "")
CHUNK_URL = os.environ.get("CHUNK_URL", "")
PROGRESS_FILE = os.environ.get("PROGRESS_FILE", "/tmp/rec_progress")
WIB = timezone(timedelta(hours=7))
TG_API = "https://api.telegram.org/bot{}".format(BOT_TOKEN)
progress_msg_id = None


def tg_send(text):
    if not BOT_TOKEN or not CHAT_ID:
        return None
    data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                        "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(TG_API + "/sendMessage", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()).get("result", {}).get("message_id")
    except Exception as e:
        print("[tg] send gagal: {}".format(e), flush=True)
        return None


def tg_edit(text):
    global progress_msg_id
    if not progress_msg_id or not BOT_TOKEN or not CHAT_ID:
        return
    data = json.dumps({"chat_id": CHAT_ID, "message_id": progress_msg_id,
                        "text": text, "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(TG_API + "/editMessageText", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30)
    except Exception:
        pass


def build_bar(pct):
    filled = pct // 5  # 20 blocks total
    return "\u2588" * filled + "\u2591" * (20 - filled)


def fmt_time(sec):
    h, m, s = int(sec) // 3600, (int(sec) % 3600) // 60, int(sec) % 60
    return "{:02d}:{:02d}:{:02d}".format(h, m, s)


def fmt_remaining(sec):
    """Human-readable remaining time: ~26m, ~1h5m, ~45s"""
    sec = int(sec)
    if sec <= 0:
        return "sebentar"
    h, m = sec // 3600, (sec % 3600) // 60
    if h > 0:
        return "~{}h{}m".format(h, m) if m else "~{}h".format(h)
    if m > 0:
        return "~{}m".format(m)
    return "~{}s".format(sec)


def duration_label(sec):
    h, m = sec // 3600, (sec % 3600) // 60
    if h and m:
        return "{}h{}m".format(h, m)
    if h:
        return "{}h".format(h)
    if m:
        return "{}m".format(m)
    return "{}s".format(sec)


dl = duration_label(DURATION)
now = time.strftime("%Y-%m-%d_%H-%M-%S")
OUT = "Wosufemi-Asset-{}-{}.mp4".format(now, dl)
HEADERS = os.environ.get("HEADERS",
    "Referer: https://20.detik.com/\r\nOrigin: https://20.detik.com")


def build_ffmpeg_cmd(url, output):
    return ["ffmpeg", "-y",
        "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "-headers", HEADERS, "-i", url, "-t", str(DURATION),
        "-c", "copy", "-movflags", "+faststart",
        "-progress", PROGRESS_FILE, output]


def build_status_msg(pct, elapsed=0):
    """Build the progress message matching user's preferred format."""
    now_wib = datetime.now(WIB).strftime("%H:%M")
    if pct < 100 and elapsed > 0:
        remaining = max(DURATION - elapsed, 0)
        finish_time = (datetime.now(WIB) + timedelta(seconds=remaining)).strftime("%H:%M")
        lines = [
            "\U0001f504 <b>Rekam</b>",
            "",
            "{} {}%".format(build_bar(pct), pct),
            "\u23f1 Sisa {} \u00b7 selesai ~{} WIB".format(fmt_remaining(remaining), finish_time),
        ]
    elif pct >= 100:
        lines = [
            "\u2705 <b>Rekaman selesai!</b>",
            "",
            "{} 100%".format(build_bar(100)),
            "\u23f1 Selesai {} WIB".format(now_wib),
        ]
    else:
        lines = [
            "\U0001f504 <b>Rekam</b>",
            "",
            "{} 0%".format(build_bar(0)),
            "\u23f1 Memulai...",
        ]
    return "\n".join(lines)


ffmpeg_done = threading.Event()
rec_start = 0.0  # Set by run_ffmpeg; wall-clock start for progress (out_time_us is absolute PTS)


def monitor_progress():
    global progress_msg_id
    # Send initial message
    progress_msg_id = tg_send(build_status_msg(0))
    last_pos = 0
    last_pct = -1
    last_update = time.time()

    while not ffmpeg_done.is_set():
        ffmpeg_done.wait(timeout=3)
        try:
            if not os.path.exists(PROGRESS_FILE):
                continue
            with open(PROGRESS_FILE, "r") as f:
                f.seek(last_pos)
                data = f.read()
                last_pos = f.tell()
        except Exception:
            continue
        if not data:
            continue

        # Use wall-clock elapsed time — out_time_us from ffmpeg -progress is
        # absolute PTS for live HLS (stream may run hours), not recording duration.
        if rec_start <= 0:
            continue
        current_sec = time.time() - rec_start
        pct = min(int((current_sec / DURATION) * 100), 100) if DURATION > 0 else 0
        now_t = time.time()

        # Update every 10%, minimum 60s gap
        if pct >= last_pct + 10 and now_t - last_update >= 60 and current_sec > 0:
            last_pct = (pct // 10) * 10
            last_update = now_t
            tg_edit(build_status_msg(last_pct, int(current_sec)))
            print("[progress] {}% ({}/{})".format(last_pct, fmt_time(current_sec), fmt_time(DURATION)), flush=True)


def run_ffmpeg(url, label):
    global rec_start
    cmd = build_ffmpeg_cmd(url, OUT)
    print("[ffmpeg] {} - {}".format(label, " ".join(cmd[:8])), flush=True)
    try:
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
    except Exception:
        pass
    rec_start = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

    def drain():
        for l in proc.stderr:
            s = l.strip()
            if s and "=" not in s.split(":", 1)[0]:
                print("[ffmpeg] {}".format(s), file=sys.stderr, flush=True)

    et = threading.Thread(target=drain, daemon=True)
    et.start()
    proc.wait()
    et.join(timeout=5)
    return proc.returncode == 0 and os.path.isfile(OUT) and os.path.getsize(OUT) > 0


def main():
    if not M3U8_URL:
        print("M3U8_URL not set", file=sys.stderr)
        sys.exit(1)

    mon = threading.Thread(target=monitor_progress, daemon=True)
    mon.start()

    success = False
    try:
        success = run_ffmpeg(M3U8_URL, "primary")
        if not success and CHUNK_URL:
            print("[ffmpeg] Retrying with chunklist...", flush=True)
            tg_edit("\U0001f504 <b>Rekam</b>\n\n\u26a0\ufe0f Retry chunklist...")
            success = run_ffmpeg(CHUNK_URL, "chunklist")
    finally:
        ffmpeg_done.set()
        mon.join(timeout=10)

    gh_out = os.environ.get("GITHUB_OUTPUT", "")
    gh_env = os.environ.get("GITHUB_ENV", "")

    if success and os.path.isfile(OUT) and os.path.getsize(OUT) > 0:
        fsize = os.path.getsize(OUT)
        size_str = "{:.1f} MB".format(fsize / (1024 * 1024)) if fsize > 1024 * 1024 else "{:.0f} kB".format(fsize / 1024)
        print("\u2705 Recorded: {} ({})".format(OUT, size_str), flush=True)
        if gh_out:
            with open(gh_out, "a") as f:
                f.write("recorded=true\noutput={}\n".format(OUT))
        if gh_env:
            with open(gh_env, "a") as f:
                f.write("ORIG_BYTES={}\nFILE_SIZE={}\n".format(fsize, size_str))
        tg_edit("\u2705 <b>Rekaman selesai!</b>\n\n{}\u23f1 Durasi: {}\n\U0001f4c1 <code>{}</code>\n\n\u23f3 Proses selanjutnya...".format(
            "\U0001f4e6 Size: {}\n".format(size_str) if size_str else "",
            fmt_time(DURATION), OUT))
    else:
        if gh_out:
            with open(gh_out, "a") as f:
                f.write("recorded=false\noutput=\n")
        tg_edit("\u274c <b>Rekaman gagal!</b>\n\n\U0001f517 Cek log GitHub Actions.")
        sys.exit(1)


if __name__ == "__main__":
    main()
