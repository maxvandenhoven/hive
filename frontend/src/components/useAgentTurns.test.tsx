import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GameDetail, GamePosition, Move, ThinkEvent } from "@/api/client";
import { useGamePosition } from "@/api/queries";
import { agentTurnReducer, useAgentTurns } from "@/components/useAgentTurns";
import {
  type ApiHandler,
  controlledEventStream,
  mockApi,
  type RecordedRequest,
} from "@/test/api";
import { gameDetail, gamePosition } from "@/test/fixtures";
import { renderQueryHook } from "@/test/render";

const GAME = gameDetail();
const GAME_PATH = `/api/games/${GAME.id}`;
const THINK = `POST ${GAME_PATH}/think`;
const MATCH = gameDetail({
  white: { type: "agent", spec: { kind: "random", params: {} }, budget_s: 1 },
});

/** The position with black, the agent, to move at ply 3. */
const BLACK_TO_MOVE = gamePosition({ ply: 3, ply_count: 3, current_player: "black" });
/** The position after black's move, with white to move at ply 4. */
const WHITE_TO_MOVE = gamePosition({ ply: 4, ply_count: 4 });
const MOVE: Move = { piece: "ant", from: null, to: [2, 0] };

function decision(position: GamePosition | null): ThinkEvent {
  return {
    type: "decision",
    decision: {
      ply: 3,
      player: "black",
      agent_label: "negamax",
      seed: 1,
      budget_s: 5,
      elapsed_s: 1.2,
      overrun_s: 0,
      close_reason: "final",
      candidates: 2,
      illegal_submissions: 0,
      move: { piece: "ant", from: null, to: [2, 0] },
      worker_restarted: false,
    },
    position,
  };
}

interface TurnsProps {
  game: GameDetail;
  /** The latest position until the query has loaded it. */
  position: GamePosition;
  idle: boolean;
}

/**
 * Serve thinking streams that the test writes to, one per request, the latest position,
 * which starts as `initial`, and any `extra` routes.
 */
function mockThinking(
  initial: GamePosition = BLACK_TO_MOVE,
  extra: Record<string, ApiHandler> = {},
) {
  const streams: ReturnType<typeof controlledEventStream>[] = [];
  const requests = mockApi({
    [THINK]: ({ signal }) => {
      const stream = controlledEventStream(signal);
      streams.push(stream);

      return stream.response;
    },
    [`GET ${GAME_PATH}/state`]: () => ({ body: initial }),
    ...extra,
  });

  return { streams, requests };
}

function thinkRequests(requests: RecordedRequest[]): RecordedRequest[] {
  return requests.filter((request) => request.path.endsWith("/think"));
}

/** Render the hook with the latest position from its query, as the game page does. */
function renderTurns(initialProps: Partial<TurnsProps> = {}) {
  return renderQueryHook(
    (props: TurnsProps) => {
      const latest = useGamePosition(props.game.id);

      return useAgentTurns({ ...props, position: latest.data ?? props.position });
    },
    {
      initialProps: { game: GAME, position: BLACK_TO_MOVE, idle: true, ...initialProps },
    },
  );
}

