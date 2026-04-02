/**
 * TimeStitch Transcript Worker
 *
 * Fetches YouTube transcripts from Cloudflare's edge IPs, bypassing
 * YouTube's datacenter IP blocks that affect Vercel/Railway/AWS etc.
 *
 * GET /transcript?video_id=<VIDEO_ID>
 * Returns: [{ text, start, duration }, ...]  (same shape as youtube-transcript-api)
 */

const INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/player";
const INNERTUBE_CONTEXT = {
  client: {
    clientName: "WEB",
    clientVersion: "2.20240101.00.00",
    hl: "en",
    gl: "US",
  },
};
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36";

export default {
  async fetch(request) {
    const url = new URL(request.url);

    // Health check
    if (url.pathname === "/") {
      return json({ status: "ok" });
    }

    if (url.pathname !== "/transcript") {
      return json({ error: "Not found" }, 404);
    }

    const videoId = url.searchParams.get("video_id");
    if (!videoId) {
      return json({ error: "video_id query param is required" }, 400);
    }

    try {
      const transcript = await fetchTranscript(videoId);
      return json(transcript);
    } catch (e) {
      const status = e.status ?? 500;
      return json({ error: e.message }, status);
    }
  },
};

async function fetchTranscript(videoId) {
  // Step 1 — Ask YouTube's InnerTube API for the player data.
  // InnerTube is YouTube's internal JSON API used by the web player itself.
  // It returns caption track URLs as part of the player response.
  const playerRes = await fetch(INNERTUBE_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "User-Agent": USER_AGENT,
    },
    body: JSON.stringify({
      context: INNERTUBE_CONTEXT,
      videoId,
    }),
  });

  if (!playerRes.ok) {
    throw httpError(playerRes.status, `InnerTube player API returned ${playerRes.status}`);
  }

  const playerData = await playerRes.json();
  const tracks =
    playerData?.captions?.playerCaptionsTracklistRenderer?.captionTracks;

  if (!tracks || tracks.length === 0) {
    throw httpError(404, "No captions available for this video");
  }

  // Step 2 — Pick the best English track (manual > auto-generated).
  // captionTracks entries have a `kind` field: "asr" = auto-generated.
  // We prefer manual captions but fall back to auto-generated if needed.
  const manualEn = tracks.find(
    (t) => (t.languageCode === "en" || t.languageCode === "en-US") && t.kind !== "asr"
  );
  const autoEn = tracks.find(
    (t) => (t.languageCode === "en" || t.languageCode === "en-US") && t.kind === "asr"
  );
  const track = manualEn ?? autoEn ?? tracks[0];

  // Step 3 — Fetch the transcript in JSON format.
  // YouTube's timedtext endpoint serves captions as XML by default.
  // Appending &fmt=json3 gets a cleaner JSON response with timed events.
  const captionUrl = `${track.baseUrl}&fmt=json3`;
  const captionRes = await fetch(captionUrl, {
    headers: { "User-Agent": USER_AGENT },
  });

  if (!captionRes.ok) {
    throw httpError(captionRes.status, `Caption fetch failed with ${captionRes.status}`);
  }

  const captionData = await captionRes.json();

  // Step 4 — Normalise into [{text, start, duration}].
  // json3 format has an "events" array. Each event has:
  //   tStartMs  — start time in milliseconds
  //   dDurationMs — duration in milliseconds
  //   segs      — array of text segments (each with utf8 field)
  // Events without segs are styling/layout events — we skip those.
  return (captionData.events ?? [])
    .filter((e) => e.segs)
    .map((e) => ({
      text: e.segs
        .map((s) => s.utf8 ?? "")
        .join("")
        .replace(/\n/g, " ")
        .trim(),
      start: (e.tStartMs ?? 0) / 1000,
      duration: (e.dDurationMs ?? 0) / 1000,
    }))
    .filter((e) => e.text.length > 0);
}

// --- helpers ---

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}

function httpError(status, message) {
  const e = new Error(message);
  e.status = status;
  return e;
}
