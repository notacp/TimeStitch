import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { TimeRange } from "@/types";

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

export function formatTime(seconds: number) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export function getPublishedAfterDate(range: TimeRange): string | null {
    if (range === "all") return null;
    const now = new Date();
    switch (range) {
        case "7d":
            now.setDate(now.getDate() - 7);
            break;
        case "30d":
            now.setDate(now.getDate() - 30);
            break;
        case "6m":
            now.setMonth(now.getMonth() - 6);
            break;
        case "1y":
            now.setFullYear(now.getFullYear() - 1);
            break;
    }
    return now.toISOString();
}
