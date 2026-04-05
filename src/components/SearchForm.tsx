import { motion, AnimatePresence } from "framer-motion";
import { Search, Youtube } from "lucide-react";
import { FormEvent, useRef, useEffect } from "react";
import { ChannelSuggestion } from "@/types";

interface SearchFormProps {
    channelDisplay: string;
    onChannelChange: (value: string) => void;
    onDismissSuggestions: () => void;
    suggestions: ChannelSuggestion[];
    onSelectSuggestion: (suggestion: ChannelSuggestion) => void;
    keyword: string;
    setKeyword: (keyword: string) => void;
    handleSearch: (e: FormEvent) => void;
    isLoading: boolean;
    excludeShorts: boolean;
    setExcludeShorts: (v: boolean) => void;
}

export function SearchForm({
    channelDisplay,
    onChannelChange,
    onDismissSuggestions,
    suggestions,
    onSelectSuggestion,
    keyword,
    setKeyword,
    handleSearch,
    isLoading,
    excludeShorts,
    setExcludeShorts,
}: SearchFormProps) {
    const containerRef = useRef<HTMLDivElement>(null);

    // Close suggestions when clicking outside
    useEffect(() => {
        function handleClickOutside(e: MouseEvent) {
            if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
                onDismissSuggestions();
            }
        }
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, [onDismissSuggestions]);

    return (
        <motion.form
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.2 }}
            onSubmit={handleSearch}
            className="w-full max-w-3xl flex flex-col md:flex-row gap-2"
        >
            {/* Channel input with suggestions */}
            <div className="flex-1 relative" ref={containerRef}>
                <div className="glass p-2 rounded-2xl flex items-center">
                    <Youtube className="ml-3 w-5 h-5 text-yt-light-gray shrink-0" />
                    <input
                        type="text"
                        placeholder="YouTube Channel URL or @handle"
                        value={channelDisplay}
                        onChange={(e) => onChannelChange(e.target.value)}
                        autoComplete="off"
                        className="w-full bg-transparent p-3 pl-3 outline-none focus:ring-0 text-white placeholder:text-yt-light-gray"
                    />
                </div>

                <AnimatePresence>
                    {suggestions.length > 0 && (
                        <motion.ul
                            initial={{ opacity: 0, y: -4 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -4 }}
                            transition={{ duration: 0.15 }}
                            className="absolute z-50 top-full mt-1 w-full glass rounded-xl overflow-hidden border border-white/10 shadow-xl"
                        >
                            {suggestions.map((s) => (
                                <li key={s.id}>
                                    <button
                                        type="button"
                                        onMouseDown={(e) => {
                                            e.preventDefault(); // prevent input blur before click registers
                                            onSelectSuggestion(s);
                                        }}
                                        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/10 transition-colors text-left"
                                    >
                                        {s.thumbnail ? (
                                            <img
                                                src={s.thumbnail}
                                                alt={s.title}
                                                className="w-8 h-8 rounded-full object-cover shrink-0"
                                            />
                                        ) : (
                                            <div className="w-8 h-8 rounded-full bg-white/10 shrink-0" />
                                        )}
                                        <span className="text-sm text-white truncate">{s.title}</span>
                                    </button>
                                </li>
                            ))}
                        </motion.ul>
                    )}
                </AnimatePresence>
            </div>

            {/* Keyword input + controls */}
            <div className="flex-1 glass p-2 rounded-2xl flex items-center md:flex-1">
                <Search className="ml-3 w-5 h-5 text-yt-light-gray shrink-0" />
                <input
                    type="text"
                    placeholder="Keyword to find..."
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                    className="flex-1 bg-transparent p-3 pl-3 outline-none focus:ring-0 text-white placeholder:text-yt-light-gray"
                />
                <label className="flex items-center gap-2 px-3 cursor-pointer select-none text-sm text-yt-light-gray whitespace-nowrap shrink-0">
                    <input
                        type="checkbox"
                        checked={excludeShorts}
                        onChange={(e) => setExcludeShorts(e.target.checked)}
                        className="accent-yt-red w-4 h-4"
                    />
                    No Shorts
                </label>
            </div>

            <button
                disabled={isLoading}
                className="bg-yt-red hover:bg-yt-red/90 disabled:opacity-50 disabled:cursor-not-allowed text-white px-8 py-4 rounded-xl font-semibold flex items-center justify-center gap-2 transition-all active:scale-95 md:w-auto w-full"
            >
                {isLoading ? (
                    <div className="w-5 h-5 border-2 border-white/20 border-t-white rounded-full animate-spin" />
                ) : (
                    <>
                        <Search className="w-5 h-5" />
                        <span>Search</span>
                    </>
                )}
            </button>
        </motion.form>
    );
}
