import { describe, expect, it, vi } from "vitest";

import { ApiRequestError, type ThinkEvent } from "@/api/client";
import { ServerSentEventParser, streamThinkEvents } from "@/api/sse";
import { controlledEventStream, mockApi, serverSentEvents } from "@/test/api";

const THINK = "POST /api/games/g1/think";
const INFO: ThinkEvent = { type: "info", info: { depth: 1, score: 2.5 } };
const CANDIDATE: ThinkEvent = {
  type: "candidate",
  move: { piece: "ant", from: null, to: [1, 0] },
  final: false,
};

async function collect(events: AsyncIterable<ThinkEvent>): Promise<ThinkEvent[]> {
  const collected: ThinkEvent[] = [];

  for await (const event of events) {
    collected.push(event);
  }

  return collected;
}

describe("ServerSentEventParser", () => {
  it("returns the data of each complete event", () => {
    const parser = new ServerSentEventParser();

    expect(parser.push("data: one\n\ndata: two\n\nda")).toEqual(["one", "two"]);
    expect(parser.push("ta: three\n")).toEqual([]);
    expect(parser.push("\n")).toEqual(["three"]);
  });

  it("joins data lines and ignores comments and other fields", () => {
    const parser = new ServerSentEventParser();

    expect(
      parser.push(": ping\nevent: info\nid: 3\ndata: first\ndata:second\nretry: 5\n\n"),
    ).toEqual(["first\nsecond"]);
    expect(parser.push(": ping\n\n")).toEqual([]);
  });

  it("accepts carriage returns, also split across chunks", () => {
    const parser = new ServerSentEventParser();

    expect(parser.push("data: a\r\ndata: b\r")).toEqual([]);
    expect(parser.push("\n\r\ndata: c\r\r")).toEqual(["a\nb", "c"]);
  });

  it("keeps the spaces after the first one", () => {
    expect(new ServerSentEventParser().push("data:   padded \n\n")).toEqual([
      "  padded ",
    ]);
  });
});

describe("streamThinkEvents", () => {
  it("posts the request and yields the events", async () => {
    const requests = mockApi({
      [THINK]: () =>
        new Response(serverSentEvents([INFO, CANDIDATE]), {
          headers: { "Content-Type": "text/event-stream" },
        }),
    });

    const events = await collect(
      streamThinkEvents({
        gameId: "g1",
        body: { commit: true },
        signal: new AbortController().signal,
      }),
    );

    expect(events).toEqual([INFO, CANDIDATE]);
    expect(requests[0]?.body).toEqual({ commit: true });
  });

  it("yields events as they arrive", async () => {
    let stream: ReturnType<typeof controlledEventStream> | undefined;
    mockApi({
      [THINK]: () => {
        stream = controlledEventStream();

        return stream.response;
      },
    });
    const events = streamThinkEvents({
      gameId: "g1",
      body: { commit: false },
      signal: new AbortController().signal,
    });

    const first = events.next();
    await vi.waitFor(() => {
      expect(stream).toBeDefined();
    });
    stream?.send(INFO);

    expect((await first).value).toEqual(INFO);

    stream?.close();

    expect((await events.next()).done).toBe(true);
  });

  it("throws the error of a failed request", async () => {
    mockApi({
      [THINK]: () => ({
        status: 503,
        body: { code: "pool_busy", detail: "Every agent is busy." },
      }),
    });

    const failure = collect(
      streamThinkEvents({
        gameId: "g1",
        body: { commit: true },
        signal: new AbortController().signal,
      }),
    );

    await expect(failure).rejects.toThrow(ApiRequestError);
    await expect(failure).rejects.toMatchObject({
      code: "pool_busy",
      message: "Every agent is busy.",
    });
  });

  it("stops when the signal aborts", async () => {
    mockApi({ [THINK]: ({ signal }) => controlledEventStream(signal).response });
    const controller = new AbortController();
    const events = collect(
      streamThinkEvents({
        gameId: "g1",
        body: { commit: true },
        signal: controller.signal,
      }),
    );

    controller.abort();

    await expect(events).rejects.toMatchObject({ name: "AbortError" });
  });
});
