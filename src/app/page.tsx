"use client";

import { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import { SearchResult, TimeRange, ChannelSuggestion } from "@/types";
import { getPublishedAfterDate } from "@/lib/utils";
import { Header } from "@/components/Header";
import { Hero } from "@/components/Hero";
import { SearchForm } from "@/components/SearchForm";
import { TimeRangeSelector } from "@/components/TimeRangeSelector";
import { SearchResults } from "@/components/SearchResults";
import { VideoPlayer } from "@/components/VideoPlayer";
import { BackgroundEffect } from "@/components/BackgroundEffect";

export default function Home() {
  const [channelUrl, setChannelUrl] = useState("");       // resolved value sent to API
  const [channelDisplay, setChannelDisplay] = useState(""); // what's shown in the input
  const [suggestions, setSuggestions] = useState<ChannelSuggestion[]>([]);
  const [keyword, setKeyword] = useState("");
  const [timeRange, setTimeRange] = useState<TimeRange>("30d");
  const [excludeShorts, setExcludeShorts] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState("");
  const [selectedVideo, setSelectedVideo] = useState<{ id: string; start: number } | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [lastSearch, setLastSearch] = useState<{ channel: string; keyword: string } | null>(null);

  useEffect(() => {
    if (channelDisplay.length < 2) {
      setSuggestions([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/suggest-channels?q=${encodeURIComponent(channelDisplay)}`);
        if (res.ok) setSuggestions(await res.json());
      } catch {
        // suggestions are best-effort, ignore errors
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [channelDisplay]);

  const handleSelectSuggestion = (suggestion: ChannelSuggestion) => {
    setChannelDisplay(suggestion.title);
    setChannelUrl(suggestion.id);
    setSuggestions([]);
  };

  const handleDismissSuggestions = () => setSuggestions([]);

  const handleChannelInputChange = (value: string) => {
    setChannelDisplay(value);
    setChannelUrl(value); // keep in sync while user is typing manually
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!channelUrl || !keyword) return;

    setIsLoading(true);
    setError("");
    setErrorStatus(null);
    setResults([]);
    setSelectedVideo(null);
    setHasSearched(false);
    setSuggestions([]);

    try {
      const publishedAfter = getPublishedAfterDate(timeRange);
      let url = `/api/search?channel_url=${encodeURIComponent(channelUrl)}&keyword=${encodeURIComponent(keyword)}&max_videos=20`;
      if (publishedAfter) {
        url += `&published_after=${encodeURIComponent(publishedAfter)}`;
      }
      if (excludeShorts) {
        url += `&exclude_shorts=true`;
      }
      const response = await fetch(url);

      if (!response.ok) {
        setErrorStatus(response.status);
        const errorData = await response.json();
        throw new Error(errorData.detail || "Search failed");
      }

      const data = await response.json();
      setResults(data);
      setLastSearch({ channel: channelUrl, keyword });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
      setHasSearched(true);
    }
  };

  return (
    <main className="min-h-screen bg-yt-black text-white selection:bg-yt-red/30 pb-20">
      <BackgroundEffect />
      <Header />

      <div className="relative z-10 max-w-7xl mx-auto px-6 py-20">
        <Hero isCompact={results.length > 0 || (hasSearched && !isLoading)}>
          <SearchForm
            channelDisplay={channelDisplay}
            onChannelChange={handleChannelInputChange}
            onDismissSuggestions={handleDismissSuggestions}
            suggestions={suggestions}
            onSelectSuggestion={handleSelectSuggestion}
            keyword={keyword}
            setKeyword={setKeyword}
            handleSearch={handleSearch}
            isLoading={isLoading}
            excludeShorts={excludeShorts}
            setExcludeShorts={setExcludeShorts}
          />
          <TimeRangeSelector timeRange={timeRange} setTimeRange={setTimeRange} />

          {isLoading && (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="mt-4 text-sm text-yt-light-gray text-center"
            >
              Scanning videos for &ldquo;{keyword}&rdquo;… this may take up to 30 seconds
            </motion.p>
          )}

          {error && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-6 p-4 rounded-xl border border-yt-red/20 bg-yt-red/10 text-yt-red"
            >
              <h3 className="font-bold flex items-center gap-2 mb-2">
                <span className="text-xl">⚠️</span>
                {errorStatus === 403 || errorStatus === 502
                  ? "Something went wrong on our end"
                  : errorStatus === 400
                  ? "Channel not found"
                  : "Search failed"}
              </h3>
              <p className="font-medium text-sm leading-relaxed text-yt-red/80">
                {errorStatus === 403 || errorStatus === 502
                  ? "YouTube is temporarily blocking our server. This usually resolves itself — try again in a few minutes."
                  : errorStatus === 400
                  ? "We couldn't find that YouTube channel. Double-check the URL or @handle and try again."
                  : "Something went wrong. Please try again."}
              </p>
            </motion.div>
          )}
        </Hero>

        {/* Empty state */}
        {hasSearched && !isLoading && !error && results.length === 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-16 text-center"
          >
            <div className="text-5xl mb-4">🔍</div>
            <h3 className="text-xl font-semibold text-white mb-2">No mentions found</h3>
            <p className="text-yt-light-gray text-sm max-w-md mx-auto">
              {lastSearch
                ? <>Couldn&apos;t find <span className="text-white font-medium">&ldquo;{lastSearch.keyword}&rdquo;</span> in any recent videos from this channel. Try a different keyword or expand the time range.</>
                : "No results found. Try a different keyword or expand the time range."}
            </p>
            <ul className="mt-4 text-yt-light-gray text-sm space-y-1">
              <li>• Make sure the keyword spelling is correct</li>
              <li>• Try a broader time range (e.g. &ldquo;All time&rdquo;)</li>
              <li>• The channel may not have transcripts enabled</li>
            </ul>
          </motion.div>
        )}

        {/* Results Section */}
        {results.length > 0 && (
          <div className="mt-20 grid grid-cols-1 lg:grid-cols-2 gap-12">
            <SearchResults
              results={results}
              onSelectVideo={(id, start) => setSelectedVideo({ id, start })}
            />
            <VideoPlayer selectedVideo={selectedVideo} />
          </div>
        )}
      </div>
    </main>
  );
}
