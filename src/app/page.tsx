"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { SearchResult, TimeRange } from "@/types";
import { getPublishedAfterDate } from "@/lib/utils";
import { Header } from "@/components/Header";
import { Hero } from "@/components/Hero";
import { SearchForm } from "@/components/SearchForm";
import { TimeRangeSelector } from "@/components/TimeRangeSelector";
import { SearchResults } from "@/components/SearchResults";
import { VideoPlayer } from "@/components/VideoPlayer";
import { BackgroundEffect } from "@/components/BackgroundEffect";

export default function Home() {
  const [channelUrl, setChannelUrl] = useState("");
  const [keyword, setKeyword] = useState("");
  const [timeRange, setTimeRange] = useState<TimeRange>("30d");
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState("");
  const [selectedVideo, setSelectedVideo] = useState<{ id: string; start: number } | null>(null);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!channelUrl || !keyword) return;

    setIsLoading(true);
    setError("");
    setResults([]);
    setSelectedVideo(null); // Reset selection on new search

    try {
      const publishedAfter = getPublishedAfterDate(timeRange);
      let url = `/api/search?channel_url=${encodeURIComponent(channelUrl)}&keyword=${encodeURIComponent(keyword)}&max_videos=20`;
      if (publishedAfter) {
        url += `&published_after=${encodeURIComponent(publishedAfter)}`;
      }
      const response = await fetch(url);

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Search failed");
      }

      const data = await response.json();
      setResults(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-yt-black text-white selection:bg-yt-red/30 pb-20">
      <BackgroundEffect />
      <Header />

      <div className="relative z-10 max-w-7xl mx-auto px-6 py-20">
        <Hero isCompact={results.length > 0}>
          <SearchForm
            channelUrl={channelUrl}
            setChannelUrl={setChannelUrl}
            keyword={keyword}
            setKeyword={setKeyword}
            handleSearch={handleSearch}
            isLoading={isLoading}
          />
          <TimeRangeSelector timeRange={timeRange} setTimeRange={setTimeRange} />

          {error && (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-yt-red mt-4 font-medium"
            >
              {error}
            </motion.p>
          )}
        </Hero>

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
