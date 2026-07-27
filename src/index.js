/**
 * wosufemi Worker — Telegram bot → GitHub Actions repository_dispatch
 * Event: record-request
 * Payload: m3u8_url, duration, chat_id, human_duration, duration_label, referer
 */
const ALLOWED_USER_ID = 2027652715;
const KNOWN_CHANNELS = ["trans7", "transtv", "cnn", "moji", "cnbc"];

export default {
  async scheduled(event, env, ctx) {
    // CF Cron Trigger — jalan tepat waktu (beda dg GHA cron yang sering delay)
    // 58 11,12,13 * * * UTC = 18:58, 19:58, 20:58 WIB
    const url = `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/actions/workflows/wosufemi.yml/dispatches`;
    const payload = JSON.stringify({ ref: "master" });
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_TOKEN}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "wosufemi-worker",
          "Content-Type": "application/json",
        },
        body: payload,
      });
      console.log(`[cron] wosufemi dispatch → HTTP ${res.status}`);
    } catch (e) {
      console.error(`[cron] dispatch error: ${e.message}`);
    }
  },

  async fetch(request, env, ctx) {
    if (request.method === "GET") {
      return new Response("OK");
    }
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    let rawBody = "";
    try {
      rawBody = await request.text();
    } catch {
      return new Response("Bad Request", { status: 400 });
    }

    let update;
    try {
      update = JSON.parse(rawBody || "{}");
    } catch {
      return new Response("Invalid JSON", { status: 400 });
    }

    // Always ACK Telegram quickly; do work in waitUntil when needed.
    try {
      const msg = update.message || update.edited_message;
      if (!msg || !msg.chat) {
        return new Response("OK");
      }

      const chatId = msg.chat.id;
      const fromId = msg.from && msg.from.id;
      const text = (msg.text || "").trim();

      if (fromId !== ALLOWED_USER_ID) {
        ctx.waitUntil(tgSend(env, chatId, "⛔ Unauthorized."));
        return new Response("OK");
      }

      if (!text) {
        return new Response("OK");
      }

      if (text === "/start" || text.startsWith("/start ")) {
        ctx.waitUntil(
          tgSend(
            env,
            chatId,
            [
              "🎬 <b>wosufemi / wosufemi-netizen</b>",
              "",
              "Perintah:",
              "• <code>/trans7 [durasi]</code>",
              "  Rekam Trans7 live (auto generate token)",
              "  contoh: <code>/trans7 5m</code> atau <code>/trans7 300</code>",
              "• <code>/record &lt;m3u8_url&gt; [detik]</code>",
              "  contoh: <code>/record https://.../index.m3u8 300</code>",
              "• <code>/status</code> — info singkat",
              "• <code>/cancel</code> — (info) batalkan lewat Actions UI",
              "",
              "Capture auto: workflow <code>wosufemi</code> (cron UTC 58 11-13).",
            ].join("\n")
          )
        );
        return new Response("OK");
      }

      if (text === "/status" || text.startsWith("/status ")) {
        ctx.waitUntil(
          tgSend(
            env,
            chatId,
            [
              "📊 <b>Status</b>",
              `Repo: <code>${env.GH_OWNER}/${env.GH_REPO}</code>`,
              "Record: Actions workflow <code>wosufemi-netizen</code>",
              "Capture: Actions workflow <code>wosufemi</code>",
              "Cek run: GitHub → Actions.",
            ].join("\n")
          )
        );
        return new Response("OK");
      }

      if (text === "/cancel" || text.startsWith("/cancel ")) {
        ctx.waitUntil(
          tgSend(
            env,
            chatId,
            "ℹ️ Cancel job lewat GitHub Actions (Cancel workflow). Bot tidak kill runner remote."
          )
        );
        return new Response("OK");
      }

      if (text.startsWith("/trans7") || text.startsWith("/transtv") || text.startsWith("/cnn")) {
        ctx.waitUntil(handleChannel(env, chatId, text));
        return new Response("OK");
      }

      if (text.startsWith("/verify")) {
        ctx.waitUntil(handleVerify(env, chatId, text));
        return new Response("OK");
      }
      if (text.startsWith("/record")) {
        ctx.waitUntil(handleRecord(env, chatId, text));
        return new Response("OK");
      }

      ctx.waitUntil(
        tgSend(env, chatId, "Perintah tidak dikenal. Kirim /start untuk bantuan.")
      );
      return new Response("OK");
    } catch (err) {
      // Never 5xx to Telegram if we can avoid it — drops deliveries.
      return new Response("OK");
    }
  },
};

