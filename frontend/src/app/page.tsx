"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Search, Youtube, Clock, ExternalLink, Play } from "lucide-react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

interface Match {
  start: number;
  text: string;
  context_before: string;
  context_after: string;
}

interface SearchResult {
  video_id: string;
  title: string;
  published_at: string;
  thumbnail: string;
  matches: Match[];
}

export default function Home() {
  const [channelUrl, setChannelUrl] = useState("");
  const [keyword, setKeyword] = useState("");
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

    try {
      const response = await fetch(
        `/api/search?channel_url=${encodeURIComponent(channelUrl)}&keyword=${encodeURIComponent(keyword)}&max_videos=10`
      );

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

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <main className="min-h-screen bg-yt-black text-white selection:bg-yt-red/30">
      {/* Background Effect */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none opacity-20">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[1000px] h-[1000px] bg-yt-red/10 rounded-full blur-[120px]" />
      </div>

      <nav className="relative z-10 flex items-center justify-between p-6 max-w-7xl mx-auto">
        <div className="flex items-center gap-2 group cursor-pointer">
          <Youtube className="w-8 h-8 text-yt-red group-hover:scale-110 transition-transform" />
          <span className="text-xl font-bold tracking-tight">TimeStitch</span>
        </div>
      </nav>

      <div className="relative z-10 max-w-7xl mx-auto px-6 py-20">
        {/* Hero Section */}
        <div className={cn(
          "flex flex-col items-center transition-all duration-700",
          results.length > 0 ? "pt-0" : "pt-20"
        )}>
          <motion.h1
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-5xl md:text-7xl font-bold text-center mb-6 tracking-tight"
          >
            Ctrl+F for <span className="text-yt-red">YouTube</span>
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="text-yt-light-gray text-lg md:text-xl text-center mb-12 max-w-2xl"
          >
            Search inside any channel's videos for specific words and jump directly to the moment they're spoken.
          </motion.p>

          {/* Search Bar */}
          <motion.form
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.2 }}
            onSubmit={handleSearch}
            className="w-full max-w-3xl glass p-2 rounded-2xl flex flex-col md:flex-row gap-2"
          >
            <div className="flex-1 relative">
              <input
                type="text"
                placeholder="YouTube Channel URL or @handle"
                value={channelUrl}
                onChange={(e) => setChannelUrl(e.target.value)}
                className="w-full bg-transparent p-4 pl-12 outline-none focus:ring-0 text-white placeholder:text-yt-light-gray"
              />
              <Youtube className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-yt-light-gray" />
            </div>
            <div className="w-[1px] bg-white/10 hidden md:block" />
            <div className="flex-1 relative">
              <input
                type="text"
                placeholder="Keyword to find..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                className="w-full bg-transparent p-4 pl-12 outline-none focus:ring-0 text-white placeholder:text-yt-light-gray"
              />
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-yt-light-gray" />
            </div>
            <button
              disabled={isLoading}
              className="bg-yt-red hover:bg-yt-red/90 disabled:opacity-50 disabled:cursor-not-allowed text-white px-8 py-4 rounded-xl font-semibold flex items-center justify-center gap-2 transition-all active:scale-95"
            >
              {isLoading ? (
                <div className="w-5 h-5 border-2 border-white/20 border-t-white rounded-full animate-spin" />
              ) : (
                <>
                  <Search className="w-5 h-5" />
                  Search
                </>
              )}
            </button>
          </motion.form>

          {error && (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-yt-red mt-4 font-medium"
            >
              {error}
            </motion.p>
          )}
        </div>

        {/* Results Section */}
        <div className="mt-20 grid grid-cols-1 lg:grid-cols-2 gap-12">
          <div className="space-y-6">
            <AnimatePresence>
              {results.map((video, idx) => (
                <motion.div
                  key={video.video_id}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: idx * 0.1 }}
                  className="glass p-6 rounded-2xl group hover:border-yt-red/50 transition-colors"
                >
                  <div className="flex gap-4">
                    <img src={video.thumbnail} className="w-32 h-20 object-cover rounded-lg" alt={video.title} />
                    <div className="flex-1">
                      <h3 className="font-bold text-lg leading-tight group-hover:text-yt-red transition-colors line-clamp-2">
                        {video.title}
                      </h3>
                      <p className="text-yt-light-gray text-sm mt-1">
                        {new Date(video.published_at).toLocaleDateString()}
                      </p>
                    </div>
                  </div>

                  <div className="mt-4 space-y-2">
                    {video.matches.map((match, mIdx) => (
                      <button
                        key={mIdx}
                        onClick={() => setSelectedVideo({ id: video.video_id, start: match.start })}
                        className="w-full text-left p-3 rounded-lg hover:bg-white/5 flex items-start gap-3 transition-colors group/match"
                      >
                        <div className="mt-1 bg-yt-gray p-1.5 rounded flex items-center gap-1 group-hover/match:bg-yt-red transition-colors text-xs font-mono">
                          <Clock className="w-3 h-3" />
                          {formatTime(match.start)}
                        </div>
                        <p className="text-sm text-yt-light-gray group-hover/match:text-white transition-colors">
                          ...{match.context_before} <span className="text-white font-medium bg-yt-red/20 px-1 rounded">{match.text}</span> {match.context_after}...
                        </p>
                      </button>
                    ))}
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>

          {/* Sticky Video Player */}
          <div className="lg:sticky lg:top-24 h-fit">
            {selectedVideo ? (
              <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                className="glass p-4 rounded-3xl aspect-video relative overflow-hidden"
              >
                <iframe
                  className="w-full h-full rounded-2xl"
                  src={`https://www.youtube.com/embed/${selectedVideo.id}?start=${Math.floor(selectedVideo.start)}&autoplay=1`}
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                  allowFullScreen
                ></iframe>
              </motion.div>
            ) : (
              <div className="glass p-12 rounded-3xl aspect-video flex flex-col items-center justify-center text-center">
                <Play className="w-16 h-16 text-yt-light-gray/20 mb-4" />
                <p className="text-yt-light-gray">Select a timestamp to start playing</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
