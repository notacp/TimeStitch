export interface Match {
  start: number;
  text: string;
  context_before: string;
  context_after: string;
}

export interface SearchResult {
  video_id: string;
  title: string;
  published_at: string;
  thumbnail: string;
  transcript_language_code: string;
  transcript_language_label: string;
  search_terms_used: string[];
  matches: Match[];
}

export type TimeRange = "7d" | "30d" | "6m" | "1y" | "all";

export type SortBy = "hits" | "recent";

export interface ChannelSuggestion {
  id: string;
  title: string;
  thumbnail: string;
}

export interface VideoInfo {
  id: string;
  title: string;
  publishedAt: string;
  thumbnail: string;
}

export interface TranscriptSegment {
  start: number;
  duration: number;
  text: string;
}

export interface Transcript {
  language_code: string;
  language_label: string;
  is_generated: boolean;
  segments: TranscriptSegment[];
}

export type FailureReason =
  | "sw_blocked"
  | "sw_no_tracks"
  | "sw_no_baseurl"
  | "xml_429"
  | "xml_status_err"
  | "parse_empty"
  | "sw_threw"
  | "no_tab"
  | "tab_threw"
  | "tab_failed"
  | "unknown";

export interface FetchTranscriptResult {
  transcript: Transcript | null;
  failure_reason: FailureReason | null;
}

// ── Message types for chrome.runtime.sendMessage ──────────────────────────────

export type ExtMessage =
  | { type: "list-videos"; params: VideoListParams }
  | { type: "fetch-transcript"; videoId: string; preferredLangs: string[] }
  | { type: "match-transcript"; params: MatchParams }
  | { type: "index-transcript"; params: IndexTranscriptParams };

export interface VideoListParams {
  channel_url: string;
  max_videos: number;
  published_after: string | null;
  exclude_shorts: boolean;
}

export interface VideoListResponse {
  channel_id: string;
  videos: VideoInfo[];
}

export interface MatchParams {
  keyword: string;
  video: VideoInfo;
  transcript: Transcript;
}

export interface MatchResponse {
  match_result: SearchResult | null;
}

export interface IndexTranscriptParams {
  channel_id: string;
  source_url: string;
  video: VideoInfo;
  transcript: Transcript;
}

export interface IndexTranscriptResponse {
  stored: number;
}

export type MessageResponse<T> =
  | { ok: true; data: T }
  | { ok: false; error: string };
