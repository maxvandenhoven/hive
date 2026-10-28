import { useCallback, useEffect, useReducer, useState } from "react";
import { toast } from "sonner";

import type { AgentPlayer, GameDetail, GamePosition, Move } from "@/api/client";
import { useConfirmMove, useRefreshGame, useStoreLatestPosition } from "@/api/queries";
import { streamThinkEvents } from "@/api/sse";
import type { ThinkInfo } from "@/lib/search";

/**
 * How agent turns run: in a `human` game an agent answers each person's move (to be made
 * on the table and confirmed in a `table` game); in a `match` (agent vs agent) moves
 * follow each other while playing.
 */
export type AgentTurnMode = "human" | "match";

/**
 * Where the agent turn at a ply stands.
 *
 * `ply` is the `ply_count` the state belongs to: the position the agent thinks about,
 * or the position after the committed move. States of other plies do not apply.
 */
export type AgentTurnState =
  | { type: "idle" }
  | {
      type: "thinking";
      ply: number;
      /** When the stream started, or `null` while it is being opened. */
      startedAt: number | null;
      info: ThinkInfo | null;
      /** The agent's current answer, `null` to pass, or `undefined` before the first. */
      candidate: Move | null | undefined;
    }
  | { type: "committed"; ply: number; move: Move | null; info: ThinkInfo | null }
  | { type: "failed"; ply: number; message: string };

export type AgentTurnAction =
  | { type: "started"; ply: number; startedAt: number }
  | { type: "info"; ply: number; info: ThinkInfo }
  | { type: "candidate"; ply: number; move: Move | null }
  | { type: "committed"; ply: number; move: Move | null }
  | { type: "failed"; ply: number; message: string }
  | { type: "stopped"; ply: number }
  | { type: "continued" };

/**
 * The next agent turn state: a stream starts, reports and ends in a committed move or a
 * failure; continuing (after the delay of a match or a retry) returns to idle.
 */
export function agentTurnReducer(
  state: AgentTurnState,
  action: AgentTurnAction,
): AgentTurnState {
  const thinkingAt =
    state.type === "thinking" && "ply" in action && state.ply === action.ply
      ? state
      : null;

  switch (action.type) {
    case "started":
      return {
        type: "thinking",
        ply: action.ply,
        startedAt: action.startedAt,
        info: null,
        candidate: undefined,
      };
    case "info":
      return thinkingAt === null ? state : { ...thinkingAt, info: action.info };
    case "candidate":
      return thinkingAt === null ? state : { ...thinkingAt, candidate: action.move };
    case "committed":
      return {
        type: "committed",
        ply: action.ply + 1,
        move: action.move,
        info: thinkingAt?.info ?? null,
      };
    case "failed":
      return { type: "failed", ply: action.ply, message: action.message };
    case "stopped":
      return thinkingAt === null ? state : { type: "idle" };
    case "continued":
      return { type: "idle" };
  }
}

interface AgentTurnsOptions {
  game: GameDetail;
  /** The latest position. */
  position: GamePosition;
  /** Whether no other write is under way, such as a move or undo being sent. */
  idle: boolean;
}

export interface AgentTurns {
  mode: AgentTurnMode;
  /** The state of the latest position. */
  state: AgentTurnState;
  /** The agent to move, or `null` on a person's turn and once the game is over. */
  agent: AgentPlayer | null;
  /**
   * Whether the last move is an agent move that waits for a person to make it on the
   * table and press **Done**: the stored pending move of a `table` game, so it survives
   * a reload.
   */
  awaitingDone: boolean;
  /** Whether **Done** is being sent. */
  confirming: boolean;
  /** Whether a match plays on by itself; human games always do. */
  autoplay: boolean;
  /** The pause between the moves of a match in seconds. */
  delayS: number;
  setAutoplay: (autoplay: boolean) => void;
  setDelayS: (delayS: number) => void;
  /** Let the agent to move in a paused match play one move. */
  step: () => void;
  /** Confirm that the pending agent move was made on the table. */
  done: () => void;
  /** Think again after a failure. */
  retry: () => void;
}

