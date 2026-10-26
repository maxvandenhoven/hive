import { ApiRequestError, type ThinkEvent, type ThinkRequest } from "@/api/client";

/**
 * Reads a server-sent event stream chunk by chunk, returning the data of each event.
 *
 * Follows the event stream format: lines end with `\n`, `\r\n` or `\r`, `data` lines of
 * one event are joined with newlines, and a blank line ends the event. Comments and the
 * other fields (`event`, `id`, `retry`) are ignored, since think events carry their type
 * in their data.
 */
export class ServerSentEventParser {
  /** The text after the last complete line, which the next chunk continues. */
  private pending = "";
  /** Whether the last chunk ended with `\r`, so a `\n` starting the next one is its pair. */
  private skipLineFeed = false;
  /** The data lines of the event being read. */
  private data: string[] = [];

  /** Add a chunk of the stream, returning the data of every event it completes. */
  push(chunk: string): string[] {
    const text = this.skipLineFeed && chunk.startsWith("\n") ? chunk.slice(1) : chunk;
    this.skipLineFeed = text.endsWith("\r");
    const lines = (this.pending + text).split(/\r\n|\n|\r/);
    this.pending = lines.pop() ?? "";
    const events: string[] = [];

    for (const line of lines) {
      if (line === "") {
        if (this.data.length > 0) {
          events.push(this.data.join("\n"));
          this.data = [];
        }
      } else if (line.startsWith("data:")) {
        const value = line.slice("data:".length);
        this.data.push(value.startsWith(" ") ? value.slice(1) : value);
      }
    }

    return events;
  }
}

async function readErrorBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

interface ThinkStreamOptions {
  gameId: string;
  body: ThinkRequest;
  /** Aborting closes the stream, which stops the agent; nothing is committed then. */
  signal: AbortSignal;
}

/**
 * Let an agent think about the latest position of a game, yielding the events of its
 * stream as they arrive: `info` and `candidate` events, then the `decision` or an
 * `error`.
 *
 * `EventSource` only supports GET, so the stream is read from `fetch`. A failed request
 * throws an `ApiRequestError`; an abort throws an `AbortError`.
 */
export async function* streamThinkEvents({
  gameId,
  body,
  signal,
}: ThinkStreamOptions): AsyncGenerator<ThinkEvent> {
  const url = new URL(
    `/api/games/${encodeURIComponent(gameId)}/think`,
    window.location.origin,
  );
  const request = new Request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
  });
  // The signal goes with the call rather than the request, which test environments
  // with their own `AbortSignal` would reject.
  const response = await globalThis.fetch(request, { signal });

  if (!response.ok) {
    throw new ApiRequestError(response.status, await readErrorBody(response));
  }

  if (response.body === null) {
    return;
  }

  const parser = new ServerSentEventParser();
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();

  try {
    for (;;) {
      const { done, value } = await reader.read();

      if (done) {
        return;
      }

      for (const data of parser.push(value)) {
        yield JSON.parse(data) as ThinkEvent;
      }
    }
  } finally {
    // Close the connection when the caller stops reading early.
    await reader.cancel().catch(() => undefined);
  }
}
