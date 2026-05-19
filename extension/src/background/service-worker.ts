// extension/src/background/service-worker.ts
import { listVideos, matchTranscript, indexTranscript } from "./api-client";
import { captureSW, captureExceptionSW } from "./posthog-sw";
import { classifyFailure } from "./transcript-fetcher";
import { PREFERRED_TRANSCRIPT_LANGS } from "../shared/constants";
import type { FetchTranscriptResult, MessageResponse, Transcript } from "../shared/types";

// Global SW error capture. posthog-js can't run here; use the REST helper.
self.addEventListener("error", (event: ErrorEvent) => {
  captureExceptionSW(event.error ?? new Error(event.message || "sw error"), {
    source: "sw.onerror",
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno,
  });
});
self.addEventListener("unhandledrejection", (event: PromiseRejectionEvent) => {
  captureExceptionSW(event.reason, { source: "sw.unhandledrejection" });
});

type Segment = { text: string; start: number; duration: number };
type ExtractResult = {
  _debug: string;
  segments?: Segment[];
  langCode?: string;
  isGenerated?: boolean;
};

const FETCH_TIMEOUT_MS = 10_000;

// Hard ceiling on total time spent extracting ONE video's transcript across
// every strategy (3 InnerTube clients + tab fallback + retry ladders). Without
// this, a single pathological video can burn minutes; telemetry showed search
// p-max ~487s. ~15s keeps typical videos (~11s) untouched while capping the
// tail. New search worst case ≈ ceil(videos / concurrency) * this.
const PER_VIDEO_BUDGET_MS = 15_000;

// Race a transcript-extraction attempt against PER_VIDEO_BUDGET_MS.
//
// Returning early is NOT enough — the SW keeps running fetches after the worker
// moved on, which is what makes searches "keep going and going". The budget
// must actually CANCEL in-flight work, so `signal` is threaded into every
// downstream fetch (tryClient / fetchTimedTextXml) via AbortSignal.any([...]).
// The tab fallback can't take a signal across the MAIN-world boundary, so it
// is instead gated on signal.aborted and given an absolute deadline.
//
// Budget expiry resolves to a synthetic failed result (not a throw): the
// caller counts `failure_reason`, and a throw would surface as a rejected
// message → mislabelled `unknown`. `budget_exceeded` keeps it observable.
async function runWithVideoBudget(
  attempt: (signal: AbortSignal) => Promise<FetchTranscriptResult>,
): Promise<FetchTranscriptResult> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const budget = new Promise<FetchTranscriptResult>((resolve) => {
    timer = setTimeout(() => {
      controller.abort();
      resolve({ transcript: null, failure_reason: "budget_exceeded" });
    }, PER_VIDEO_BUDGET_MS);
  });
  try {
    return await Promise.race([attempt(controller.signal), budget]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

// ─── Header-spoof rules ──────────────────────────────────────────────────────
// Rewrite Origin/Referer on extension-initiated requests to YouTube endpoints
// so they look like they come from a real youtube.com page. Scoped to
// TAB_ID_NONE — user's own browsing untouched.
//
// HEADER_SPOOF_RULE_IDS at top of file: registerHeaderSpoofRules() runs during
// SW boot, before const bindings further down would be initialized (TDZ).

const HEADER_SPOOF_RULE_IDS = [1001, 1002];

async function registerHeaderSpoofRules(): Promise<void> {
  const headers = [
    { header: "origin", operation: chrome.declarativeNetRequest.HeaderOperation.SET, value: "https://www.youtube.com" },
    { header: "referer", operation: chrome.declarativeNetRequest.HeaderOperation.SET, value: "https://www.youtube.com/" },
  ];
  const rule = (id: number, urlFilter: string): chrome.declarativeNetRequest.Rule => ({
    id,
    priority: 1,
    action: {
      type: chrome.declarativeNetRequest.RuleActionType.MODIFY_HEADERS,
      requestHeaders: headers,
    },
    condition: {
      urlFilter,
      resourceTypes: [chrome.declarativeNetRequest.ResourceType.XMLHTTPREQUEST],
      tabIds: [chrome.tabs.TAB_ID_NONE],
    },
  });
  try {
    await chrome.declarativeNetRequest.updateSessionRules({
      removeRuleIds: HEADER_SPOOF_RULE_IDS,
      addRules: [
        rule(1001, "||youtube.com/youtubei/v1/player"),
        rule(1002, "||youtube.com/api/timedtext"),
      ],
    });
    console.log("[CC] header-spoof rules registered");
  } catch (e) {
    console.warn("[CC] header-spoof rules failed:", e);
    // declarativeNetRequest failure → YouTube treats fetches as cross-origin,
    // transcript pipeline silently breaks. Surface so we can correlate against
    // transcript_fetch_failed reasons.
    void captureSW("header_spoof_rules_failed", {
      error_message: e instanceof Error ? e.message : String(e),
    });
  }
}

const LANDING_BASE = "https://clipchase.xyz";

// Manual open via chrome.action.onClicked so we can instrument the click
// (popup_open_attempted) and catch open() failures (Arc compat). With the
// auto-open behavior, onClicked never fires. Set on every SW wake so existing
// installs pick up the new behavior without waiting for a manifest bump.
//
// Forks that don't expose setPanelBehavior (or reject it) silently break the
// onClicked path — report so we can spot Arc/Brave/Vivaldi quirks instead of
// flying blind.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false }).catch((e) => {
  void captureSW("set_panel_behavior_failed", {
    error_message: e instanceof Error ? e.message : String(e),
  });
});

