import { describe, expect, it } from "vitest";

import type { AgentPlayer, GameDetail, GamePosition, HumanPlayer } from "@/api/client";
import type { AgentTurnState } from "@/components/useAgentTurns";
import { gameDetail, gamePosition, moveRead } from "@/test/fixtures";
import { describeTurnPrompt } from "@/lib/turnPrompt";

const NM3: AgentPlayer = {
  type: "agent",
  spec: { kind: "negamax", params: { depth: 3 }, label: "nm3" },
  budget_s: 5,
};
const NM2: AgentPlayer = {
  type: "agent",
  spec: { kind: "negamax", params: { depth: 2 }, label: "nm2" },
  budget_s: 5,
};
const HELPED: HumanPlayer = { type: "human", hint: { spec: NM3.spec, budget_s: 5 } };

const ON_SCREEN = gameDetail({ black: NM3, board_location: "screen" });
const AT_TABLE = gameDetail({ black: NM3, board_location: "table" });
const HINTS = gameDetail({ black: HELPED, white: HELPED, board_location: "table" });
const WATCH = gameDetail({ white: NM3, black: NM2, board_location: "screen" });

/** Black (nm3 against a person) to move at ply 3. */
const BLACK_TO_MOVE = gamePosition({ ply: 3, ply_count: 3, current_player: "black" });

function prompt(
  game: GameDetail,
  position: GamePosition = gamePosition(),
  {
    turnState = "idle",
    shownPly = null,
  }: {
    turnState?: AgentTurnState["type"];
    shownPly?: number | null;
  } = {},
) {
  return describeTurnPrompt({ game, position, turnState, shownPly });
}

describe("describeTurnPrompt", () => {
  it("tells a person what to do on their turn in each scenario", () => {
    expect(prompt(ON_SCREEN)).toEqual({
      kind: "turn",
      text: "Your turn: tap a piece on the board or in your hand",
    });
    expect(prompt(AT_TABLE)).toEqual({
      kind: "turn",
      text: "Your turn: tap a piece on the board or in your hand",
    });
    expect(prompt(HINTS, BLACK_TO_MOVE)).toEqual({
      kind: "turn",
      text: "Black's turn: make the move on the table and enter it",
    });
    expect(prompt(ON_SCREEN, gamePosition({ must_pass: true })).text).toBe(
      "Your turn: no move is possible, so pass",
    );
  });

  it("names the agent that thinks or could not move", () => {
    expect(prompt(ON_SCREEN, BLACK_TO_MOVE, { turnState: "thinking" })).toEqual({
      kind: "thinking",
      text: "nm3 is thinking…",
    });
    expect(prompt(AT_TABLE, BLACK_TO_MOVE, { turnState: "failed" })).toEqual({
      kind: "failed",
      text: "nm3 could not move",
    });
  });

  it("asks to make a pending agent move on the table, also once the game ended", () => {
    const pending = gamePosition({
      ply: 4,
      ply_count: 4,
      board: [
        ...gamePosition().board,
        { coord: [2, 0], stack: [{ piece: "ant", owner: "black" }] },
      ],
      last_move: moveRead({
        ply: 3,
        move: { piece: "ant", from: null, to: [2, 0] },
        source: "agent",
        pending: true,
      }),
      pending_move: true,
    });

    expect(prompt(AT_TABLE, pending)).toEqual({
      kind: "pending",
      text: "Make this move on the table: place ant next to the black queen",
    });
    expect(prompt(AT_TABLE, { ...pending, result: "black" }).kind).toBe("pending");
  });

  it("watches a match", () => {
    expect(prompt(WATCH, BLACK_TO_MOVE, { turnState: "thinking" })).toEqual({
      kind: "watching",
      text: "Watching nm3 vs nm2",
    });
  });

  it("names the winner, the person against an agent", () => {
    const finished = gamePosition({ result: "white" });

    expect(prompt(ON_SCREEN, finished)).toEqual({
      kind: "over",
      text: "You won after 2 moves",
    });
    expect(prompt(ON_SCREEN, { ...finished, result: "black" }).text).toBe(
      "nm3 won after 2 moves",
    );
    expect(prompt(HINTS, finished).text).toBe("White won after 2 moves");
    expect(prompt(WATCH, { ...finished, result: "draw" }).text).toBe(
      "Draw after 2 moves",
    );
    expect(prompt({ ...ON_SCREEN, status: "abandoned" })).toEqual({
      kind: "abandoned",
      text: "This game was abandoned",
    });
  });

  it("offers to go live while replaying", () => {
    expect(prompt(ON_SCREEN, gamePosition(), { shownPly: 1 })).toEqual({
      kind: "replay",
      text: "Showing the position after move 1: go live to play on",
    });
  });
});