describe("useAgentTurns in a human game", () => {
  it("lets the agent think, streams its search and waits for Done", async () => {
    const { streams, requests } = mockThinking();
    const { result } = renderTurns();

    expect(result.current.mode).toBe("human");
    expect(result.current.state).toMatchObject({ type: "thinking", ply: 3 });
    await waitFor(() => {
      expect(streams).toHaveLength(1);
    });
    expect(thinkRequests(requests)[0]?.body).toEqual({ commit: true });

    act(() => {
      streams[0]?.send({ type: "info", info: { depth: 2, score: 1.5 } });
      streams[0]?.send({ type: "candidate", move: MOVE, final: false });
    });

    await waitFor(() => {
      expect(result.current.state).toMatchObject({
        type: "thinking",
        info: { depth: 2, score: 1.5 },
        candidate: MOVE,
      });
    });

    act(() => {
      streams[0]?.send(decision(WHITE_TO_MOVE));
    });
    await waitFor(() => {
      expect(result.current.state).toMatchObject({
        type: "committed",
        ply: 4,
        move: MOVE,
      });
    });
    expect(result.current.awaitingDone).toBe(true);
    expect(result.current.agent).toBeNull();

    act(() => {
      result.current.done();
    });

    expect(result.current.awaitingDone).toBe(false);
    expect(result.current.state).toEqual({ type: "idle" });
    expect(thinkRequests(requests)).toHaveLength(1);
  });

  it("confirms a pending move with Done", async () => {
    const pending = { ...WHITE_TO_MOVE, pending_move: true };
    const { streams, requests } = mockThinking(BLACK_TO_MOVE, {
      [`POST ${GAME_PATH}/moves/last/confirm`]: () => ({ body: WHITE_TO_MOVE }),
    });
    const { result } = renderTurns();

    await waitFor(() => {
      expect(streams).toHaveLength(1);
    });
    act(() => {
      streams[0]?.send(decision(pending));
    });
    await waitFor(() => {
      expect(result.current.awaitingDone).toBe(true);
    });

    act(() => {
      result.current.done();
    });

    await waitFor(() => {
      expect(requests.filter((request) => request.path.endsWith("/confirm"))).toEqual([
        expect.objectContaining({ method: "POST", body: { expected_ply: 4 } }),
      ]);
    });
  });

  it("does not think on a person's turn", () => {
    const { requests } = mockThinking(gamePosition());
    const { result } = renderTurns({ position: gamePosition() });

    expect(result.current.state).toEqual({ type: "idle" });
    expect(result.current.agent).toBeNull();
    expect(thinkRequests(requests)).toEqual([]);
  });

  it("reports a request that failed and thinks again on retry", async () => {
    let attempts = 0;
    mockApi({
      [THINK]: () => {
        attempts++;

        return {
          status: 503,
          body: { code: "pool_busy", detail: "Every agent is busy." },
        };
      },
      [`GET ${GAME_PATH}/state`]: () => ({ body: BLACK_TO_MOVE }),
    });
    const { result } = renderTurns();

    await waitFor(() => {
      expect(result.current.state).toEqual({
        type: "failed",
        ply: 3,
        message: "Every agent is busy.",
      });
    });
    expect(await screen.findByText("Every agent is busy.")).toBeInTheDocument();

    act(() => {
      result.current.retry();
    });

    await waitFor(() => {
      expect(attempts).toBe(2);
    });
  });

  it("reports a decision that could not be committed", async () => {
    const { streams } = mockThinking();
    const { result } = renderTurns();
    await waitFor(() => {
      expect(streams).toHaveLength(1);
    });

    act(() => {
      streams[0]?.send(decision(null));
      streams[0]?.send({
        type: "error",
        code: "ply_conflict",
        detail: "The game is at ply 4, not 3.",
      });
    });

    await waitFor(() => {
      expect(result.current.state).toMatchObject({
        type: "failed",
        message: "The game is at ply 4, not 3.",
      });
    });
  });

  it("stops the agent when the page closes or another write starts", async () => {
    const { streams, requests } = mockThinking();
    const { result, rerender, unmount } = renderTurns();
    await waitFor(() => {
      expect(streams).toHaveLength(1);
    });

    rerender({ game: GAME, position: BLACK_TO_MOVE, idle: false });

    expect(thinkRequests(requests)[0]?.signal?.aborted).toBe(true);
    await waitFor(() => {
      expect(result.current.state).toEqual({ type: "idle" });
    });

    rerender({ game: GAME, position: BLACK_TO_MOVE, idle: true });
    await waitFor(() => {
      expect(streams).toHaveLength(2);
    });
    unmount();

    expect(thinkRequests(requests)[1]?.signal?.aborted).toBe(true);
  });
});

describe("useAgentTurns in a match", () => {
  it("waits for play, then plays on after the delay", async () => {
    const { streams } = mockThinking();
    const { result } = renderTurns({ game: MATCH });

    expect(result.current.mode).toBe("match");
    expect(result.current.state).toEqual({ type: "idle" });

    act(() => {
      result.current.setDelayS(0);
      result.current.setAutoplay(true);
    });
    await waitFor(() => {
      expect(streams).toHaveLength(1);
    });
    act(() => {
      streams[0]?.send(decision(WHITE_TO_MOVE));
    });
    await waitFor(() => {
      expect(streams).toHaveLength(2);
    });
    expect(result.current.awaitingDone).toBe(false);
    expect(result.current.state).toMatchObject({ type: "thinking", ply: 4 });
  });

  it("plays one move per step", async () => {
    const { streams } = mockThinking();
    const { result } = renderTurns({ game: MATCH });

    act(() => {
      result.current.setDelayS(0);
      result.current.step();
    });
    await waitFor(() => {
      expect(streams).toHaveLength(1);
    });
    act(() => {
      streams[0]?.send(decision(WHITE_TO_MOVE));
    });
    await waitFor(() => {
      expect(result.current.state).toEqual({ type: "idle" });
    });
    expect(result.current.agent).toEqual(MATCH.white);
    expect(streams).toHaveLength(1);
  });

  it("stops the thinking agent on pause", async () => {
    const { streams, requests } = mockThinking();
    const { result } = renderTurns({ game: MATCH });

    act(() => {
      result.current.setAutoplay(true);
    });
    await waitFor(() => {
      expect(streams).toHaveLength(1);
    });
    act(() => {
      result.current.setAutoplay(false);
    });

    expect(thinkRequests(requests)[0]?.signal?.aborted).toBe(true);
    await waitFor(() => {
      expect(result.current.state).toEqual({ type: "idle" });
    });
  });
});

describe("agentTurnReducer", () => {
  it("ignores reports of another ply", () => {
    const thinking = agentTurnReducer(
      { type: "idle" },
      { type: "started", ply: 3, startedAt: 0 },
    );

    expect(agentTurnReducer(thinking, { type: "info", ply: 2, info: { depth: 1 } })).toBe(
      thinking,
    );
    expect(agentTurnReducer(thinking, { type: "stopped", ply: 2 })).toBe(thinking);
    expect(agentTurnReducer(thinking, { type: "stopped", ply: 3 })).toEqual({
      type: "idle",
    });
  });
});