chrome.runtime.onInstalled.addListener(async (details) => {
  registerHeaderSpoofRules();

  // Post-install attribution: only on fresh install, not update/reload.
  // Stable-ID logic is duplicated from extension/src/shared/posthog.ts because
  // the SW can't import Vite/React-side modules cleanly.
  if (details.reason === "install") {
    try {
      const stored = await chrome.storage.local.get("clipchase_stable_id");
      let stableId = stored.clipchase_stable_id as string | undefined;
      if (!stableId) {
        stableId = `cc_${crypto.randomUUID()}`;
        await chrome.storage.local.set({ clipchase_stable_id: stableId });
      }
      chrome.tabs.create({
        url: `${LANDING_BASE}/installed?stable_id=${encodeURIComponent(stableId)}`,
      });
    } catch (e) {
      console.warn("[CC] post-install tab failed:", e);
    }
  }
});
chrome.runtime.onStartup.addListener(registerHeaderSpoofRules);
// Re-register on every SW wake — session rules don't survive SW termination.
registerHeaderSpoofRules();

// Lifecycle ping. Fires once per SW boot, including the first start after
// install. Tells us the background actually came alive on this client —
// the absence of this for an active person_id is itself a strong signal.
void captureSW("sw_started", {
  ua: (self.navigator as Navigator | undefined)?.userAgent ?? null,
});

// Action click → open side panel. We fire popup_open_attempted *before* the
// open call so failures (Arc, missing windowId, gesture lost) still appear in
// PostHog. The delta between `popup_open_attempted` and `extension_opened`
// (fired from the side panel itself) measures real-world open success rate.
chrome.action.onClicked.addListener(async (tab) => {
  const browserHint = (() => {
    const ua = (self.navigator as Navigator | undefined)?.userAgent ?? "";
    // Best-effort hints — Arc UA is identical to Chrome's, but UA-CH brands
    // sometimes leak the rendering host. Keep both for cross-checking.
    const brands = (self.navigator as Navigator & {
      userAgentData?: { brands?: { brand: string; version: string }[] };
    } | undefined)?.userAgentData?.brands;
    return {
      ua,
      ua_data_brands: brands ? brands.map((b) => b.brand).join(",") : null,
    };
  })();

  void captureSW("popup_open_attempted", {
    has_window_id: typeof tab.windowId === "number",
    tab_url_host: tab.url ? new URL(tab.url).host : null,
    ...browserHint,
  });

  try {
    if (typeof tab.windowId !== "number") {
      throw new Error("missing windowId on action click");
    }
    await chrome.sidePanel.open({ windowId: tab.windowId });
    void captureSW("popup_open_succeeded", browserHint);
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    void captureSW("popup_open_failed", {
      error_message: message,
      ...browserHint,
    });
    captureExceptionSW(e, { source: "sidePanel.open" });
  }
});

// ─── Shared transcript helpers (SW context) ─────────────────────────────────
// fetchTranscriptInPage below cannot reuse these — executeScript only carries
// the function body to MAIN world, not module-scope closures. Helpers are
// duplicated inside it on purpose.

