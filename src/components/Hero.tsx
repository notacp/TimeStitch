import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

interface HeroProps {
    isCompact: boolean;
    children?: React.ReactNode;
}

export function Hero({ isCompact, children }: HeroProps) {
    return (
        <div className={cn(
            "flex flex-col items-center transition-all duration-700",
            isCompact ? "pt-0" : "pt-20"
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
                className="text-yt-light-gray text-lg md:text-xl text-center mb-12 max-w-2xl px-4"
            >
                Search inside any channel's videos for specific words and jump directly to the moment they're spoken.
            </motion.p>
            {children}
        </div>
    );
}
