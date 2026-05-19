import { describe, it, expect } from "vitest";
import { dominantReason } from "./utils";
import type { FailureReason } from "./types";

describe("dominantReason", () => {
  it("returns null for empty counts", () => {
    expect(dominantReason({})).toBeNull();
  });

  it("returns the only reason when one is present", () => {
    expect(dominantReason({ no_tab: 7 })).toBe("no_tab");
  });

  it("picks the reason with the highest count", () => {
    const counts: Partial<Record<FailureReason, number>> = {
      sw_no_tracks: 3,
      no_tab: 10,
      sw_blocked: 2,
    };
    expect(dominantReason(counts)).toBe("no_tab");
  });

  it("on tie, returns the first-inserted reason", () => {
    const counts: Partial<Record<FailureReason, number>> = {};
    counts.sw_no_tracks = 5;
    counts.no_tab = 5;
    expect(dominantReason(counts)).toBe("sw_no_tracks");
  });

  it("ignores zero-count entries", () => {
    expect(dominantReason({ sw_no_tracks: 0, no_tab: 1 })).toBe("no_tab");
  });

  it("treats no_tab with count 1 and parse_empty with count 1 deterministically by insertion", () => {
    const counts: Partial<Record<FailureReason, number>> = {};
    counts.parse_empty = 1;
    counts.no_tab = 1;
    expect(dominantReason(counts)).toBe("parse_empty");
  });
});