function pickBestTrack(tracks: any[], langs: string[]): any | null {
  for (const lang of langs) {
    const norm = lang.toLowerCase().split("-")[0];
    const manual = tracks.find((t) => t.languageCode?.toLowerCase().split("-")[0] === norm && t.kind !== "asr");
    if (manual) return manual;
    const generated = tracks.find((t) => t.languageCode?.toLowerCase().split("-")[0] === norm);
    if (generated) return generated;
  }
  return tracks[0] ?? null;
}

function decodeEntities(s: string): string {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'");
}

// Parses both timedtext formats. Attribute order is NOT guaranteed in either —
// extract attrs from the opening tag's attribute string independently.
function parseXml(xml: string): Segment[] {
  const segs: Segment[] = [];
  // Format 1: <text start="1.23" dur="0.56">…</text>  (standard timedtext)
  const re1 = /<text\b([^>]*)>([\s\S]*?)<\/text>/g;
  for (const m of xml.matchAll(re1)) {
    const sM = m[1].match(/\bstart="([^"]+)"/);
    const dM = m[1].match(/\bdur="([^"]+)"/);
    if (!sM || !dM) continue;
    const text = decodeEntities(m[2].replace(/<[^>]+>/g, "")).trim();
    if (text) segs.push({ text, start: parseFloat(sM[1]), duration: parseFloat(dM[1]) });
  }
  if (segs.length) return segs;
  // Format 2: <p t="1230" d="560">…</p>  (Android API, ms)
  const re2 = /<p\b([^>]*)>([\s\S]*?)<\/p>/g;
  for (const m of xml.matchAll(re2)) {
    const tM = m[1].match(/\bt="(\d+)"/);
    const dM = m[1].match(/\bd="(\d+)"/);
    if (!tM || !dM) continue;
    const text = decodeEntities(m[2].replace(/<[^>]+>/g, "")).trim();
    if (text) segs.push({ text, start: parseInt(tM[1], 10) / 1000, duration: parseInt(dM[1], 10) / 1000 });
  }
  return segs;
}

async function fetchTimedTextXml(
  baseUrl: string,
  budget: AbortSignal,
): Promise<{ xml: string | null; err: string }> {
  const delays = [0, 1500, 3000];
  for (let attempt = 0; attempt < delays.length; attempt++) {
    if (budget.aborted) return { xml: null, err: "budget" };
    if (delays[attempt]) {
      try {
        await new Promise<void>((resolve, reject) => {
          const t = setTimeout(resolve, delays[attempt]);
          budget.addEventListener(
            "abort",
            () => {
              clearTimeout(t);
              reject(new DOMException("budget", "AbortError"));
            },
            { once: true },
          );
        });
      } catch {
        return { xml: null, err: "budget" };
      }
    }
    try {
      const res = await fetch(baseUrl, {
        signal: AbortSignal.any([AbortSignal.timeout(FETCH_TIMEOUT_MS), budget]),
      });
      if (res.status === 429) continue;
      if (!res.ok) return { xml: null, err: `status=${res.status}` };
      const text = await res.text();
      if (text.length <= 10) return { xml: null, err: `empty len=${text.length}` };
      return { xml: text, err: "" };
    } catch (e) {
      return { xml: null, err: `threw=${String(e)}` };
    }
  }
  return { xml: null, err: "status=429 after retries" };
}

// InnerTube clients tried in order. ANDROID first (lowest latency, no
// signatureCipher), IOS second (different bot-detection treatment),
// WEB_EMBEDDED_PLAYER last. Each client returns its own baseUrl, so this
// also retries XML fetches that 429'd on the previous client.
type InnertubeClient = { clientName: string; clientVersion: string };

const INNERTUBE_CLIENTS: InnertubeClient[] = [
  { clientName: "ANDROID", clientVersion: "20.10.38" },
  { clientName: "IOS", clientVersion: "20.10.4" },
  { clientName: "WEB_EMBEDDED_PLAYER", clientVersion: "1.20240101.00.00" },
];

