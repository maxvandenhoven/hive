import { describe, expect, it } from "vitest";

import type { Move } from "@/api/client";
import {
  boardBeforeMove,
  describeMove,
  describeMoveOnBoard,
  listPieces,
  playerAtPly,
  toBoardView,
  toMoveView,
} from "@/lib/moves";
import { gameDetail, RULES } from "@/test/fixtures";

describe("describeMove", () => {
  it("describes placements, movements and passes", () => {
    expect(describeMove({ piece: "ant", from: null, to: [1, -1] })).toBe(
      "Place ant at (1, -1)",
    );
    expect(describeMove({ piece: "grasshopper", from: [0, 0], to: [3, 0] })).toBe(
      "Move grasshopper from (0, 0) to (3, 0)",
    );
    expect(describeMove(null)).toBe("Pass");
  });
});

describe("playerAtPly", () => {
  it("alternates from the starting player", () => {
    const game = gameDetail();

    expect([0, 1, 2, 3].map((ply) => playerAtPly(game, ply))).toEqual([
      "white",
      "black",
      "white",
      "black",
    ]);
  });

  it("starts with the starting player of the rules", () => {
    const game = gameDetail({ rules: { ...RULES, starting_player: "black" } });

    expect(playerAtPly(game, 0)).toBe("black");
  });

  it("starts with the side to move of a board setup", () => {
    const game = gameDetail({ setup: { board: [], current_player: "black" } });

    expect(playerAtPly(game, 0)).toBe("black");
    expect(playerAtPly(game, 1)).toBe("white");
  });
});

describe("toBoardView", () => {
  it("puts the top piece of each stack first", () => {
    const view = toBoardView([
      {
        coord: [0, 0],
        stack: [
          { piece: "queen", owner: "black" },
          { piece: "beetle", owner: "white" },
        ],
      },
    ]);

    expect(view).toEqual([
      {
        coord: [0, 0],
        pieces: [
          { piece: "beetle", owner: "white" },
          { piece: "queen", owner: "black" },
        ],
      },
    ]);
  });
});

describe("toMoveView", () => {
  it("marks the coordinates of a move", () => {
    expect(toMoveView({ piece: "ant", from: [0, 1], to: [2, 0] })).toEqual({
      from: [0, 1],
      to: [2, 0],
    });
  });

  it("marks nothing without a move or after a pass", () => {
    expect(toMoveView(undefined)).toBeNull();
    expect(toMoveView(null)).toBeNull();
  });
});

describe("describeMoveOnBoard", () => {
  /** White queen at the origin, black queen east of it, a white ant and a black beetle. */
  const board = toBoardView([
    { coord: [0, 0], stack: [{ piece: "queen", owner: "white" }] },
    { coord: [1, 0], stack: [{ piece: "queen", owner: "black" }] },
    { coord: [-1, 0], stack: [{ piece: "ant", owner: "white" }] },
    { coord: [2, 0], stack: [{ piece: "beetle", owner: "black" }] },
  ]);

  it("describes a placement by the pieces next to it", () => {
    expect(describeMoveOnBoard({ piece: "spider", from: null, to: [-1, 1] }, board)).toBe(
      "place spider next to the white queen and the white ant",
    );
    expect(describeMoveOnBoard({ piece: "ant", from: null, to: [0, 0] }, [])).toBe(
      "place ant as the first piece",
    );
  });

  it("describes a movement without the piece that moves", () => {
    expect(describeMoveOnBoard({ piece: "ant", from: [-1, 0], to: [1, 1] }, board)).toBe(
      "ant moves next to the black queen and the black beetle",
    );
  });

  it("describes climbing, climbing down and jumping", () => {
    expect(
      describeMoveOnBoard({ piece: "beetle", from: [2, 0], to: [1, 0] }, board),
    ).toBe("beetle climbs onto the black queen");

    const stacked = toBoardView([
      { coord: [0, 0], stack: [{ piece: "queen", owner: "white" }] },
      {
        coord: [1, 0],
        stack: [
          { piece: "queen", owner: "black" },
          { piece: "beetle", owner: "black" },
        ],
      },
    ]);
    expect(
      describeMoveOnBoard({ piece: "beetle", from: [1, 0], to: [1, -1] }, stacked),
    ).toBe("beetle climbs down next to the white queen and the black queen");

    const line = toBoardView([
      { coord: [0, 0], stack: [{ piece: "grasshopper", owner: "white" }] },
      { coord: [1, 0], stack: [{ piece: "queen", owner: "white" }] },
      { coord: [2, 0], stack: [{ piece: "ant", owner: "black" }] },
    ]);
    expect(
      describeMoveOnBoard({ piece: "grasshopper", from: [0, 0], to: [3, 0] }, line),
    ).toBe("grasshopper jumps over the white queen and the black ant");
  });

  it("tells a piece apart from its twins by where it stands", () => {
    const twins = toBoardView([
      ...board.map((stack) => ({ coord: stack.coord, stack: [...stack.pieces] })),
      { coord: [3, 0], stack: [{ piece: "ant", owner: "white" }] },
    ]);

    expect(describeMoveOnBoard({ piece: "ant", from: [-1, 0], to: [0, 1] }, twins)).toBe(
      "ant beside the white queen moves next to the white queen and the black queen",
    );
  });

  it("counts identical neighbours and passes", () => {
    expect(
      listPieces([
        { piece: "ant", owner: "black" },
        { piece: "queen", owner: "black" },
        { piece: "ant", owner: "black" },
        { piece: "beetle", owner: "white" },
      ]),
    ).toBe("the white beetle, the black queen and two black ants");
    expect(describeMoveOnBoard(null, board)).toBe("pass");
  });

  it("is the same before a move and from the board after it", () => {
    const move: Move = { piece: "ant", from: [-1, 0], to: [1, 1] };
    const after = toBoardView([
      { coord: [0, 0], stack: [{ piece: "queen", owner: "white" }] },
      { coord: [1, 0], stack: [{ piece: "queen", owner: "black" }] },
      { coord: [2, 0], stack: [{ piece: "beetle", owner: "black" }] },
      { coord: [1, 1], stack: [{ piece: "ant", owner: "white" }] },
    ]);

    expect(describeMoveOnBoard(move, boardBeforeMove(after, move))).toBe(
      describeMoveOnBoard(move, board),
    );
    expect(boardBeforeMove(after, { piece: "ant", from: null, to: [1, 1] })).toHaveLength(
      3,
    );
  });
});
