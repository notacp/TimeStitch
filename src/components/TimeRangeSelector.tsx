import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { TimeRange } from "@/types";

interface TimeRangeSelectorProps {
    timeRange: TimeRange;
    setTimeRange: (range: TimeRange) => void;
}

const TIME_RANGES: { value: TimeRange; label: string }[] = [
    { value: "7d", label: "Last 7 days" },
    { value: "30d", label: "Last 30 days" },
    { value: "6m", label: "Last 6 months" },
    { value: "1y", label: "Last year" },
    { value: "all", label: "All time" },
];

export function TimeRangeSelector({ timeRange, setTimeRange }: TimeRangeSelectorProps) {
    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
            className="flex flex-wrap items-center justify-center gap-2 mt-6"
        >
            <span className="text-yt-light-gray text-sm mr-2 w-full sm:w-auto text-center">Search videos from:</span>
            {TIME_RANGES.map((range) => (
                <button
                    key={range.value}
                    type="button"
                    onClick={() => setTimeRange(range.value)}
                    className={cn(
                        "px-4 py-2 rounded-full text-sm font-medium transition-all",
                        timeRange === range.value
                            ? "bg-yt-red text-white"
                            : "bg-white/5 text-yt-light-gray hover:bg-white/10 hover:text-white"
                    )}
                >
                    {range.label}
                </button>
            ))}
        </motion.div>
    );
}
