export function BackgroundEffect() {
    return (
        <div className="fixed inset-0 overflow-hidden pointer-events-none opacity-20">
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[1000px] h-[1000px] bg-yt-red/10 rounded-full blur-[120px]" />
        </div>
    );
}
