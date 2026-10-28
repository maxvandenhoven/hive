import { describe, expect, it } from "vitest";

import type { PlayerConfig } from "@/api/client";
import {
  agentDraft,
  describeGameScenario,
  describeGameStatus,
  describeNextAction,
  describePlayer,
  gameScenario,
  parseAgentDraft,
} from "@/lib/players";
import { AGENT_KINDS, gameSummary } from "@/test/fixtures";

const [negamax] = AGENT_KINDS;

if (negamax === undefined) {
  throw new Error("The fixtures have no agent kinds.");
}

const HUMAN: PlayerConfig = { type: "human" };
const HINTED: PlayerConfig = {
  type: "human",
  hint: { spec: { kind: "negamax", label: "nm3" }, budget_s: 5 },
};
const NM3: PlayerConfig = {
  type: "agent",
  spec: { kind: "negamax", label: "nm3" },
  budget_s: 5,
};
const NM2: PlayerConfig = {
  type: "agent",
  spec: { kind: "negamax", label: "nm2" },
  budget_s: 5,
};

describe("agentDraft", () => {
  it("starts from the defaults or from the params of a spec", () => {
    expect(agentDraft(negamax)).toEqual({
      type: "agent",
      kind: "negamax",
      label: "",
      budget: "5",
      params: { depth: "", queen_safety: "1" },
    });
    expect(agentDraft(negamax, { params: { depth: 3 }, label: "nm3" })).toMatchObject({
      label: "nm3",
      params: { depth: "3", queen_safety: "1" },
    });
  });
});

describe("parseAgentDraft", () => {
  it("builds an agent player with the changed params and the label", () => {
    const draft = {
      ...agentDraft(negamax),
      label: " nm3 ",
      budget: "2.5",
      params: { depth: "3", queen_safety: "1" },
    };

    expect(parseAgentDraft(draft, AGENT_KINDS)).toEqual({
      ok: true,
      player: {
        type: "agent",
        spec: { kind: "negamax", params: { depth: 3 }, label: "nm3" },
        budget_s: 2.5,
      },
    });
  });

  it("reports an invalid budget, params and unknown kinds", () => {
    const draft = { ...agentDraft(negamax), budget: "0", params: { depth: "-1" } };

    expect(parseAgentDraft(draft, AGENT_KINDS)).toEqual({
      ok: false,
      errors: {
        budget: "Must be a positive number of seconds.",
        params: { depth: "Must be at least 1." },
      },
    });
    expect(parseAgentDraft({ ...draft, kind: "gone", budget: "1" }, AGENT_KINDS)).toEqual(
      { ok: false, errors: { kind: "Choose an agent.", params: {} } },
    );
  });
});

describe("describePlayer", () => {
  it("names humans, their hints and agents", () => {
    expect(describePlayer(HUMAN)).toBe("Human");
    expect(describePlayer(HINTED)).toBe("Human · hints from nm3 (5 s)");
    expect(
      describePlayer({ type: "agent", spec: { kind: "negamax" }, budget_s: 5 }),
    ).toBe("negamax (5 s)");
    expect(describePlayer({ ...NM3, budget_s: 1 })).toBe("nm3 (1 s)");
  });
});

describe("gameScenario", () => {
  it("tells the scenarios apart by their players and board location", () => {
    const cases = [
      {
        white: HUMAN,
        black: NM3,
        board_location: "screen",
        label: "vs agent · on screen",
      },
      {
        white: NM3,
        black: HINTED,
        board_location: "table",
        label: "vs agent · at the table",
      },
      { white: HINTED, black: HUMAN, board_location: "table", label: "hints game" },
      { white: NM3, black: NM2, board_location: "screen", label: "watching" },
    ] as const;

    expect(cases.map((game) => gameScenario(game))).toEqual([
      "agent",
      "agent",
      "hints",
      "watch",
    ]);
    expect(cases.map((game) => describeGameScenario(game))).toEqual(
      cases.map((game) => game.label),
    );
  });
});

describe("describeGameStatus", () => {
  it("shows the result of finished games", () => {
    expect(describeGameStatus({ status: "active", result: null })).toBe("Active");
    expect(describeGameStatus({ status: "abandoned", result: null })).toBe("Abandoned");
    expect(describeGameStatus({ status: "finished", result: "black" })).toBe("Black won");
    expect(describeGameStatus({ status: "finished", result: "draw" })).toBe("Draw");
  });
});

describe("describeNextAction", () => {
  it("shows what happens next in each scenario and state", () => {
    const cases = [
      [gameSummary({ white: HUMAN, black: NM3 }), "Your turn", true],
      [
        gameSummary({ white: HUMAN, black: NM3, current_player: "black" }),
        "nm3 to move",
        false,
      ],
      [
        gameSummary({ white: HUMAN, black: NM3, pending_move: true }),
        "Agent's move to make",
        true,
      ],
      [gameSummary({ white: HINTED, black: HUMAN }), "White to move", true],
      [
        gameSummary({ white: HINTED, black: HUMAN, current_player: "black" }),
        "Black to move",
        true,
      ],
      [
        gameSummary({ white: NM3, black: NM2, current_player: "black" }),
        "nm2 to move",
        false,
      ],
      [gameSummary({ status: "finished", result: "white" }), "White won", false],
      [gameSummary({ status: "abandoned" }), "Abandoned", false],
    ] as const;

    for (const [game, label, waitsForPerson] of cases) {
      expect(describeNextAction(game)).toEqual({ label, waitsForPerson });
    }
  });
});
