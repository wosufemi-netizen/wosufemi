# wosufemi

Public automation for live HLS capture + record pipeline.

## Components

| Piece | Role |
|-------|------|
| GitHub Actions `wosufemi` | Scheduled/manual capture of 720p `.m3u8` |
| GitHub Actions `wosufemi-netizen` | Record live edge, notify Telegram, release tiny `.txt` log |
| Cloudflare Worker `wosufemi` | Telegram bot webhook → `repository_dispatch` |

## Secrets (never commit)

**GitHub Actions**
- `BOT_TOKEN` / `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TG_API_ID` / `TG_API_HASH` (local Bot API for large uploads)

**Worker**
- `BOT_TOKEN`
- `GH_TOKEN` (repo + workflow)
- `GH_OWNER` / `GH_REPO`

## Notes

- Video is delivered to Telegram only; GitHub Releases keep a small `.txt` metadata log.
- Capture labels Telegram messages `FRESH` vs `STALE` via `wosufemi/capture_status.json`.
- Record uses live edge (`-live_start_index -3`), not DVR dump restart.