async function handleRecord(env, chatId, text) {
  // /record <url> [duration_seconds]
  const parts = text.split(/\s+/).filter(Boolean);
  if (parts.length < 2) {
    await tgSend(
      env,
      chatId,
      "Format: <code>/record &lt;m3u8_url&gt; [detik]</code>\nContoh: <code>/record https://example.com/live.m3u8 300</code>"
    );
    return;
  }

  const m3u8 = parts[1];
  if (!/^https?:\/\//i.test(m3u8) || !m3u8.includes(".m3u8")) {
    await tgSend(env, chatId, "❌ URL harus http(s) dan mengandung <code>.m3u8</code>.");
    return;
  }

  let durationSec = 300;
  if (parts[2]) {
    const n = parseDuration(parts[2]);
    if (!n || n < 30 || n > 6 * 3600) {
      await tgSend(
        env,
        chatId,
        "❌ Durasi invalid. Pakai detik (30–21600) atau format 5m / 1h30m."
      );
      return;
    }
    durationSec = n;
  }

  const human = humanDuration(durationSec);
  const durationLabel = labelDuration(durationSec);
  const referer = guessReferer(m3u8);

  if (!env.BOT_TOKEN || !env.GH_TOKEN || !env.GH_OWNER || !env.GH_REPO) {
    await tgSend(
      env,
      chatId,
      "❌ Worker secrets belum lengkap (BOT_TOKEN / GH_TOKEN / GH_OWNER / GH_REPO)."
    );
    return;
  }

  await tgSend(
    env,
    chatId,
    [
      "⏳ <b>Dispatch record</b>",
      `URL: <code>${escapeHtml(m3u8.slice(0, 180))}${m3u8.length > 180 ? "…" : ""}</code>`,
      `Durasi: <b>${human}</b> (${durationSec}s)`,
      `Repo: <code>${env.GH_OWNER}/${env.GH_REPO}</code>`,
    ].join("\n")
  );

  const payload = {
    event_type: "record-request",
    client_payload: {
      m3u8_url: m3u8,
      duration: String(durationSec),
      chat_id: String(chatId),
      human_duration: human,
      duration_label: durationLabel,
      referer: referer,
    },
  };

  try {
    const res = await fetch(
      `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_TOKEN}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "wosufemi-worker",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      }
    );

    if (res.status === 204 || res.ok) {
      await tgSend(
        env,
        chatId,
        "✅ Request dikirim ke GitHub Actions. Pantau progress di chat / Actions."
      );
    } else {
      const body = await res.text();
      await tgSend(
        env,
        chatId,
        `❌ GitHub dispatch gagal HTTP ${res.status}\n<pre>${escapeHtml(body.slice(0, 500))}</pre>`
      );
    }
  } catch (e) {
    await tgSend(env, chatId, `❌ Dispatch error: ${escapeHtml(String(e.message || e))}`);
  }
}

async function handleChannel(env, chatId, text) {
  // /trans7 [duration] — default 5m (300s)
  const parts = text.split(/\s+/).filter(Boolean);
  let durationSec = 300;
  if (parts[1]) {
    const n = parseDuration(parts[1]);
    if (!n || n < 30 || n > 6 * 3600) {
      await tgSend(
        env,
        chatId,
        "❌ Durasi invalid. Pakai detik (30–21600) atau format 5m / 1h30m."
      );
      return;
    }
    durationSec = n;
  }

  const human = humanDuration(durationSec);

  if (!env.BOT_TOKEN || !env.GH_TOKEN || !env.GH_OWNER || !env.GH_REPO) {
    await tgSend(env, chatId, "❌ Worker secrets belum lengkap.");
    return;
  }

  await tgSend(
    env,
    chatId,
    [
      "⏳ <b>Dispatch Trans7 record</b>",
      `Durasi: <b>${human}</b> (${durationSec}s)`,
      `Repo: <code>${env.GH_OWNER}/${env.GH_REPO}</code>`,
      "",
      "Token akan di-generate otomatis di GHA.",
    ].join("\n")
  );

  const payload = {
    event_type: "record-trans7",
    client_payload: {
      duration: String(durationSec),
      stream_type: channel,
      chat_id: String(chatId),
    },
  };

  try {
    const res = await fetch(
      `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_TOKEN}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "wosufemi-worker",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      }
    );

    if (res.status === 204 || res.ok) {
      await tgSend(
        env,
        chatId,
        `✅ Trans7 dispatch berhasil. Rekaman <b>${human}</b> dimulai. Pantau di chat ini.`
      );
    } else {
      const body = await res.text();
      await tgSend(
        env,
        chatId,
        `❌ GitHub dispatch gagal HTTP ${res.status}\n<pre>${escapeHtml(body.slice(0, 500))}</pre>`
      );
    }
  } catch (e) {
    await tgSend(env, chatId, `❌ Dispatch error: ${escapeHtml(String(e.message || e))}`);
  }
}

function parseDuration(raw) {
  const s = String(raw).trim().toLowerCase();
  if (/^\d+$/.test(s)) return parseInt(s, 10);
  // 1h30m / 90m / 5m / 1h
  let total = 0;
  const re = /(\d+)\s*(h|m|s)/g;
  let m;
  let matched = false;
  while ((m = re.exec(s))) {
    matched = true;
    const n = parseInt(m[1], 10);
    if (m[2] === "h") total += n * 3600;
    else if (m[2] === "m") total += n * 60;
    else total += n;
  }
  return matched ? total : 0;
}

