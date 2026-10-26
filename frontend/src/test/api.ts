import { vi } from "vitest";

/** A request the app sent, with its decoded JSON body. */
export interface RecordedRequest {
  method: string;
  path: string;
  search: string;
  body: unknown;
}

type ApiHandler = (request: RecordedRequest) => { status?: number; body?: unknown };

/**
 * Replace `fetch` with handlers by `"METHOD /path"`, recording every request.
 *
 * Requests without a handler fail the test with a 500 response.
 */
export function mockApi(handlers: Record<string, ApiHandler>): RecordedRequest[] {
  const requests: RecordedRequest[] = [];

  vi.stubGlobal("fetch", async (input: Request) => {
    const url = new URL(input.url);
    const text = await input.text();
    const request: RecordedRequest = {
      method: input.method,
      path: url.pathname,
      search: url.search,
      body: text ? (JSON.parse(text) as unknown) : null,
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

    const { status = 200, body = null } = handler(request);

    return status === 204
      ? new Response(null, { status })
      : Response.json(body, { status });
  });

  return requests;
}
