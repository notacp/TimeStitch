import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Search } from "lucide-react";
import { SearchResult, TimeRange, ChannelSuggestion, VideoInfo, SortBy, FailureReason } from "../shared/types";
import { getPublishedAfterDate, dominantReason } from "../shared/utils";
import { send } from "../shared/messaging";
import { SearchForm } from "../components/SearchForm";
import { TimeRangeSelector } from "../components/TimeRangeSelector";
import { SearchResults } from "../components/SearchResults";
import { LoadingStream } from "../components/LoadingStream";
import { WelcomeModal } from "../components/WelcomeModal";
import posthog from "../shared/posthog";
import { PREFERRED_TRANSCRIPT_LANGS } from "../shared/constants";
import { detectKeywordScript } from "../lib/keyword-script";
import { consumeSSE } from "../lib/sse";

const UNINDEXED_FETCH_CONCURRENCY = 6;
const MAX_VIDEOS = 20;

type ChannelResolutionSource =
  | "suggestion"
  | "typed_url"
  | "typed_handle"
  | "typed_name"
  | "empty";

function classifyChannelInput(
  value: string,
  pickedFromSuggestion: boolean,
): ChannelResolutionSource {
  const trimmed = value.trim();
  if (!trimmed) return "empty";
  if (pickedFromSuggestion) return "suggestion";
  if (/^https?:\/\//i.test(trimmed)) return "typed_url";
  if (trimmed.startsWith("@")) return "typed_handle";
  return "typed_name";
}

const BUILDER_NOTE =
  "I kept rewatching videos just to find a single moment I remembered. No way to search, no timestamps — just scrubbing forever. So I built this. If it saves you even five minutes, it was worth it. Thank you for trying it out.";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function App() {
  const [channelUrl, setChannelUrl] = useState("");
  const [channelDisplay, setChannelDisplay] = useState("");
  const [suggestions, setSuggestions] = useState<ChannelSuggestion[]>([]);
  const [isSuggestionsLoading, setIsSuggestionsLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [timeRange, setTimeRange] = useState<TimeRange>("30d");
  const [sortBy, setSortBy] = useState<SortBy>("hits");
  const [excludeShorts, setExcludeShorts] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState("");
  const [hasSearched, setHasSearched] = useState(false);
  const [lastSearch, setLastSearch] = useState<{ channel: string; keyword: string } | null>(null);
  const [formError, setFormError] = useState("");
  const [showWelcome, setShowWelcome] = useState(() => !localStorage.getItem("hasSeenWelcome"));
  const [showReviewPrompt, setShowReviewPrompt] = useState(false);
  // Generation counter — each runSearch call claims a unique generation.
  // After every await, we compare against the latest generation; if a newer
  // search has started, we bail out.  This prevents stale results from an
  // older search leaking into state after a newer search began.
  const searchGenRef = useRef(0);
  // Aborts any in-flight SSE connection when a new search supersedes it.
  // Without this, the prior fetch keeps streaming bytes (server CPU + bandwidth)
  // even though superseded() gates state writes.
  const searchAbortRef = useRef<AbortController | null>(null);
  // Prevents the suggestion effect from re-fetching when channelDisplay is set
  // programmatically (i.e. by selecting a suggestion, not by the user typing).
  const skipSuggestionFetchRef = useRef(false);
  // Tracks whether the current channel value originated from a suggestion pick.
  // Flipped back to false the moment the user edits the field.
  const channelFromSuggestionRef = useRef(false);
  // Per-query dedupe so a persistently-failing suggestions endpoint doesn't
  // flood PostHog with one event per keystroke while typing.
  const suggestionFailureLoggedRef = useRef<string | null>(null);
  const suggestionEmptyLoggedRef = useRef<string | null>(null);

  // Channel suggestions — call backend directly (no Next.js proxy in extension).
  useEffect(() => {
    if (skipSuggestionFetchRef.current) {
      skipSuggestionFetchRef.current = false;
      return;
    }
    if (channelDisplay.length < 2) {
      setSuggestions([]);
      setIsSuggestionsLoading(false);
      return;
    }
    const timer = setTimeout(async () => {
      setIsSuggestionsLoading(true);
      const query = channelDisplay;
      try {
        const res = await fetch(
          `${API_BASE}/api/suggest-channels?q=${encodeURIComponent(query)}`
        );
        if (!res.ok) {
          if (suggestionFailureLoggedRef.current !== query) {
            suggestionFailureLoggedRef.current = query;
            posthog.capture("suggestion_fetch_failed", {
              query_length: query.length,
              status: res.status,
              reason: "non_ok_status",
            });
          }
          return;
        }
        const items = (await res.json()) as ChannelSuggestion[];
        setSuggestions(items);
        if (items.length === 0 && suggestionEmptyLoggedRef.current !== query) {
          suggestionEmptyLoggedRef.current = query;
          posthog.capture("suggestion_zero_results", {
            query_length: query.length,
          });
        }
      } catch (err: unknown) {
        if (suggestionFailureLoggedRef.current !== query) {
          suggestionFailureLoggedRef.current = query;
          posthog.capture("suggestion_fetch_failed", {
            query_length: query.length,
            reason: "network_error",
            error_message: err instanceof Error ? err.message : String(err),
          });
        }
      } finally {
        setIsSuggestionsLoading(false);
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [channelDisplay]);

  // Screen-view events — fire on transition into the "shown" state so each
  // impression is counted exactly once. Pair with the existing click/dismiss
  // events to compute conversion rates per surface.
  useEffect(() => {
    if (showWelcome) posthog.capture("welcome_shown");
  }, [showWelcome]);
  useEffect(() => {
    if (showReviewPrompt) posthog.capture("review_prompt_shown");
  }, [showReviewPrompt]);

  const handleDismissWelcome = (useCase?: string) => {
    localStorage.setItem("hasSeenWelcome", "1");
    posthog.capture("welcome_dismissed", { use_case: useCase ?? null });
    if (useCase) posthog.setPersonProperties({ use_case: useCase });
    setShowWelcome(false);
  };

  const handleSelectSuggestion = (suggestion: ChannelSuggestion) => {
    skipSuggestionFetchRef.current = true;
    channelFromSuggestionRef.current = true;
    setChannelDisplay(suggestion.title);
    setChannelUrl(suggestion.id);
    setSuggestions([]);
    posthog.capture("channel_selected_from_suggestion", {
      channel_id: suggestion.id,
      channel_title: suggestion.title,
      typed_query: channelDisplay,
    });
  };

  const handleDismissSuggestions = () => setSuggestions([]);

  const handleChannelInputChange = (value: string) => {
    // User editing the field invalidates any prior suggestion pick.
    channelFromSuggestionRef.current = false;
    setChannelDisplay(value);
    setChannelUrl(value);
    if (formError) setFormError("");
  };

  const handleKeywordChange = (value: string) => {
    setKeyword(value);
    if (formError) setFormError("");
  };

  const runSearch = async () => {
    // Cancel any in-flight SSE before claiming a new generation.
    searchAbortRef.current?.abort();
    const controller = new AbortController();
    searchAbortRef.current = controller;

    const myGen = ++searchGenRef.current;
    const superseded = () => myGen !== searchGenRef.current;

    setIsLoading(true);
    setError("");
    setResults([]);
    setHasSearched(false);
    setSuggestions([]);

    const searchStartedAt = Date.now();
    let searchFailed = false;

    const channelResolutionSource = classifyChannelInput(
      channelDisplay,
      channelFromSuggestionRef.current,
    );

    posthog.capture("search_started", {
      channel: channelUrl,
      keyword,
      keyword_script: detectKeywordScript(keyword),
      time_range: timeRange,
      exclude_shorts: excludeShorts,
      channel_resolution_source: channelResolutionSource,
    });

    let videosScanned = 0;
    let indexedHits = 0;
    let transcriptFailures = 0;
    let matchCount = 0;
    const failureReasonCounts: Partial<Record<FailureReason, number>> = {};

    try {
      const publishedAfter = getPublishedAfterDate(timeRange);

      // Step 1 — Stream indexed-only matches from /api/search via SSE.
      // Indexed FTS pre-filter skips videos that can't possibly match. Cached
      // transcripts mean no live YouTube fetch on the server. Un-indexed videos
      // are returned in the 'unindexed_videos' event; we fetch those locally.
      const params = new URLSearchParams({
        channel_url: channelUrl,
        keyword,
        max_videos: String(MAX_VIDEOS),
        exclude_shorts: String(excludeShorts),
        skip_live: "true",
      });
      if (publishedAfter) params.set("published_after", publishedAfter);
      const sseUrl = `${API_BASE}/api/search?${params.toString()}`;

      let unindexedVideos: VideoInfo[] = [];
      let resolvedChannelId: string | null = null;
      let sseError: string | null = null;

      await consumeSSE(sseUrl, {
        signal: controller.signal,
        onMessage: (data) => {
          if (superseded() || !data) return;
          try {
            const result = JSON.parse(data) as SearchResult;
            indexedHits++;
            matchCount++;
            setResults((prev) => [...prev, result]);
          } catch {
            // ignore malformed
          }
        },
        onEvent: (event, data) => {
          if (superseded()) return;
          if (event === "unindexed_videos") {
            try {
              const parsed = JSON.parse(data) as { videos: VideoInfo[] };
              unindexedVideos = parsed.videos ?? [];
            } catch {
              unindexedVideos = [];
            }
          } else if (event === "meta") {
            try {
              const parsed = JSON.parse(data) as { total: number; channel_id?: string };
              videosScanned = parsed.total ?? 0;
              resolvedChannelId = parsed.channel_id ?? null;
            } catch {
              // ignore
            }
          } else if (event === "error") {
            try {
              const parsed = JSON.parse(data) as { detail?: string };
              sseError = parsed.detail ?? "Search failed";
            } catch {
              sseError = "Search failed";
            }
          }
        },
      });

      if (superseded()) return;
      if (sseError) throw new Error(sseError);

      // Step 2 — Parallel SW transcript fetch + match for un-indexed videos.
      if (unindexedVideos.length > 0) {
        const queue = [...unindexedVideos];

        const worker = async () => {
          while (queue.length > 0) {
            if (superseded()) return;
            const video = queue.shift();
            if (!video) break;

            const txRes = await send({
              type: "fetch-transcript",
              videoId: video.id,
              preferredLangs: [...PREFERRED_TRANSCRIPT_LANGS],
            });
            if (superseded()) return;
            if (!txRes.ok || !txRes.data.transcript) {
              transcriptFailures++;
              const reason: FailureReason = !txRes.ok
                ? "unknown"
                : (txRes.data.failure_reason ?? "unknown");
              failureReasonCounts[reason] = (failureReasonCounts[reason] ?? 0) + 1;
              console.warn(
                `[ClipChase] transcript skipped for ${video.id}:`,
                txRes.ok ? `null (${reason})` : txRes.error,
              );
              continue;
            }
            const transcript = txRes.data.transcript;

            // Fire-and-forget: persist transcript to backend index so future
            // searches on this channel use the cached path. Failures here mean
            // cached-path stays cold — capture the error so we can spot a
            // broken indexer instead of just seeing low indexed_hits.
            if (resolvedChannelId) {
              void send({
                type: "index-transcript",
                params: {
                  channel_id: resolvedChannelId,
                  source_url: channelUrl,
                  video,
                  transcript,
                },
              }).then((res) => {
                if (!res.ok) {
                  posthog.capture("index_transcript_failed", {
                    channel_id: resolvedChannelId,
                    video_id: video.id,
                    error_message: res.error,
                  });
                }
              });
            }

            const matchRes = await send({
              type: "match-transcript",
              params: { keyword, video, transcript },
            });
            if (superseded()) return;

            if (matchRes.ok && matchRes.data.match_result) {
              matchCount++;
              setResults((prev) => [...prev, matchRes.data.match_result!]);
            }
          }
        };

        const workerCount = Math.min(UNINDEXED_FETCH_CONCURRENCY, unindexedVideos.length);
        await Promise.all(Array.from({ length: workerCount }, worker));
      }

      if (superseded()) return;
      if (!videosScanned) videosScanned = unindexedVideos.length + indexedHits;

      setLastSearch({ channel: channelUrl, keyword });
    } catch (err: unknown) {
      if (superseded()) return; // swallow errors from a superseded search
      // Abort fired by a newer search — caller already updated state, ignore.
      if (err instanceof DOMException && err.name === "AbortError") return;
      searchFailed = true;
      const message = err instanceof Error ? err.message : "Something went wrong. Please try again.";
      setError(message);
      posthog.capture("search_error", {
        channel: channelUrl,
        keyword,
        keyword_script: detectKeywordScript(keyword),
        error_message: message,
        duration_ms: Date.now() - searchStartedAt,
      });
      posthog.capture("error_shown", {
        surface: "search",
        error_message: message,
      });
    } finally {
      if (superseded()) {
        posthog.capture("search_cancelled", {
          channel: channelUrl,
          keyword,
          keyword_script: detectKeywordScript(keyword),
          duration_ms: Date.now() - searchStartedAt,
        });
      } else {
        setIsLoading(false);
        setHasSearched(true);
        // Transcript coverage tells us whether zero-result searches are caused
        // by transcript-pipeline gaps (low coverage) vs genuinely-rare keywords
        // (high coverage, still zero hits). Indexed videos are assumed to
        // already have transcripts, so failures only come from unindexed
        // local-fetch attempts.
        const videosWithTranscript = Math.max(0, videosScanned - transcriptFailures);
        const transcriptCoveragePct =
          videosScanned > 0
            ? Math.round((videosWithTranscript / videosScanned) * 1000) / 10
            : null;
        const hadAnyTranscript = videosWithTranscript > 0;
        const transcriptFailureReasonTop = dominantReason(failureReasonCounts);
        posthog.capture("search_completed", {
          channel: channelUrl,
          keyword,
          keyword_script: detectKeywordScript(keyword),
          time_range: timeRange,
          result_count: matchCount,
          indexed_hits: indexedHits,
          videos_scanned: videosScanned,
          videos_with_transcript: videosWithTranscript,
          transcript_failures: transcriptFailures,
          transcript_coverage_pct: transcriptCoveragePct,
          had_any_transcript: hadAnyTranscript,
          transcript_failure_reason_top: transcriptFailureReasonTop,
          success: !searchFailed,
          duration_ms: Date.now() - searchStartedAt,
        });
        const searchCount = parseInt(localStorage.getItem("searchCount") || "0") + 1;
        localStorage.setItem("searchCount", String(searchCount));
        if (searchCount === 3 && !localStorage.getItem("reviewPromptDismissed")) {
          setShowReviewPrompt(true);
        }
        if (matchCount === 0 && !searchFailed) {
          posthog.capture("zero_results", {
            channel: channelUrl,
            keyword,
            keyword_script: detectKeywordScript(keyword),
            time_range: timeRange,
            videos_scanned: videosScanned,
            videos_with_transcript: videosWithTranscript,
            transcript_failures: transcriptFailures,
            transcript_coverage_pct: transcriptCoveragePct,
            had_any_transcript: hadAnyTranscript,
            transcript_failure_reason_top: transcriptFailureReasonTop,
          });
          posthog.capture("zero_results_shown", {
            keyword_script: detectKeywordScript(keyword),
            had_any_transcript: hadAnyTranscript,
            transcript_failure_reason_top: transcriptFailureReasonTop,
          });
        } else if (matchCount > 0) {
          posthog.capture("results_shown", {
            result_count: matchCount,
            indexed_hits: indexedHits,
            had_any_transcript: hadAnyTranscript,
          });
        }
      }
    }
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!channelUrl && !keyword) {
      setFormError("Enter a channel and a keyword to search");
      posthog.capture("search_validation_error", { missing_field: "both" });
      return;
    }
    if (!channelUrl) {
      setFormError("Enter a YouTube channel URL or @handle");
      posthog.capture("search_validation_error", { missing_field: "channel" });
      return;
    }
    if (!keyword) {
      setFormError("Enter a keyword to search for");
      posthog.capture("search_validation_error", { missing_field: "keyword" });
      return;
    }
    setFormError("");
    await runSearch();
  };

  return (
    <main className="min-h-screen bg-yt-black text-yt-text selection:bg-yt-red/30 px-4 pt-5 pb-20">
      <AnimatePresence>
        {showWelcome && <WelcomeModal key="welcome" note={BUILDER_NOTE} onDismiss={handleDismissWelcome} />}
      </AnimatePresence>
      <div className="mb-4 flex items-center gap-2 pb-3 border-b border-yt-dark-gray">
        <div className="w-[22px] h-[22px] rounded-[5px] bg-yt-red flex items-center justify-center shrink-0">
          <Search className="w-3 h-3 text-white" strokeWidth={2.2} />
        </div>
        <span className="text-[13px] font-bold text-yt-text tracking-tight">ClipChase</span>
      </div>

      <SearchForm
        channelDisplay={channelDisplay}
        onChannelChange={handleChannelInputChange}
        onDismissSuggestions={handleDismissSuggestions}
        suggestions={suggestions}
        isSuggestionsLoading={isSuggestionsLoading}
        onSelectSuggestion={handleSelectSuggestion}
        keyword={keyword}
        setKeyword={handleKeywordChange}
        handleSearch={handleSearch}
        isLoading={isLoading}
        excludeShorts={excludeShorts}
        setExcludeShorts={setExcludeShorts}
        formError={formError}
      />

      <TimeRangeSelector
        timeRange={timeRange}
        setTimeRange={(range) => {
          posthog.capture("time_range_changed", { from: timeRange, to: range });
          setTimeRange(range);
        }}
      />

      {isLoading && <LoadingStream keyword={keyword} channel={channelDisplay} />}

      {error && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-5 p-4 rounded border border-yt-red/30 bg-yt-red/[0.08] text-yt-red"
        >
          <h3 className="font-semibold flex items-center gap-2 mb-1 text-xs">
            <span>⚠</span>
            Search failed
          </h3>
          <p className="text-[11px] leading-relaxed text-yt-red/80">{error}</p>
          <button
            type="button"
            onClick={runSearch}
            className="mt-3 text-[11px] font-semibold text-yt-red hover:text-white border border-yt-red/40 hover:border-yt-red hover:bg-yt-red px-3 py-2 rounded transition-all"
          >
            Try again
          </button>
        </motion.div>
      )}

      {hasSearched && !isLoading && !error && results.length === 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-10 flex flex-col items-center gap-2.5 text-center"
        >
          <Search className="w-7 h-7 text-yt-tert" strokeWidth={1.4} />
          <p className="text-[12px] text-yt-light-gray leading-relaxed max-w-xs">
            {lastSearch ? (
              <>
                No mentions of <span className="text-yt-text font-medium">&ldquo;{lastSearch.keyword}&rdquo;</span><br />
                in recent videos. Try a different keyword<br />or expand the time range.
              </>
            ) : (
              <>No results found.<br />Try a different keyword or time range.</>
            )}
          </p>
          <a
            href="https://tally.so/r/7RJQZA?source=ext_zero_results"
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => posthog.capture("feedback_link_clicked", { trigger: "zero_results" })}
            className="mt-2 text-[11px] text-yt-tert hover:text-yt-light-gray transition-colors underline underline-offset-2"
          >
            What were you looking for? →
          </a>
        </motion.div>
      )}

      {showReviewPrompt && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-5 p-4 rounded border border-yt-dark-gray bg-yt-gray flex items-start gap-3"
        >
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-yt-text mb-0.5">Enjoying ClipChase?</p>
            <p className="text-[11px] text-yt-light-gray leading-snug">A quick review helps others find it.</p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <a
              href="https://chromewebstore.google.com/detail/ojgacfpcibnmggkenjndnogpfglmhefn/reviews"
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => {
                posthog.capture("review_prompt_clicked");
                localStorage.setItem("reviewPromptDismissed", "1");
                setShowReviewPrompt(false);
              }}
              className="text-[11px] font-semibold text-yt-red hover:text-white transition-colors"
            >
              ⭐ Review
            </a>
            <button
              type="button"
              onClick={() => {
                posthog.capture("review_prompt_dismissed");
                localStorage.setItem("reviewPromptDismissed", "1");
                setShowReviewPrompt(false);
              }}
              className="text-yt-light-gray/40 hover:text-yt-light-gray text-xs transition-colors"
              aria-label="Dismiss"
            >
              ✕
            </button>
          </div>
        </motion.div>
      )}

      {results.length > 0 && (
        <div className="mt-5">
          <SearchResults
            results={results}
            sortBy={sortBy}
            onSortChange={(next) => {
              posthog.capture("sort_changed", { from: sortBy, to: next });
              setSortBy(next);
            }}
            onSelectVideo={(id, start) => {
              const position = results.findIndex((r) => r.video_id === id);
              chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
                const tab = tabs[0];
                if (tab?.id) {
                  posthog.capture("video_opened", {
                    video_id: id,
                    timestamp: start,
                    result_position: position,
                    keyword,
                    channel: channelUrl,
                  });
                  chrome.tabs.update(tab.id, {
                    url: `https://www.youtube.com/watch?v=${id}&t=${Math.floor(start)}s`,
                  });
                }
              });
            }}
          />
        </div>
      )}

      <div className="mt-10 pt-3 border-t border-yt-dark-gray flex justify-between items-center">
        <span className="font-mono text-[9px] text-yt-tert">v1.0</span>
        <div className="flex items-center gap-3">
          <a
            href="https://tally.so/r/7RJQZA?source=ext_footer"
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => posthog.capture("feedback_link_clicked", { trigger: "ext_footer" })}
            className="text-[9px] text-yt-tert hover:text-yt-light-gray transition-colors"
          >
            Feedback
          </a>
          <a
            href="https://clipchase.xyz"
            target="_blank"
            rel="noopener noreferrer"
            className="text-[9px] text-yt-tert hover:text-yt-light-gray transition-colors"
          >
            clipchase.xyz
          </a>
        </div>
      </div>
    </main>
  );
}