async function tryClient(
  videoId: string,
  preferredLangs: string[],
  client: InnertubeClient,
  budget: AbortSignal,
): Promise<ExtractResult> {
  const prefix = `sw-${client.clientName.toLowerCase()}-`;
  if (budget.aborted) return { _debug: `${prefix}budget` };
  try {
    const res = await fetch("https://www.youtube.com/youtubei/v1/player?prettyPrint=false", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        context: { client: { clientName: client.clientName, clientVersion: client.clientVersion } },
        videoId,
      }),
      signal: AbortSignal.any([AbortSignal.timeout(FETCH_TIMEOUT_MS), budget]),
    });
    if (!res.ok) return { _debug: `${prefix}status=${res.status}` };
    const data = await res.json();
    const tracks = data?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
    if (!tracks?.length) return { _debug: `${prefix}no-tracks keys=${Object.keys(data ?? {}).join(",")}` };
    const track = pickBestTrack(tracks, preferredLangs);
    if (!track?.baseUrl) return { _debug: `${prefix}no-baseUrl tracks=${tracks.length}` };
    const { xml, err } = await fetchTimedTextXml(track.baseUrl, budget);
    if (!xml) return { _debug: `${prefix}xml-failed err=${err}` };
    const segments = parseXml(xml);
    if (!segments.length) return { _debug: `${prefix}parse-empty xml_len=${xml.length}` };
    return {
      _debug: `${prefix}ok`,
      segments,
      langCode: track.languageCode,
      isGenerated: track.kind === "asr",
    };
  } catch (e) {
    return { _debug: `${prefix}threw=${String(e)}` };
  }
}

async function fetchTranscriptFromSW(
  videoId: string,
  preferredLangs: string[],
  budget: AbortSignal,
): Promise<{ result: ExtractResult; perClientDebug: string[] }> {
  const perClientDebug: string[] = [];
  for (const client of INNERTUBE_CLIENTS) {
    if (budget.aborted) break;
    const r = await tryClient(videoId, preferredLangs, client, budget);
    perClientDebug.push(r._debug);
    if (r.segments?.length) return { result: r, perClientDebug };
  }
  return { result: { _debug: perClientDebug.join("|") }, perClientDebug };
}

