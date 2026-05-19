// extension/src/background/transcript-fetcher.test.ts
import { describe, it, expect } from "vitest";
import { pickTrack, parseSegments, normalizeLanguageCode, classifyFailure, type CaptionTrack } from "./transcript-fetcher";

// ── normalizeLanguageCode ─────────────────────────────────────────────────────

describe("normalizeLanguageCode", () => {
  it("strips region subtag", () => {
    expect(normalizeLanguageCode("en-US")).toBe("en");
    expect(normalizeLanguageCode("zh-Hant")).toBe("zh");
  });

  it("lowercases", () => {
    expect(normalizeLanguageCode("EN")).toBe("en");
  });

  it("returns empty string for empty input", () => {
    expect(normalizeLanguageCode("")).toBe("");
  });
});

// ── pickTrack ─────────────────────────────────────────────────────────────────

const enManual: CaptionTrack = {
  languageCode: "en",
  baseUrl: "https://example.com/en",
  kind: "",
  name: { simpleText: "English" },
};
const enAsr: CaptionTrack = {
  languageCode: "en",
  baseUrl: "https://example.com/en-asr",
  kind: "asr",
  name: { simpleText: "English (auto-generated)" },
};
const hiManual: CaptionTrack = {
  languageCode: "hi",
  baseUrl: "https://example.com/hi",
  kind: "",
  name: { simpleText: "Hindi" },
};
const jaManual: CaptionTrack = {
  languageCode: "ja",
  baseUrl: "https://example.com/ja",
  kind: "",
  name: { simpleText: "Japanese" },
};

describe("pickTrack", () => {
  it("prefers manual over ASR for same language", () => {
    const result = pickTrack([enAsr, enManual], ["en"]);
    expect(result).toBe(enManual);
  });

  it("falls back to ASR if no manual available", () => {
    const result = pickTrack([enAsr], ["en"]);
    expect(result).toBe(enAsr);
  });

  it("respects language preference order", () => {
    const result = pickTrack([enManual, hiManual], ["hi", "en"]);
    expect(result).toBe(hiManual);
  });

  it("skips languages not in preferredLangs", () => {
    const result = pickTrack([jaManual], ["en", "hi"]);
    expect(result).toBeNull();
  });

  it("returns null for empty tracks", () => {
    expect(pickTrack([], ["en"])).toBeNull();
  });

  it("normalizes region codes when matching", () => {
    const enUs: CaptionTrack = { languageCode: "en-US", baseUrl: "https://example.com/en-us", kind: "" };
    expect(pickTrack([enUs], ["en"])).toBe(enUs);
  });
});

// ── parseSegments ─────────────────────────────────────────────────────────────

const CAPTION_XML = `<?xml version="1.0" encoding="utf-8" ?>
<transcript>
  <text start="0.5" dur="2.0">Hello world</text>
  <text start="3.0" dur="1.5">This is a &amp;test&amp;</text>
  <text start="5.0" dur="2.5">with &#39;quotes&#39; here</text>
  <text start="7.0" dur="1.0">   </text>
</transcript>`;

describe("parseSegments", () => {
  it("parses start, duration, and text correctly", () => {
    const segs = parseSegments(CAPTION_XML);
    expect(segs).toHaveLength(3); // whitespace-only entry is skipped
    expect(segs[0]).toEqual({ text: "Hello world", start: 0.5, duration: 2.0 });
    expect(segs[1]).toEqual({ text: "This is a &test&", start: 3.0, duration: 1.5 });
    expect(segs[2]).toEqual({ text: "with 'quotes' here", start: 5.0, duration: 2.5 });
  });

  it("decodes all HTML entities", () => {
    const xml = `<transcript><text start="0" dur="1">&amp; &lt; &gt; &quot; &#39;</text></transcript>`;
    const segs = parseSegments(xml);
    expect(segs[0].text).toBe('& < > " \'');
  });

  it("collapses newlines to spaces", () => {
    const xml = `<transcript><text start="0" dur="1">line one\nline two</text></transcript>`;
    const segs = parseSegments(xml);
    expect(segs[0].text).toBe("line one line two");
  });

  it("skips whitespace-only entries", () => {
    const xml = `<transcript><text start="0" dur="1">   </text><text start="1" dur="1">real</text></transcript>`;
    const segs = parseSegments(xml);
    expect(segs).toHaveLength(1);
    expect(segs[0].text).toBe("real");
  });

  it("returns empty array for empty XML", () => {
    expect(parseSegments("")).toHaveLength(0);
    expect(parseSegments("<transcript></transcript>")).toHaveLength(0);
  });
});

// ── classifyFailure ───────────────────────────────────────────────────────────

describe("classifyFailure", () => {
  it("classifies no-tab when last entry is no-youtube-tab", () => {
    expect(classifyFailure(["sw-android-no-tracks keys=x", "no-youtube-tab"])).toBe("no_tab");
  });

  it("classifies tab_threw when last entry starts with tab-threw", () => {
    expect(classifyFailure(["sw-android-status=403", "tab-threw=Error: boom"])).toBe("tab_threw");
  });

  it("classifies tab_failed for any other tab- prefix", () => {
    expect(classifyFailure(["sw-android-status=403", "tab-no-tracks"])).toBe("tab_failed");
    expect(classifyFailure(["sw-android-status=403", "tab-android-no-baseUrl tracks=1"])).toBe("tab_failed");
  });

  it("classifies sw_blocked for InnerTube non-ok status", () => {
    expect(classifyFailure(["sw-android-status=403"])).toBe("sw_blocked");
    expect(classifyFailure(["sw-ios-status=429"])).toBe("sw_blocked");
  });

  it("classifies sw_no_tracks", () => {
    expect(classifyFailure(["sw-android-no-tracks keys=playabilityStatus"])).toBe("sw_no_tracks");
  });

  it("classifies sw_no_baseurl", () => {
    expect(classifyFailure(["sw-ios-no-baseUrl tracks=2"])).toBe("sw_no_baseurl");
  });

  it("classifies xml_429 when xml-failed err contains 429", () => {
    expect(classifyFailure(["sw-android-xml-failed err=status=429 after retries"])).toBe("xml_429");
  });

  it("classifies xml_status_err for other xml-failed statuses", () => {
    expect(classifyFailure(["sw-web_embedded_player-xml-failed err=status=500"])).toBe("xml_status_err");
    expect(classifyFailure(["sw-android-xml-failed err=threw=TypeError"])).toBe("xml_status_err");
  });

  it("classifies parse_empty", () => {
    expect(classifyFailure(["sw-android-parse-empty xml_len=42"])).toBe("parse_empty");
  });

  it("classifies sw_threw", () => {
    expect(classifyFailure(["sw-ios-threw=AbortError"])).toBe("sw_threw");
  });

  it("classifies unknown for unrecognised debug strings", () => {
    expect(classifyFailure([])).toBe("unknown");
    expect(classifyFailure(["something-else"])).toBe("unknown");
  });

  it("uses only the last entry for classification", () => {
    expect(classifyFailure(["sw-android-status=403", "sw-ios-status=403", "sw-web_embedded_player-no-tracks keys=x"])).toBe("sw_no_tracks");
  });
});