/**
 * Agent turns: when an agent is to move, it thinks with `commit=true`, streaming its
 * search, and its move is stored in the game.
 *
 * On the screen the person plays on at once. At the table the API stores the move as
 * pending (D27), and the person plays once they made it on the table and pressed
 * **Done**, which confirms it; this follows the stored position, so it survives a
 * reload. A match plays on while `autoplay` is set, waiting `delayS` between moves, or one move
 * per `step`. The stream is closed, which stops the agent without committing, when the
 * page closes, a match pauses or another write starts.
 */
export function useAgentTurns({ game, position, idle }: AgentTurnsOptions): AgentTurns {
  const storeLatestPosition = useStoreLatestPosition(game.id);
  const refreshGame = useRefreshGame(game.id);
  const confirmMove = useConfirmMove(game.id);
  const [state, dispatch] = useReducer(agentTurnReducer, { type: "idle" });
  const [autoplay, setAutoplay] = useState(false);
  const [stepPending, setStepPending] = useState(false);
  const [delayS, setDelayS] = useState(1);
  const mode: AgentTurnMode =
    game.white.type === "agent" && game.black.type === "agent" ? "match" : "human";
  const ply = position.ply_count;
  const player = game[position.current_player];
  const agent =
    game.status === "active" && position.result === null && player.type === "agent"
      ? player
      : null;
  const current = state.type !== "idle" && state.ply === ply ? state : null;
  const blocked = current?.type === "committed" || current?.type === "failed";
  const allowed = mode === "human" || autoplay || stepPending;
  const wantsToThink = agent !== null && idle && !blocked && allowed;
  const cooling = mode === "match" && current?.type === "committed";

  const think = useCallback(
    async (thinkPly: number, signal: AbortSignal) => {
      const fail = (message: string) => {
        dispatch({ type: "failed", ply: thinkPly, message });
        toast.error(message);
        void refreshGame();
      };

      let committed: GamePosition | null = null;

      try {
        const events = streamThinkEvents({
          gameId: game.id,
          body: { commit: true },
          signal,
        });
        dispatch({ type: "started", ply: thinkPly, startedAt: Date.now() });

        for await (const event of events) {
          if (event.type === "info") {
            dispatch({ type: "info", ply: thinkPly, info: event.info });
          } else if (event.type === "candidate") {
            dispatch({ type: "candidate", ply: thinkPly, move: event.move });
          } else if (event.type === "decision" && event.position !== null) {
            dispatch({ type: "committed", ply: thinkPly, move: event.decision.move });
            committed = event.position;
            break;
          } else if (event.type === "error") {
            fail(event.detail);

            return;
          }
        }
      } catch (error) {
        if (signal.aborted) {
          dispatch({ type: "stopped", ply: thinkPly });
        } else {
          fail(error instanceof Error ? error.message : "The agent could not think.");
        }

        return;
      }

      if (committed === null) {
        fail("The agent stopped without a decision.");

        return;
      }

      setStepPending(false);
      await storeLatestPosition(committed);
    },
    [game.id, storeLatestPosition, refreshGame],
  );

  useEffect(() => {
    if (!wantsToThink) {
      return;
    }

    const controller = new AbortController();
    void think(ply, controller.signal);

    return () => {
      controller.abort();
    };
  }, [wantsToThink, ply, think]);

  // A match waits between moves, so they can be followed.
  useEffect(() => {
    if (!cooling) {
      return;
    }

    const timeout = setTimeout(() => {
      dispatch({ type: "continued" });
    }, delayS * 1000);

    return () => {
      clearTimeout(timeout);
    };
  }, [cooling, ply, delayS]);

  return {
    mode,
    state:
      current ??
      (wantsToThink
        ? { type: "thinking", ply, startedAt: null, info: null, candidate: undefined }
        : { type: "idle" }),
    agent,
    awaitingDone: position.pending_move,
    confirming: confirmMove.isPending,
    autoplay,
    delayS,
    setAutoplay: (next) => {
      setAutoplay(next);
      setStepPending(false);
    },
    setDelayS,
    step: () => {
      setStepPending(true);
    },
    done: () => {
      if (position.pending_move) {
        confirmMove.mutate(ply, {
          onError: (error) => {
            toast.error(error.message);
          },
        });
      }
    },
    retry: () => {
      dispatch({ type: "continued" });
    },
  };
}