// ─── Tab fallback (runs in MAIN world via executeScript) ────────────────────
// Self-contained — helpers re-declared inside because executeScript only
// carries this function body across the world boundary.
async function fetchTranscriptInPage(
  videoId: string,
  preferredLangs: string[],
  budgetDeadlineMs: number,
): Promise<ExtractResult> {
  const FETCH_TIMEOUT_MS_INNER = 10_000;
  // Can't carry an AbortSignal across the MAIN-world boundary, so the in-page
  // ladder self-bounds: never wait/fetch past the caller's per-video deadline.
  const remainingMs = () => Math.max(0, budgetDeadlineMs - Date.now());
  const innerTimeout = () =>
    AbortSignal.timeout(Math.min(FETCH_TIMEOUT_MS_INNER, remainingMs()));
  function pickBestTrack(tracks: any[], langs: string[]): any | null {
    for (const lang of langs) {
      const norm = lang.toLowerCase().split("-")[0];
      const manual = tracks.find((t) => t.languageCode?.toLowerCase().split("-")[0] === norm && t.kind !== "asr");
      if (manual) return manual;
      const generated = tracks.find((t) => t.languageCode?.toLowerCase().split("-")[0] === norm);
      if (generated) return generated;
    }
    return tracks[0] ?? null;
  }
  function decodeEntities(s: string): string {
    return s
      .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&apos;/g, "'");
  }
  function parseXml(xml: string): Segment[] {
    const segs: Segment[] = [];
    const re1 = /<text\b([^>]*)>([\s\S]*?)<\/text>/g;
    for (const m of xml.matchAll(re1)) {
      const sM = m[1].match(/\bstart="([^"]+)"/);
      const dM = m[1].match(/\bdur="([^"]+)"/);
      if (!sM || !dM) continue;
      const text = decodeEntities(m[2].replace(/<[^>]+>/g, "")).trim();
      if (text) segs.push({ text, start: parseFloat(sM[1]), duration: parseFloat(dM[1]) });
    }
    if (segs.length) return segs;
    const re2 = /<p\b([^>]*)>([\s\S]*?)<\/p>/g;
    for (const m of xml.matchAll(re2)) {
      const tM = m[1].match(/\bt="(\d+)"/);
      const dM = m[1].match(/\bd="(\d+)"/);
      if (!tM || !dM) continue;
      const text = decodeEntities(m[2].replace(/<[^>]+>/g, "")).trim();
      if (text) segs.push({ text, start: parseInt(tM[1], 10) / 1000, duration: parseInt(dM[1], 10) / 1000 });
    }
    return segs;
  }
  async function fetchXml(baseUrl: string): Promise<{ xml: string | null; err: string }> {
    const delays = [0, 1500, 3000];
    for (let attempt = 0; attempt < delays.length; attempt++) {
      if (remainingMs() <= 0) return { xml: null, err: "budget" };
      if (delays[attempt]) {
        if (delays[attempt] >= remainingMs()) return { xml: null, err: "budget" };
        await new Promise<void>((r) => setTimeout(r, delays[attempt]));
      }
      try {
        const res = await fetch(baseUrl, { signal: innerTimeout() });
        if (res.status === 429) continue;
        if (!res.ok) return { xml: null, err: `status=${res.status}` };
        const text = await res.text();
        if (text.length <= 10) return { xml: null, err: `empty len=${text.length}` };
        return { xml: text, err: "" };
      } catch (e) {
        return { xml: null, err: `threw=${String(e)}` };
      }
    }
    return { xml: null, err: "status=429 after retries" };
  }

  // Strategy 1: Android API
  try {
    const res = await fetch("https://www.youtube.com/youtubei/v1/player?prettyPrint=false", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        context: { client: { clientName: "ANDROID", clientVersion: "20.10.38" } },
        videoId,
      }),
      signal: innerTimeout(),
    });
    if (res.ok) {
      const data = await res.json();
      const tracks = data?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
      if (tracks?.length) {
        const track = pickBestTrack(tracks, preferredLangs);
        if (track?.baseUrl) {
          const { xml, err } = await fetchXml(track.baseUrl);
          if (xml) {
            const segments = parseXml(xml);
            if (segments.length) {
              return {
                _debug: "tab-android-ok",
                segments,
                langCode: track.languageCode,
                isGenerated: track.kind === "asr",
              };
            }
            return { _debug: `tab-android-parse-empty xml_len=${xml.length}` };
          }
          return { _debug: `tab-android-xml-failed err=${err}` };
        }
        return { _debug: `tab-android-no-baseUrl tracks=${tracks.length}` };
      }
      return { _debug: `tab-android-no-tracks keys=${Object.keys(data ?? {}).join(",")}` };
    }
  } catch {
    // fall through to strategy 2
  }

  // Strategy 2: ytInitialPlayerResponse already injected on watch page.
  const yt = (window as any).ytInitialPlayerResponse;
  const ytiprTracks = yt?.captions?.playerCaptionsTracklistRenderer?.captionTracks;
  if (ytiprTracks?.length) {
    const track = pickBestTrack(ytiprTracks, preferredLangs);
    if (track?.baseUrl) {
      const { xml, err } = await fetchXml(track.baseUrl);
      if (xml) {
        const segments = parseXml(xml);
        if (segments.length) {
          return {
            _debug: "tab-ytipr-ok",
            segments,
            langCode: track.languageCode,
            isGenerated: track.kind === "asr",
          };
        }
        return { _debug: `tab-ytipr-parse-empty xml_len=${xml.length}` };
      }
      return { _debug: `tab-ytipr-xml-failed err=${err}` };
    }
  }

  return { _debug: "tab-no-tracks" };
}

// ─── Tab discovery ──────────────────────────────────────────────────────────
async function getYouTubeTabId(): Promise<number | null> {
  // currentWindow: true is undefined in service worker context — use lastFocusedWindow.
  const [active] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (active?.id && active.url?.includes("youtube.com")) return active.id;
  const [any] = await chrome.tabs.query({ url: "*://*.youtube.com/*" });
  return any?.id ?? null;
}

// ─── Message routing ────────────────────────────────────────────────────────
function languageLabel(code: string): string {
  try {
    const dn = new Intl.DisplayNames(["en"], { type: "language" });
    return dn.of(code) ?? code.toUpperCase();
  } catch {
    return code.toUpperCase();
  }
}

function buildTranscript(extracted: ExtractResult): Transcript | null {
  if (!extracted.segments?.length) return null;
  const langCode = extracted.langCode ?? "en";
  return {
    language_code: langCode,
    language_label: languageLabel(langCode),
    is_generated: extracted.isGenerated ?? true,
    segments: extracted.segments,
  };
}

