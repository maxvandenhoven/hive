import { describe, expect, it } from "vitest";

import { describeMove, playerAtPly, toBoardView, toMoveView } from "@/lib/moves";
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
