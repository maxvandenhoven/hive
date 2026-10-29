import { describe, expect, it } from "vitest";

import { BOARD_MARKS, boardMarksShown } from "@/components/board/boardMarks";
import type { BoardMarkProps } from "@/components/board/boardMarks";

const EMPTY: BoardMarkProps = {
  board: [{ coord: [0, 0], pieces: [{ piece: "queen", owner: "white" }] }],
  highlights: [],
  movable: [],
  selected: null,
  lastMove: null,
  proposedMove: null,
};

describe("boardMarksShown", () => {
  it("finds no marks on a plain board", () => {
    expect(boardMarksShown(EMPTY)).toEqual([]);
  });

  it("finds every mark but movable with a suggestion, in legend order", () => {
    expect(
      boardMarksShown({
        ...EMPTY,
        highlights: [
          [0, 0],
          [1, 0],
        ],
        movable: [[0, 0]],
        selected: [0, 0],
        lastMove: { from: null, to: [0, 0] },
        proposedMove: { from: [0, 0], to: [1, 0] },
        forbidden: [[2, 0]],
      }),
    ).toEqual(BOARD_MARKS.map(({ kind }) => kind).filter((kind) => kind !== "movable"));
    expect(boardMarksShown({ ...EMPTY, movable: [[0, 0]] })).toEqual(["movable"]);
  });

  it("tells targets on empty hexes from climbs onto tiles", () => {
    expect(boardMarksShown({ ...EMPTY, highlights: [[1, 0]] })).toEqual(["target"]);
    expect(boardMarksShown({ ...EMPTY, highlights: [[0, 0]] })).toEqual(["climb"]);
  });
});
