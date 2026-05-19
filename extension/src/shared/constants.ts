// Shared constants across the side panel and the background service worker.
// Adding a new transcript language is a one-line change here; everywhere else
// imports this list.

export const PREFERRED_TRANSCRIPT_LANGS = ["en", "hi", "fr", "es", "pt"] as const;
