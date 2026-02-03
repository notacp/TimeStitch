import { motion } from "framer-motion";
import { Play } from "lucide-react";

interface VideoPlayerProps {
    selectedVideo: { id: string; start: number } | null;
}

export function VideoPlayer({ selectedVideo }: VideoPlayerProps) {
    return (
        <div className="lg:sticky lg:top-24 h-fit">
            {selectedVideo ? (
                <motion.div
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    key={selectedVideo.id + selectedVideo.start} // Re-animate on change
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
    );
}
