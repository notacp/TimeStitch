import { Youtube } from "lucide-react";

export function Header() {
    return (
        <nav className="relative z-10 flex items-center justify-between p-6 max-w-7xl mx-auto">
            <div className="flex items-center gap-2 group cursor-pointer">
                <Youtube className="w-8 h-8 text-yt-red group-hover:scale-110 transition-transform" />
                <span className="text-xl font-bold tracking-tight">TimeStitch</span>
            </div>
        </nav>
    );
}
