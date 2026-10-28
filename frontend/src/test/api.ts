import { vi } from "vitest";

/** A request the app sent, with its decoded JSON body. */
export interface RecordedRequest {
  method: string;
  path: string;
  search: string;
  body: unknown;
  /** The signal the request was sent with, which aborts it. */
  signal: AbortSignal | null;
}

/** A response by status and JSON body, or a whole response such as a stream. */
export type ApiHandler = (
  request: RecordedRequest,
) => { status?: number; body?: unknown } | Response;

/**
 * Replace `fetch` with handlers by `"METHOD /path"`, recording every request.
 *
 * Requests without a handler fail the test with a 500 response.
 */
export function mockApi(handlers: Record<string, ApiHandler>): RecordedRequest[] {
  const requests: RecordedRequest[] = [];

  vi.stubGlobal("fetch", async (input: Request, init?: RequestInit) => {
    const url = new URL(input.url);
    const text = await input.text();

    // Like `fetch`, a request aborted before its response fails.
    if (init?.signal?.aborted === true) {
      throw new DOMException("The request was aborted.", "AbortError");
    }

    const request: RecordedRequest = {
      method: input.method,
      path: url.pathname,
      search: url.search,
      body: text ? (JSON.parse(text) as unknown) : null,
      signal: init?.signal ?? null,
    };
    requests.push(request);
    const handler = handlers[`${request.method} ${request.path}`];

    if (handler === undefined) {
      return Response.json(
        { detail: `No handler for ${request.method} ${request.path}` },
        {
          status: 500,
        },
      );
    }

    const result = handler(request);

    if (result instanceof Response) {
      return result;
    }

    const { status = 200, body = null } = result;

    return status === 204
      ? new Response(null, { status })
      : Response.json(body, { status });
  });

  return requests;
}

/** The text of a server-sent event stream with one event per data object. */
export function serverSentEvents(events: unknown[]): string {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
}

/**
 * A server-sent event stream that the test writes to, for events that arrive over time.
 *
 * The stream fails once `signal` aborts, as a fetch response does.
 */
export function controlledEventStream(signal: AbortSignal | null = null) {
  let controller: ReadableStreamDefaultController<Uint8Array> | undefined;
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(streamController) {
      controller = streamController;
    },
  });
  signal?.addEventListener("abort", () => {
    controller?.error(new DOMException("The request was aborted.", "AbortError"));
  });

  return {
    response: new Response(stream, { headers: { "Content-Type": "text/event-stream" } }),
    send: (event: unknown) => {
      controller?.enqueue(encoder.encode(serverSentEvents([event])));
    },
    close: () => {
      controller?.close();
    },
  };
}
