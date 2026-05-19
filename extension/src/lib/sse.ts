// Minimal SSE consumer over fetch streaming. EventSource has limitations
// (no abort signal, no custom events on body errors), so we parse manually.

export interface SSEHandlers {
  onMessage?: (data: string) => void;
  onEvent?: (event: string, data: string) => void;
  signal?: AbortSignal;
  /**
   * Abort if no bytes arrive for this long. Without it a stalled server (or a
   * buffering proxy) leaves reader.read() pending forever — only a *new*
   * search breaks it, so the spinner runs indefinitely. The server emits
   * `meta` immediately then streams per-video; sustained total silence past
   * this means the stream is dead.
   */
  idleMs?: number;
}

const DEFAULT_IDLE_MS = 45_000;

export async function consumeSSE(url: string, handlers: SSEHandlers): Promise<void> {
  const idleMs = handlers.idleMs ?? DEFAULT_IDLE_MS;

  // Internal controller fires on idle timeout; combine with the caller's
  // signal so either a new search OR a stalled stream cancels the fetch —
  // aborting the fetch is what makes a pending reader.read() reject.
  const idleController = new AbortController();
  const signals = [idleController.signal];
  if (handlers.signal) signals.push(handlers.signal);
  const combined = signals.length === 1 ? signals[0] : AbortSignal.any(signals);

  let idleTimer: ReturnType<typeof setTimeout> | undefined;
  const armIdle = () => {
    if (idleTimer !== undefined) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => idleController.abort(), idleMs);
  };

  try {
    // Arm BEFORE fetch: a server that accepts the socket but never sends
    // response headers hangs `await fetch` forever, and the timer wouldn't
    // exist yet to break it. The connect phase is the same "waits forever"
    // class as a mid-stream stall.
    armIdle();

    let res: Response;
    try {
      res = await fetch(url, { signal: combined });
    } catch (e) {
      if (idleController.signal.aborted) throw new Error("SSE idle timeout");
      throw e;
    }
    if (!res.ok || !res.body) throw new Error(`SSE ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    armIdle(); // headers arrived — reset before streaming
    while (true) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch (e) {
        // Idle abort surfaces here as an AbortError — rethrow a clear signal
        // so the caller shows an error and stops the spinner instead of
        // hanging. A caller-initiated (new search) abort rethrows as-is.
        if (idleController.signal.aborted) throw new Error("SSE idle timeout");
        throw e;
      }
      if (chunk.done) break;
      armIdle(); // bytes arrived — reset the deadman

      buffer += decoder.decode(chunk.value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        dispatch(block, handlers);
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    if (idleTimer !== undefined) clearTimeout(idleTimer);
  }
}

function dispatch(block: string, handlers: SSEHandlers): void {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    // ignore comments/id/retry
  }
  const data = dataLines.join("\n");
  if (event === "message") handlers.onMessage?.(data);
  else handlers.onEvent?.(event, data);
}
