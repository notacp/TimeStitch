import type { ExtMessage, MessageResponse, VideoListResponse, MatchResponse, FetchTranscriptResult, IndexTranscriptResponse } from "./types";
import posthog from "./posthog";

/** Typed wrapper around chrome.runtime.sendMessage. */
export function send(msg: { type: "list-videos"; params: import("./types").VideoListParams }): Promise<MessageResponse<VideoListResponse>>;
export function send(msg: { type: "fetch-transcript"; videoId: string; preferredLangs: string[] }): Promise<MessageResponse<FetchTranscriptResult>>;
export function send(msg: { type: "match-transcript"; params: import("./types").MatchParams }): Promise<MessageResponse<MatchResponse>>;
export function send(msg: { type: "index-transcript"; params: import("./types").IndexTranscriptParams }): Promise<MessageResponse<IndexTranscriptResponse>>;
export function send(msg: ExtMessage): Promise<MessageResponse<unknown>> {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(msg, (response: MessageResponse<unknown>) => {
      if (chrome.runtime.lastError) {
        const errMsg = chrome.runtime.lastError.message ?? "Runtime error";
        // lastError here means the SW didn't respond — crashed, unloaded, or
        // never started. Critical Arc/Chrome-compat signal; surface it before
        // returning the soft error to the caller.
        posthog.capture("sw_message_failed", {
          message_type: msg.type,
          error_message: errMsg,
        });
        resolve({ ok: false, error: errMsg });
      } else {
        resolve(response);
      }
    });
  });
}
