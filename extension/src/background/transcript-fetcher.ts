// extension/src/background/transcript-fetcher.ts
import type { FailureReason, TranscriptSegment } from "../shared/types";

export interface CaptionTrack {
  languageCode: string;
  baseUrl: string;
  kind?: string;
  name?: { simpleText?: string };
}

export function normalizeLanguageCode(code: string): string {
  return (code ?? "").toLowerCase().split("-")[0];
}

export function pickTrack(
  tracks: CaptionTrack[],
  preferredLangs: string[]
): CaptionTrack | null {
  for (const lang of preferredLangs) {
    const manual = tracks.find(
      (t) => normalizeLanguageCode(t.languageCode) === lang && t.kind !== "asr"
    );
    if (manual) return manual;

    const generated = tracks.find(
      (t) => normalizeLanguageCode(t.languageCode) === lang
    );
    if (generated) return generated;
  }
  return null;
}

// Maps the `_debug` string from the last attempted transcript-fetch strategy
// to a stable FailureReason enum value. The last element in `debugStrings`
// represents the final fallback's outcome — that's what the user saw.
// Order matters: status= must check before xml-failed status=429 to avoid
// misclassifying an InnerTube /player 429 as an XML 429.
export function classifyFailure(debugStrings: string[]): FailureReason {
  const last = debugStrings[debugStrings.length - 1] ?? "";
  if (last === "no-youtube-tab") return "no_tab";
  if (last.startsWith("tab-threw")) return "tab_threw";
  if (last.startsWith("tab-")) return "tab_failed";
  // SW debug strings are prefixed `sw-<client>-`. Strip for matching.
  const m = last.match(/^sw-[a-z0-9_]+-(.+)$/);
  const body = m ? m[1] : last.replace(/^sw-/, "");
  if (body.startsWith("status=")) return "sw_blocked";
  if (body.startsWith("no-tracks")) return "sw_no_tracks";
  if (body.startsWith("no-baseUrl")) return "sw_no_baseurl";
  if (body.startsWith("xml-failed") && body.includes("429")) return "xml_429";
  if (body.startsWith("xml-failed")) return "xml_status_err";
  if (body.startsWith("parse-empty")) return "parse_empty";
  if (body.startsWith("threw")) return "sw_threw";
  return "unknown";
}

export function parseSegments(xml: string): TranscriptSegment[] {
  const segments: TranscriptSegment[] = [];
  const re = new RegExp('<text start="([^"]+)" dur="([^"]+)"[^>]*>([\\s\\S]*?)<\\/text>', "g");
  let m: RegExpExecArray | null;
  while ((m = re.exec(xml)) !== null) {
    const text = m[3]
      .replace(/&#39;/g, "'")
      .replace(/&amp;/g, "&")
      .replace(/&quot;/g, '"')
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/\n/g, " ")
      .trim();
    if (text) {
      segments.push({ text, start: parseFloat(m[1]), duration: parseFloat(m[2]) });
    }
  }
  return segments;
}
