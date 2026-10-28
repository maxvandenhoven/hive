import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  boardTransitionBetween,
  boardTransitionOf,
  useBoardTransition,
  type TransitionPosition,
} from "@/components/board/transition";
import type { BoardView } from "@/components/board/types";

const BOARD: BoardView = [
  { coord: [0, 0], pieces: [{ piece: "queen", owner: "white" }] },
  {
    coord: [1, 0],
    pieces: [
      { piece: "beetle", owner: "black" },
      { piece: "ant", owner: "white" },
    ],
  },
  { coord: [-1, 1], pieces: [{ piece: "spider", owner: "black" }] },
];

function position(ply: number, lastMove: TransitionPosition["lastMove"]) {
  return { ply, lastMove, board: BOARD };
}

const PLACEMENT = position(4, { piece: "spider", from: null, to: [-1, 1] });
const MOVE = position(5, { piece: "spider", from: [0, 1], to: [-1, 1] });
const CLIMB = position(6, { piece: "beetle", from: [1, -1], to: [1, 0] });

describe("boardTransitionOf", () => {
  it("tells placements, moves and climbs apart", () => {
    expect(boardTransitionOf(PLACEMENT)).toEqual({
      key: "4:hand>-1,1",
      kind: "place",
      piece: { piece: "spider", owner: "black" },
      from: null,
      to: [-1, 1],
    });
    expect(boardTransitionOf(MOVE)).toMatchObject({ kind: "move", from: [0, 1] });
    expect(boardTransitionOf(CLIMB)).toMatchObject({
      kind: "climb",
      piece: { piece: "beetle", owner: "black" },
    });
  });

  it("has nothing to animate after a pass or at the start", () => {
    expect(boardTransitionOf(position(3, null))).toBeNull();
    expect(boardTransitionOf(position(0, undefined))).toBeNull();
  });

  it("keys a transition by its ply and move", () => {
    expect(boardTransitionOf(MOVE)?.key).not.toBe(
      boardTransitionOf({ ...MOVE, ply: 7 })?.key,
    );
  });
});

describe("boardTransitionBetween", () => {
  it("animates a step forward by one ply", () => {
    expect(boardTransitionBetween(4, MOVE)).toEqual(boardTransitionOf(MOVE));
  });

  it("does not animate jumps, steps back or the first position", () => {
    expect(boardTransitionBetween(2, MOVE)).toBeNull();
    expect(boardTransitionBetween(6, MOVE)).toBeNull();
    expect(boardTransitionBetween(5, MOVE)).toBeNull();
    expect(boardTransitionBetween(null, MOVE)).toBeNull();
  });
});

describe("useBoardTransition", () => {
  function renderTransition(initial: TransitionPosition) {
    return renderHook((shown: TransitionPosition) => useBoardTransition(shown), {
      initialProps: initial,
    });
  }

  it("animates nothing when the board first shows", () => {
    const { result } = renderTransition(MOVE);

    expect(result.current).toBeNull();
  });

  it("animates a live move or a replay step forward, once", () => {
    const { result, rerender } = renderTransition(PLACEMENT);

    rerender(MOVE);
    const transition = result.current;

    expect(transition).toMatchObject({ kind: "move", key: "5:0,1>-1,1" });

    // The same ply again, for example after a refetch, keeps the same transition.
    rerender({ ...MOVE, board: [...BOARD] });

    expect(result.current).toBe(transition);
  });

  it("does not animate jumps, steps back or undo", () => {
    const { result, rerender } = renderTransition(PLACEMENT);

    rerender(CLIMB);
    expect(result.current).toBeNull();

    rerender(MOVE);
    expect(result.current).toBeNull();

    rerender(PLACEMENT);
    expect(result.current).toBeNull();
  });

  it("animates the move played again after an undo", () => {
    const { result, rerender } = renderTransition(PLACEMENT);

    rerender(MOVE);
    rerender(PLACEMENT);
    rerender(MOVE);

    expect(result.current).toMatchObject({ kind: "move" });
  });
});
