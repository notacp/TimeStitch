// Minimal PostHog capture for the service worker.
//
// posthog-js can't run in an SW (no window/localStorage). The SDK is only used
// in the side panel; here we POST events to /capture/ ourselves. Stable_id is
// shared with the panel via chrome.storage.local so events from both surfaces
// resolve to the same person in PostHog.

const POSTHOG_KEY = import.meta.env.VITE_POSTHOG_KEY as string | undefined;
const POSTHOG_HOST = import.meta.env.VITE_POSTHOG_HOST as string | undefined;
const STABLE_ID_KEY = "clipchase_stable_id";

async function getStableId(): Promise<string> {
  const stored = await chrome.storage.local.get(STABLE_ID_KEY);
  if (stored[STABLE_ID_KEY]) return stored[STABLE_ID_KEY] as string;
  const id = `cc_${crypto.randomUUID()}`;
  await chrome.storage.local.set({ [STABLE_ID_KEY]: id });
  return id;
}

function extVersion(): string {
  return chrome?.runtime?.getManifest?.().version ?? "unknown";
}

export async function captureSW(
  event: string,
  properties: Record<string, unknown> = {},
): Promise<void> {
  if (!POSTHOG_KEY || !POSTHOG_HOST) return;
  try {
    const distinctId = await getStableId();
    // PostHog's public capture endpoint. `/i/v0/e/` is the *internal* batched
    // ingest path used by posthog-js; the single-event REST shape is /capture/.
    await fetch(`${POSTHOG_HOST}/capture/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: POSTHOG_KEY,
        event,
        distinct_id: distinctId,
        properties: {
          app: "extension",
          surface: "background",
          extension_version: extVersion(),
          ...properties,
        },
        timestamp: new Date().toISOString(),
      }),
    });
  } catch {
    // Swallow — telemetry must never break the extension.
  }
}

export function captureExceptionSW(
  err: unknown,
  extra: Record<string, unknown> = {},
): void {
  const error = err instanceof Error ? err : new Error(String(err));
  void captureSW("$exception", {
    $exception_list: [
      {
        type: error.name || "Error",
        value: error.message,
        stacktrace: error.stack
          ? { type: "raw", frames: [{ raw: error.stack }] }
          : undefined,
      },
    ],
    $exception_level: "error",
    $exception_handled: true,
    ...extra,
  });
}
