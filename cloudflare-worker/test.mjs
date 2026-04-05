/**
 * Local test — run with: node test.mjs
 */

const TEST_VIDEO_ID = "dQw4w9WgXcQ";
const BROWSER_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
  "Accept-Language": "en-US,en;q=0.9",
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
};

async function run(videoId) {
  // Step 1: fetch watch page, extract caption track URLs + cookies
  console.log(`[1] Fetching watch page for ${videoId}...`);
  const watchRes = await fetch(`https://www.youtube.com/watch?v=${videoId}`, {
    headers: BROWSER_HEADERS,
  });
  console.log(`    Status: ${watchRes.status}`);

  // Capture session cookies YouTube sets — needed for the timedtext URL
  const cookies = watchRes.headers.getSetCookie?.() ?? [];
  const cookieStr = cookies.map(c => c.split(";")[0]).join("; ");
  console.log(`    Cookies: ${cookieStr.slice(0, 80)}...`);

  const html = await watchRes.text();
  const marker = "ytInitialPlayerResponse = ";
  const startIdx = html.indexOf(marker);
  if (startIdx === -1) { console.error("✘ ytInitialPlayerResponse not found"); return; }

  let depth = 0, i = startIdx + marker.length;
  for (; i < html.length; i++) {
    if (html[i] === "{") depth++;
    else if (html[i] === "}") { if (--depth === 0) break; }
  }
  const playerData = JSON.parse(html.slice(startIdx + marker.length, i + 1));
  const tracks = playerData?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
  if (!tracks?.length) { console.error("✘ No caption tracks"); return; }
  console.log(`    Found ${tracks.length} tracks`);

  const track = tracks.find(t => t.languageCode === "en" || t.languageCode === "en-US") ?? tracks[0];
  console.log(`    Using: ${track.languageCode} (${track.kind ?? "manual"})`);
  console.log(`    Full URL: ${track.baseUrl}`);

  // Step 2: fetch transcript XML using unsigned direct URL
  // The signed URL from the watch page gets silently blocked.
  // The direct timedtext API (unsigned) sometimes works for public videos.
  console.log(`\n[2] Fetching transcript XML (direct URL)...`);
  const directUrl = `https://www.youtube.com/api/timedtext?v=${videoId}&lang=${track.languageCode}`;
  console.log(`    URL: ${directUrl}`);
  const xmlRes = await fetch(directUrl, {
    headers: {
      ...BROWSER_HEADERS,
      "Referer": `https://www.youtube.com/watch?v=${videoId}`,
      ...(cookieStr ? { "Cookie": cookieStr } : {}),
    },
  });
  console.log(`    Status: ${xmlRes.status}`);
  console.log(`    Content-Type: ${xmlRes.headers.get("content-type")}`);
  console.log(`    Content-Encoding: ${xmlRes.headers.get("content-encoding")}`);
  console.log(`    Content-Length: ${xmlRes.headers.get("content-length")}`);
  const buf = await xmlRes.arrayBuffer();
  console.log(`    ArrayBuffer byte length: ${buf.byteLength}`);
  console.log(`    First bytes: ${[...new Uint8Array(buf).slice(0, 16)].map(b => b.toString(16).padStart(2,"0")).join(" ")}`);
  const xml = new TextDecoder().decode(buf);
  console.log(`    Text length: ${xml.length}, preview: ${xml.slice(0, 120)}`);

  if (!xml.trim()) { console.error("✘ Empty response"); return; }

  // Step 3: parse XML into [{text, start, duration}]
  console.log(`\n[3] Parsing XML...`);
  const segments = [];
  const re = /<text start="([^"]+)" dur="([^"]+)"[^>]*>([\s\S]*?)<\/text>/g;
  let m;
  while ((m = re.exec(xml)) !== null) {
    const text = m[3].replace(/&#39;/g, "'").replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/\n/g, " ").trim();
    if (text) segments.push({ start: parseFloat(m[1]), duration: parseFloat(m[2]), text });
  }

  console.log(`    Parsed ${segments.length} segments`);
  if (segments.length > 0) {
    segments.slice(0, 3).forEach(s => console.log(`    [${s.start.toFixed(2)}s] ${s.text}`));
    console.log("\n✔ SUCCESS");
  } else {
    console.error("✘ 0 segments parsed — check XML format above");
  }
}

run(TEST_VIDEO_ID).catch(e => console.error("Error:", e));
