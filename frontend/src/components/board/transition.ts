/*
 * The transition contract of the board renderers: which move to animate, derived from
 * the position shown and independent of how a renderer draws it.
 */
import { useState } from "react";

import type { Move } from "@/api/client";
import { hexKey } from "@/components/board/hex";
import type { BoardTransition, BoardView } from "@/components/board/types";

/** A position shown on the board, as far as transitions need it. */
export interface TransitionPosition {
  /** The number of moves played to reach the position. */
  ply: number;
  /** The move that led to it, `null` after a pass or at the start. */
  lastMove: Move | null | undefined;
  /** The board of the position, top piece first. */
  board: BoardView;
}

/**
 * The transition of the move that led to `position`, or `null` when there is nothing to
 * animate (a pass, the start, or a move whose piece is not on the board).
 */
export function boardTransitionOf(position: TransitionPosition): BoardTransition | null {
  const { ply, lastMove, board } = position;

  if (lastMove == null) {
    return null;
  }

  const stack = board.find(
    (candidate) => hexKey(candidate.coord) === hexKey(lastMove.to),
  );
  const piece = stack?.pieces[0];

  if (stack === undefined || piece === undefined) {
    return null;
  }

  const kind =
    lastMove.from === null ? "place" : stack.pieces.length > 1 ? "climb" : "move";
  const source = lastMove.from === null ? "hand" : hexKey(lastMove.from);
  const route = `${source}>${hexKey(lastMove.to)}`;

  return { key: `${ply}:${route}`, kind, piece, from: lastMove.from, to: lastMove.to };
}

/**
 * The transition to animate when the board changes from the position at `previousPly`
 * to `position`: the move that led to it if the ply advanced by exactly one, otherwise
 * `null`, so jumps, steps back and undo show the new position without travel.
 */
export function boardTransitionBetween(
  previousPly: number | null,
  position: TransitionPosition,
): BoardTransition | null {
  return previousPly !== null && position.ply === previousPly + 1
    ? boardTransitionOf(position)
    : null;
}

interface TrackedTransition {
  ply: number;
  transition: BoardTransition | null;
}

/**
 * The transition for the position shown, following its ply from render to render: a
 * step forward by one ply sets it, any other change of ply clears it, and it stays the
 * same while the ply does. The first position shown has none.
 */
export function useBoardTransition(position: TransitionPosition): BoardTransition | null {
  const [tracked, setTracked] = useState<TrackedTransition>({
    ply: position.ply,
    transition: null,
  });

  if (tracked.ply === position.ply) {
    return tracked.transition;
  }

  // Derived from the previous ply during render, so the board and its transition change
  // in the same frame.
  const transition = boardTransitionBetween(tracked.ply, position);
  setTracked({ ply: position.ply, transition });

  return transition;
}
