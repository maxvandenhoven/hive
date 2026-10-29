import { describe, expect, it } from "vitest";

import type { AgentPlayer, HumanPlayer } from "@/api/client";
import { boardTips, describeGameHelp } from "@/lib/gameHelp";
import { helpPath, rulesPath } from "@/lib/help";
import { gameDetail, gamePosition } from "@/test/fixtures";

const NM3: AgentPlayer = {
  type: "agent",
  spec: { kind: "negamax", params: { depth: 3 }, label: "nm3" },
  budget_s: 5,
};
const HELPED: HumanPlayer = { type: "human", hint: { spec: NM3.spec, budget_s: 5 } };

const AGAINST_AGENT = gameDetail({ black: NM3, board_location: "screen" });
const HINTS = gameDetail({
  white: HELPED,
  black: { type: "human" },
  board_location: "table",
});
const WATCH = gameDetail({ white: NM3, black: NM3, board_location: "screen" });

function tipIds(...args: Parameters<typeof boardTips>): string[] {
  return boardTips(...args).map((tip) => tip.id);
}

describe("describeGameHelp", () => {
  it("explains entering a move by scenario", () => {
    const position = gamePosition();

    expect(
      describeGameHelp({ game: AGAINST_AGENT, position, kind: "turn" }).text,
    ).toMatch(/^Tap a piece with a blue ring/);
    expect(describeGameHelp({ game: HINTS, position, kind: "turn" }).text).toMatch(
      /^Make the move on the real board/,
    );
  });

  it("points to the rules when the only move is to pass", () => {
    const help = describeGameHelp({
      game: AGAINST_AGENT,
      position: gamePosition({ must_pass: true }),
      kind: "turn",
    });

    expect(help.to).toBe(rulesPath("passing"));
  });

  it("explains leaving while an agent thinks or a move waits for Done", () => {
    const position = gamePosition();

    expect(describeGameHelp({ game: AGAINST_AGENT, position, kind: "thinking" }).to).toBe(
      helpPath("leaving"),
    );
    expect(
      describeGameHelp({ game: AGAINST_AGENT, position, kind: "pending" }).text,
    ).toMatch(/press Done/);
    expect(describeGameHelp({ game: WATCH, position, kind: "watching" }).title).toBe(
      "Watching a match",
    );
  });
});

describe("boardTips", () => {
  it("shows the tapping, placement and hint tips on a person's turn", () => {
    expect(
      tipIds({
        game: AGAINST_AGENT,
        position: gamePosition(),
        kind: "turn",
        hintAvailable: true,
      }),
    ).toEqual(["place-own-colour", "tap-movable", "ask-hint"]);
  });

  it("asks to enter the table move in a hints game", () => {
    expect(
      tipIds({
        game: HINTS,
        position: gamePosition(),
        kind: "turn",
        hintAvailable: false,
      }),
    ).toEqual(["enter-table-move", "place-own-colour", "tap-movable"]);
  });

  it("links to the placement rule when only the queen may be placed", () => {
    const position = gamePosition({
      ply: 6,
      ply_count: 6,
      movable_pieces: [],
      placeable_piece_types: ["queen"],
      hands: {
        white: { queen: 1, beetle: 2, grasshopper: 1, spider: 1, ant: 3 },
        black: { queen: 0, beetle: 2, grasshopper: 3, spider: 2, ant: 0 },
      },
    });
    const [tip] = boardTips({
      game: AGAINST_AGENT,
      position,
      kind: "turn",
      hintAvailable: false,
    });

    expect(tip?.id).toBe("queen-by-fourth-turn");
    expect(tip?.link?.to).toBe(rulesPath("placement"));
  });

  it("matches the pending, watching, passing and other states", () => {
    const position = gamePosition();
    const options = { game: AGAINST_AGENT, position, hintAvailable: true };

    expect(tipIds({ ...options, kind: "pending" })).toEqual(["make-agent-move"]);
    expect(tipIds({ ...options, game: WATCH, kind: "watching" })).toEqual([
      "watch-match",
    ]);
    expect(
      tipIds({ ...options, position: gamePosition({ must_pass: true }), kind: "turn" }),
    ).toEqual(["must-pass"]);
    expect(tipIds({ ...options, kind: "thinking" })).toEqual([]);
    expect(tipIds({ ...options, kind: "over" })).toEqual([]);
  });
});
