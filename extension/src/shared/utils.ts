import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { FailureReason } from "./types";
import { TimeRange } from "./types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatTime(seconds: number) {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

// Returns the FailureReason with the highest count, or null when no failures.
// Tie-break: insertion order (Object.entries iterates in insertion order).
export function dominantReason(
  counts: Partial<Record<FailureReason, number>>,
): FailureReason | null {
  let top: FailureReason | null = null;
  let topCount = 0;
  for (const [reason, count] of Object.entries(counts) as [FailureReason, number][]) {
    if (count > topCount) {
      top = reason;
      topCount = count;
    }
  }
  return top;
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