function humanDuration(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const parts = [];
  if (h) parts.push(`${h}h`);
  if (m) parts.push(`${m}m`);
  if (s && !h) parts.push(`${s}s`);
  if (!parts.length) parts.push("0s");
  return parts.join(" ");
}

function labelDuration(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h && m) return `${h}h${m}m`;
  if (h) return `${h}h`;
  if (m) return `${m}m`;
  return `${sec}s`;
}

function guessReferer(url) {
  try {
    const u = new URL(url);
    return `${u.protocol}//${u.host}/`;
  } catch {
    return "";
  }
}

async function tgSend(env, chatId, html) {
  if (!env.BOT_TOKEN) return;
  const body = new URLSearchParams({
    chat_id: String(chatId),
    text: html,
    parse_mode: "HTML",
    disable_web_page_preview: "true",
  });
  await fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
async function handleVerify(env, chatId, text) {
  const parts = text.split(/s+/).filter(Boolean);
  if (parts.length < 2) {
    await tgSend(env, chatId, "Format: <code>/verify &lt;release_tag&gt;</code>
Atau: <code>/verify list</code> untuk daftar rekaman + hash");
    return;
  }

  const arg = parts[1].toLowerCase();

  if (arg === "list") {
    await handleVerifyList(env, chatId);
    return;
  }

  // Fetch release .txt and show metadata + hashes
  const tag = parts[1];
  try {
    const relRes = await fetch(
      `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/releases/tags/${tag}`,
      { headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json" } }
    );
    if (!relRes.ok) {
      await tgSend(env, chatId, `❌ Release <code>${escapeHtml(tag)}</code> tidak ditemukan.`);
      return;
    }
    const rel = await relRes.json();

    // Find .txt asset
    let txtContent = "";
    for (const asset of rel.assets || []) {
      if (asset.name.endsWith(".txt")) {
        const txtRes = await fetch(asset.browser_download_url, {
          headers: { Authorization: `Bearer ${env.GH_TOKEN}` }
        });
        txtContent = await txtRes.text();
        break;
      }
    }

    if (!txtContent) {
      await tgSend(env, chatId, `❌ Tidak ada .txt di release <code>${escapeHtml(tag)}</code>`);
      return;
    }

    // Parse metadata
    const meta = {};
    for (const line of txtContent.split("
")) {
      const trimmed = line.trim();
      if (trimmed && !trimmed.startsWith("#") && trimmed.includes(":")) {
        const [k, ...v] = trimmed.split(":");
        meta[k.trim()] = v.join(":").trim();
      }
    }

    const shaOrig = meta.sha256_orig || "N/A";
    const shaHevc = meta.sha256_hevc || "N/A";

    const msg = [
      "🔒 <b>Verifikasi Integritas</b>",
      "",
      `📁 File: <code>${escapeHtml(meta.file || "?")}</code>`,
      `📦 Size: ${meta.size || "?"}`,
      `⏱ Durasi: ${meta.durasi || "?"}`,
      `🖥 Resolusi: ${meta.resolusi || "?"}`,
      `🎞 Codec: ${meta.codec || "?"}`,
      `📶 Bitrate: ${meta.bitrate || "?"}`,
      "",
      `🔑 SHA256 (orig): <code>${shaOrig.substring(0, 32)}</code>`,
      shaOrig.length > 32 ? `<code>${shaOrig.substring(32)}</code>` : "",
      shaHevc !== "N/A" ? `🔑 SHA256 (HEVC): <code>${shaHevc.substring(0, 32)}</code>` : "",
      shaHevc !== "N/A" && shaHevc.length > 32 ? `<code>${shaHevc.substring(32)}</code>` : "",
      "",
      "💡 Bandingkan hash di atas dengan file yang kamu download.",
    ].filter(Boolean).join("
");

    await tgSend(env, chatId, msg);
  } catch (e) {
    await tgSend(env, chatId, `❌ Error: ${escapeHtml(String(e.message || e))}`);
  }
}

async function handleVerifyList(env, chatId) {
  try {
    const res = await fetch(
      `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/releases?per_page=5`,
      { headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json" } }
    );
    const releases = await res.json();
    if (!releases.length) {
      await tgSend(env, chatId, "📭 Belum ada release.");
      return;
    }

    const lines = ["<b>📋 Rekaman terakhir</b>", ""];
    for (const r of releases) {
      lines.push(`• <code>${escapeHtml(r.tag_name)}</code>`);
      lines.push(`  ${escapeHtml(r.title || r.tag_name)}`);
      lines.push("");
    }
    lines.push("Gunakan: <code>/verify &lt;tag&gt;</code> untuk lihat hash");
    await tgSend(env, chatId, lines.join("
"));
  } catch (e) {
    await tgSend(env, chatId, `❌ Error: ${escapeHtml(String(e.message || e))}`);
  }
}
}
