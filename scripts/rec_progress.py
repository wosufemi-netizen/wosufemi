#!/usr/bin/env python3
"""rec_progress.py - Record HLS with ffmpeg + live Telegram progress."""
import json, os, subprocess, sys, threading, time, urllib.request

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")
DURATION = int(os.environ.get("DURATION", "300"))
M3U8_URL = os.environ.get("M3U8_URL", "")
CHUNK_URL = os.environ.get("CHUNK_URL", "")
PROGRESS_FILE = os.environ.get("PROGRESS_FILE", "/tmp/rec_progress")
TG_API = "https://api.telegram.org/bot{}".format(BOT_TOKEN)
progress_msg_id = None
ffmpeg_done = threading.Event()

def tg_send(text):
    if not BOT_TOKEN or not CHAT_ID: return None
    data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(TG_API + "/sendMessage", data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode()).get("result", {}).get("message_id")
    except Exception as e:
        print("[tg] send gagal: {}".format(e), flush=True); return None

def tg_edit(text):
    global progress_msg_id
    if not progress_msg_id or not BOT_TOKEN or not CHAT_ID: return
    data = json.dumps({"chat_id": CHAT_ID, "message_id": progress_msg_id, "text": text, "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(TG_API + "/editMessageText", data=data, headers={"Content-Type": "application/json"})
    try: urllib.request.urlopen(req, timeout=30)
    except: pass

def build_bar(pct):
    return "\u2588" * (pct // 10) + "\u2591" * (10 - pct // 10)

def fmt_time(sec):
    h, m, s = int(sec)//3600, (int(sec)%3600)//60, int(sec)%60
    return "{:02d}:{:02d}:{:02d}".format(h, m, s)

def duration_label(sec):
    h, m = sec//3600, (sec%3600)//60
    if h and m: return "{}h{}m".format(h, m)
    if h: return "{}h".format(h)
    if m: return "{}m".format(m)
    return "{}s".format(sec)

def parse_size_kb(text):
    t = text.strip()
    if t.endswith("kB"):
        try: return int(t[:-2]) * 1024
        except: pass
    return 0

dl = duration_label(DURATION)
now = time.strftime("%Y-%m-%d_%H-%M-%S")
OUT = "Wosufemi-Asset-{}-{}.mp4".format(now, dl)
HEADERS = os.environ.get("HEADERS", "Referer: https://20.detik.com/\r\nOrigin: https://20.detik.com")

def build_ffmpeg_cmd(url, output):
    return ["ffmpeg", "-y",
        "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "-headers", HEADERS, "-i", url, "-t", str(DURATION), "-c", "copy",
        "-movflags", "+faststart", "-progress", PROGRESS_FILE, output]

def monitor_progress():
    global progress_msg_id
    progress_msg_id = tg_send("\u23fa <b>Merekam</b>\n\n{} 0%\n\u23f1 00:00:00 / {}\n\U0001f4c1 <code>{}</code>".format(build_bar(0), fmt_time(DURATION), OUT))
    last_pos = 0; last_pct = -1; last_update = time.time()
    while not ffmpeg_done.is_set():
        ffmpeg_done.wait(timeout=2)
        try:
            if not os.path.exists(PROGRESS_FILE): continue
            with open(PROGRESS_FILE, "r") as f:
                f.seek(last_pos); data = f.read(); last_pos = f.tell()
        except: continue
        if not data: continue
        current_us = 0; current_size = 0
        for line in data.strip().split("\n"):
            line = line.strip()
            if line.startswith("out_time_us="):
                try: current_us = int(line.split("=", 1)[1])
                except: pass
            elif line.startswith("out_time_ms="):
                try: current_us = int(line.split("=", 1)[1]) * 1000
                except: pass
            elif line.startswith("size="):
                current_size = parse_size_kb(line.split("=", 1)[1])
        current_sec = current_us / 1_000_000
        pct = min(int((current_sec / DURATION) * 100), 100) if DURATION > 0 else 0
        now_t = time.time()
        if pct >= last_pct + 10 and now_t - last_update >= 60 and current_sec > 0:
            last_pct = (pct // 10) * 10; last_update = now_t
            size_str = "{:.1f} MB".format(current_size/(1024*1024)) if current_size > 1024*1024 else ""
            lines = ["\u23fa <b>Merekam</b>", "", "{} {}%".format(build_bar(last_pct), last_pct),
                     "\u23f1 {} / {}".format(fmt_time(current_sec), fmt_time(DURATION))]
            if size_str: lines.append("\U0001f4e6 {}".format(size_str))
            lines.append("\U0001f4c1 <code>{}</code>".format(OUT))
            tg_edit("\n".join(lines))
            print("[progress] {}%".format(last_pct), flush=True)

def run_ffmpeg(url, label):
    cmd = build_ffmpeg_cmd(url, OUT)
    print("[ffmpeg] {} - {}".format(label, " ".join(cmd[:8])), flush=True)
    try:
        if os.path.exists(PROGRESS_FILE): os.remove(PROGRESS_FILE)
    except: pass
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    def drain():
        for l in proc.stderr:
            s = l.strip()
            if s and "=" not in s.split(":",1)[0]:
                print("[ffmpeg] {}".format(s), file=sys.stderr, flush=True)
    et = threading.Thread(target=drain, daemon=True); et.start(); proc.wait(); et.join(timeout=5)
    return proc.returncode == 0 and os.path.isfile(OUT) and os.path.getsize(OUT) > 0

def main():
    if not M3U8_URL:
        print("M3U8_URL not set", file=sys.stderr); sys.exit(1)
    mon = threading.Thread(target=monitor_progress, daemon=True); mon.start()
    success = False
    try:
        success = run_ffmpeg(M3U8_URL, "primary")
        if not success and CHUNK_URL:
            print("[ffmpeg] Retrying with chunklist...", flush=True)
            tg_edit("\u23fa <b>Merekam</b>\n\n\u26a0\ufe0f Retry chunklist...\n\U0001f4c1 <code>{}</code>".format(OUT))
            success = run_ffmpeg(CHUNK_URL, "chunklist")
    finally:
        ffmpeg_done.set(); mon.join(timeout=10)
    gh_out = os.environ.get("GITHUB_OUTPUT", ""); gh_env = os.environ.get("GITHUB_ENV", "")
    if success and os.path.isfile(OUT) and os.path.getsize(OUT) > 0:
        fsize = os.path.getsize(OUT)
        size_str = "{:.1f} MB".format(fsize/(1024*1024)) if fsize > 1024*1024 else "{:.0f} kB".format(fsize/1024)
        print("\u2705 Recorded: {} ({})".format(OUT, size_str), flush=True)
        if gh_out:
            with open(gh_out, "a") as f: f.write("recorded=true\noutput={}\n".format(OUT))
        if gh_env:
            with open(gh_env, "a") as f: f.write("ORIG_BYTES={}\nFILE_SIZE={}\n".format(fsize, size_str))
        tg_edit("\u2705 <b>Rekaman selesai!</b>\n\n\U0001f4e6 Size: {}\n\u23f1 Durasi: {}\n\U0001f4c1 <code>{}</code>\n\n\u23f3 Proses selanjutnya...".format(size_str, fmt_time(DURATION), OUT))
    else:
        if gh_out:
            with open(gh_out, "a") as f: f.write("recorded=false\noutput=\n")
        tg_edit("\u274c <b>Rekaman gagal!</b>\n\n\U0001f517 Cek log GitHub Actions.")
        sys.exit(1)

if __name__ == "__main__":
    main()