async function handleFetchTranscript(
  videoId: string,
  preferredLangs: string[],
): Promise<FetchTranscriptResult> {
  // Re-await rule registration on every fetch. SW termination after ~30s idle
  // drops session rules; the first fetch after wake can race ahead of the
  // top-level registerHeaderSpoofRules() call. updateSessionRules is
  // idempotent (removeRuleIds + addRules) so paying ~5-50ms here is safe.
  await registerHeaderSpoofRules();

  const deadline = Date.now() + PER_VIDEO_BUDGET_MS;

  const result = await runWithVideoBudget(async (budget) => {
    const { result: sw, perClientDebug } = await fetchTranscriptFromSW(
      videoId,
      preferredLangs,
      budget,
    );
    if (sw.segments?.length) {
      return { transcript: buildTranscript(sw), failure_reason: null };
    }

    // Budget blew during the SW path: bail WITHOUT telemetry. Promise.race has
    // already resolved to budget_exceeded and the wrapper emits that single
    // event — firing a no_tab capture here too would double-count this video.
    if (budget.aborted) {
      return { transcript: null, failure_reason: "budget_exceeded" };
    }

    // Fallback: piggy-back on a YouTube tab if all SW clients returned nothing.
    const tabId = await getYouTubeTabId();
    if (!tabId) {
      const reason = classifyFailure([...perClientDebug, "no-youtube-tab"]);
      void captureSW("transcript_fetch_failed", {
        video_id: videoId,
        sw_debug: perClientDebug.join("|"),
        tab_debug: "no-youtube-tab",
        failure_reason: reason,
        preferred_langs: preferredLangs.join(","),
      });
      return { transcript: null, failure_reason: reason };
    }
    let tab: ExtractResult = { _debug: "tab-not-run" };
    try {
      const res = await chrome.scripting.executeScript({
        target: { tabId },
        func: fetchTranscriptInPage,
        args: [videoId, preferredLangs, deadline],
        world: "MAIN" as chrome.scripting.ExecutionWorld,
      });
      tab = res[0]?.result ?? { _debug: "tab-no-result" };
    } catch (e) {
      tab = { _debug: `tab-threw=${String(e)}` };
    }
    if (tab.segments?.length) {
      return { transcript: buildTranscript(tab), failure_reason: null };
    }
    const reason = classifyFailure([...perClientDebug, tab._debug]);
    void captureSW("transcript_fetch_failed", {
      video_id: videoId,
      sw_debug: perClientDebug.join("|"),
      tab_debug: tab._debug,
      failure_reason: reason,
      preferred_langs: preferredLangs.join(","),
    });
    return { transcript: null, failure_reason: reason };
  });

  if (result.failure_reason === "budget_exceeded") {
    void captureSW("transcript_fetch_failed", {
      video_id: videoId,
      sw_debug: "budget",
      tab_debug: "budget",
      failure_reason: "budget_exceeded",
      preferred_langs: preferredLangs.join(","),
    });
  }
  return result;
}

chrome.runtime.onMessage.addListener(
  (msg: { type: string; [key: string]: unknown }, _sender, sendResponse) => {
    (async () => {
      try {
        let data: unknown;
        switch (msg.type) {
          case "list-videos":
            data = await listVideos(msg.params as Parameters<typeof listVideos>[0]);
            break;
          case "fetch-transcript":
            data = await handleFetchTranscript(
              msg.videoId as string,
              (msg.preferredLangs as string[] | undefined) ?? [...PREFERRED_TRANSCRIPT_LANGS],
            );
            break;
          case "match-transcript":
            data = await matchTranscript(msg.params as Parameters<typeof matchTranscript>[0]);
            break;
          case "index-transcript":
            data = await indexTranscript(msg.params as Parameters<typeof indexTranscript>[0]);
            break;
          default:
            sendResponse({ ok: false, error: `Unknown message type: ${msg.type}` } satisfies MessageResponse<never>);
            return;
        }
        sendResponse({ ok: true, data } satisfies MessageResponse<unknown>);
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : String(e);
        console.error("[TS] error:", message);
        captureExceptionSW(e, { source: "sw.onMessage", message_type: msg.type });
        sendResponse({ ok: false, error: message } satisfies MessageResponse<never>);
      }
    })();
    return true;
  },
);
