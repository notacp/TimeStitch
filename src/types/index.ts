export interface Match {
    start: number;
    text: string;
    context_before: string;
    context_after: string;
}

export interface SearchResult {
    video_id: string;
    title: string;
    published_at: string;
    thumbnail: string;
    matches: Match[];
}

export type TimeRange = "7d" | "30d" | "6m" | "1y" | "all";
