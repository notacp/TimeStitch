import { motion, AnimatePresence } from "framer-motion";
import { Clock } from "lucide-react";
import { SearchResult } from "@/types";
import { formatTime } from "@/lib/utils";

interface SearchResultsProps {
    results: SearchResult[];
    onSelectVideo: (id: string, start: number) => void;
}

export function SearchResults({ results, onSelectVideo }: SearchResultsProps) {
    return (
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
                        <div className="flex flex-col sm:flex-row gap-4">
                            <img
                                src={video.thumbnail}
                                className="w-full sm:w-32 h-48 sm:h-20 object-cover rounded-lg"
                                alt={video.title}
                            />
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
                                    onClick={() => onSelectVideo(video.video_id, match.start)}
                                    className="w-full text-left p-3 rounded-lg hover:bg-white/5 flex items-start gap-3 transition-colors group/match"
                                >
                                    <div className="mt-1 bg-yt-gray p-1.5 rounded flex items-center gap-1 group-hover/match:bg-yt-red transition-colors text-xs font-mono shrink-0">
                                        <Clock className="w-3 h-3" />
                                        {formatTime(match.start)}
                                    </div>
                                    <p className="text-sm text-yt-light-gray group-hover/match:text-white transition-colors break-words">
                                        ...{match.context_before} <span className="text-white font-medium bg-yt-red/20 px-1 rounded">{match.text}</span> {match.context_after}...
                                    </p>
                                </button>
                            ))}
                        </div>
                    </motion.div>
                ))}
            </AnimatePresence>
        </div>
    );
}
