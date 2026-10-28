import { useEffect, useState } from "react";

import type { GameDetail, GamePosition, HintAgent, Move } from "@/api/client";
import { streamThinkEvents } from "@/api/sse";

/**
 * Where the hint for the latest position stands: `hidden` until asked for, `thinking`
 * while the hint agent searches, then `shown` with its move (`null` to pass) or
 * `failed`.
 */
export type HintState =
  | { type: "hidden" }
  | {
      type: "thinking";
      /** When the stream started, or `null` while it is being opened. */
      startedAt: number | null;
    }
  | { type: "shown"; move: Move | null }
  | { type: "failed"; message: string };

/** What a finished hint request for a ply found. */
type HintOutcome =
  | { ply: number; type: "shown"; move: Move | null }
  | { ply: number; type: "failed"; message: string };

interface HintOptions {
  game: GameDetail;
  /** The latest position. */
  position: GamePosition;
}

export interface Hint {
  /**
   * The hint agent of the side to move, or `null` when no hint can be asked for now:
   * that side has none, it is an agent's turn, a move is pending or the game is over.
   */
  agent: HintAgent | null;
  state: HintState;
  /** Ask for a hint, or hide the hint (stopping its search) when it is asked for. */
  toggle: () => void;
}

/**
 * The hint for a person's turn (D26): hidden until asked for, then `POST /think` with
 * `commit=false` for the side to move, which uses that side's hint agent and budget.
 *
 * A hint belongs to one position: playing or undoing a move clears it. Hiding it, a new
 * position or closing the page aborts a search under way. Hints never change the game.
 */
export function useHint({ game, position }: HintOptions): Hint {
  const ply = position.ply_count;
  const player = game[position.current_player];
  const agent =
    game.status === "active" &&
    position.result === null &&
    !position.pending_move &&
    player.type === "human"
      ? (player.hint ?? null)
      : null;
  const [askedPly, setAskedPly] = useState<number | null>(null);
  const [outcome, setOutcome] = useState<HintOutcome | null>(null);
  const [startedAt, setStartedAt] = useState<{ ply: number; at: number } | null>(null);
  const [seenPly, setSeenPly] = useState(ply);

  // Any move, including an undo back to the same ply, clears the hint.
  if (seenPly !== ply) {
    setSeenPly(ply);
    setAskedPly(null);
    setOutcome(null);
  }

  const asked = agent !== null && askedPly === ply;
  const done = outcome?.ply === ply;
  const wantsToThink = asked && !done;

  useEffect(() => {
    if (!wantsToThink) {
      return;
    }

    const controller = new AbortController();

    const think = async () => {
      try {
        const events = streamThinkEvents({
          gameId: game.id,
          body: { commit: false },
          signal: controller.signal,
        });
        setStartedAt({ ply, at: Date.now() });

        for await (const event of events) {
          if (event.type === "decision") {
            setOutcome({ ply, type: "shown", move: event.decision.move });

            return;
          }

          if (event.type === "error") {
            setOutcome({ ply, type: "failed", message: event.detail });

            return;
          }
        }

        setOutcome({ ply, type: "failed", message: "The hint agent did not decide." });
      } catch (error) {
        if (!controller.signal.aborted) {
          const message =
            error instanceof Error ? error.message : "The hint agent could not think.";
          setOutcome({ ply, type: "failed", message });
        }
      }
    };

    void think();

    return () => {
      controller.abort();
    };
  }, [wantsToThink, ply, game.id]);

  let state: HintState = { type: "hidden" };

  if (asked && outcome?.ply === ply) {
    state =
      outcome.type === "shown"
        ? { type: "shown", move: outcome.move }
        : { type: "failed", message: outcome.message };
  } else if (asked) {
    state = { type: "thinking", startedAt: startedAt?.ply === ply ? startedAt.at : null };
  }

  return {
    agent,
    state,
    toggle: () => {
      if (askedPly === ply) {
        setAskedPly(null);

        // A failed hint is asked for again next time.
        if (outcome?.type === "failed") {
          setOutcome(null);
        }
      } else {
        setAskedPly(ply);
      }
    },
  };
}
