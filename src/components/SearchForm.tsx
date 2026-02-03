import { motion } from "framer-motion";
import { Search, Youtube } from "lucide-react";
import { FormEvent } from "react";

interface SearchFormProps {
    channelUrl: string;
    setChannelUrl: (url: string) => void;
    keyword: string;
    setKeyword: (keyword: string) => void;
    handleSearch: (e: FormEvent) => void;
    isLoading: boolean;
}

export function SearchForm({
    channelUrl,
    setChannelUrl,
    keyword,
    setKeyword,
    handleSearch,
    isLoading,
}: SearchFormProps) {
    return (
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
                className="bg-yt-red hover:bg-yt-red/90 disabled:opacity-50 disabled:cursor-not-allowed text-white px-8 py-4 rounded-xl font-semibold flex items-center justify-center gap-2 transition-all active:scale-95 md:w-auto w-full"
            >
                {isLoading ? (
                    <div className="w-5 h-5 border-2 border-white/20 border-t-white rounded-full animate-spin" />
                ) : (
                    <>
                        <Search className="w-5 h-5" />
                        <span className="md:hidden">Search</span>
                        <span className="hidden md:inline">Search</span>
                    </>
                )}
            </button>
        </motion.form>
    );
}
