/**
 * TimeStitch Transcript Worker
 *
 * Fetches YouTube transcripts from Cloudflare's edge IPs, bypassing
 * YouTube's datacenter IP blocks that affect Vercel/Railway/AWS etc.
 *
 * GET /transcript?video_id=<VIDEO_ID>
 * Returns: [{ text, start, duration }, ...]  (same shape as youtube-transcript-api)
 */

const BROWSER_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
  "Accept-Language": "en-US,en;q=0.9",
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
};

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (url.pathname === "/") return json({ status: "ok" });

    if (url.pathname === "/debug") {
      const videoId = url.searchParams.get("video_id") ?? "dQw4w9WgXcQ";
      const res = await fetch(`https://www.youtube.com/watch?v=${videoId}`, { headers: BROWSER_HEADERS });
      const body = await res.text();
      return json({
        status: res.status,
        headers: Object.fromEntries(res.headers.entries()),
        body_length: body.length,
        body_preview: body.slice(0, 300),
      });
    }

    if (url.pathname !== "/transcript") return json({ error: "Not found" }, 404);

    const videoId = url.searchParams.get("video_id");
    if (!videoId) return json({ error: "video_id query param is required" }, 400);

    try {
      const transcript = await fetchTranscript(videoId);
      return json(transcript);
    } catch (e) {
      return json({ error: e.message }, e.status ?? 500);
    }
  },
};

async function fetchTranscript(videoId) {
  // Step 1 — Fetch the YouTube watch page.
  // This gives us the signed caption track URLs embedded in ytInitialPlayerResponse.
  // Cloudflare's HTTP client has a browser-like TLS fingerprint, so this isn't blocked.
  const watchRes = await fetch(`https://www.youtube.com/watch?v=${videoId}`, {
    headers: BROWSER_HEADERS,
  });

  if (!watchRes.ok) throw httpError(watchRes.status, `Watch page fetch failed: ${watchRes.status}`);

  // Capture session cookies — required for the subsequent timedtext fetch
  const cookies = (watchRes.headers.getSetCookie?.() ?? [])
    .map(c => c.split(";")[0])
    .join("; ");

  const html = await watchRes.text();

  // Step 2 — Extract ytInitialPlayerResponse from the HTML.
  // YouTube embeds the full player config as a JS variable in the page.
  // We walk forward matching braces to safely extract the JSON without regex.
  const marker = "ytInitialPlayerResponse = ";
  const markerIdx = html.indexOf(marker);
  if (markerIdx === -1) throw httpError(500, "ytInitialPlayerResponse not found in watch page");

  let depth = 0, i = markerIdx + marker.length;
  for (; i < html.length; i++) {
    if (html[i] === "{") depth++;
    else if (html[i] === "}") { if (--depth === 0) break; }
  }

  const playerData = JSON.parse(html.slice(markerIdx + marker.length, i + 1));
  const tracks = playerData?.captions?.playerCaptionsTracklistRenderer?.captionTracks;

  if (!tracks?.length) throw httpError(404, "No captions available for this video");

  // Step 3 — Pick the best English track.
  // Prefer manual captions over auto-generated ("asr") ones for better quality.
  const track =
    tracks.find(t => (t.languageCode === "en" || t.languageCode === "en-US") && t.kind !== "asr") ??
    tracks.find(t => t.languageCode === "en" || t.languageCode === "en-US") ??
    tracks[0];

  // Step 4 — Fetch the caption XML.
  // The baseUrl is a signed timedtext URL. We include cookies from the watch page
  // and the Referer header to satisfy YouTube's same-origin expectations.
  const captionRes = await fetch(track.baseUrl, {
    headers: {
      ...BROWSER_HEADERS,
      "Referer": `https://www.youtube.com/watch?v=${videoId}`,
      ...(cookies ? { "Cookie": cookies } : {}),
    },
  });

  if (!captionRes.ok) throw httpError(captionRes.status, `Caption fetch failed: ${captionRes.status}`);

  const xml = await captionRes.text();
  if (!xml.trim()) throw httpError(500, "Caption response was empty");

  // Step 5 — Parse XML into [{text, start, duration}].
  // The timedtext XML format: <text start="1.23" dur="2.00">Hello world</text>
  const segments = [];
  const re = /<text start="([^"]+)" dur="([^"]+)"[^>]*>([\s\S]*?)<\/text>/g;
  let m;
  while ((m = re.exec(xml)) !== null) {
    const text = m[3]
      .replace(/&#39;/g, "'")
      .replace(/&amp;/g, "&")
      .replace(/&quot;/g, '"')
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/\n/g, " ")
      .trim();
    if (text) segments.push({ text, start: parseFloat(m[1]), duration: parseFloat(m[2]) });
  }

  return segments;
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
  });
}

function httpError(status, message) {
  const e = new Error(message);
  e.status = status;
  return e;
}
