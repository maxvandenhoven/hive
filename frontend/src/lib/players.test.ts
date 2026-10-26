import { describe, expect, it } from "vitest";

import {
  agentDraft,
  describeGameStatus,
  describePlayer,
  HUMAN_DRAFT,
  parsePlayerDraft,
} from "@/lib/players";
import { AGENT_KINDS } from "@/test/fixtures";

const [negamax] = AGENT_KINDS;

if (negamax === undefined) {
  throw new Error("The fixtures have no agent kinds.");
}

describe("parsePlayerDraft", () => {
  it("builds a human player", () => {
    expect(parsePlayerDraft(HUMAN_DRAFT, AGENT_KINDS)).toEqual({
      ok: true,
      player: { type: "human" },
    });
  });

  it("builds an agent player with the changed params and the label", () => {
    const draft = {
      ...agentDraft(negamax),
      label: " nm3 ",
      budget: "2.5",
      params: { depth: "3", queen_safety: "1" },
    };

    expect(parsePlayerDraft(draft, AGENT_KINDS)).toEqual({
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

    expect(parsePlayerDraft(draft, AGENT_KINDS)).toEqual({
      ok: false,
      errors: {
        budget: "Must be a positive number of seconds.",
        params: { depth: "Must be at least 1." },
      },
    });
    expect(
      parsePlayerDraft({ ...draft, kind: "gone", budget: "1" }, AGENT_KINDS),
    ).toEqual({
      ok: false,
      errors: { kind: "Choose an agent.", params: {} },
    });
  });
});

describe("describePlayer", () => {
  it("names humans and agents", () => {
    expect(describePlayer({ type: "human" })).toBe("Human");
    expect(
      describePlayer({ type: "agent", spec: { kind: "negamax" }, budget_s: 5 }),
    ).toBe("negamax (5 s)");
    expect(
      describePlayer({
        type: "agent",
        spec: { kind: "negamax", label: "nm3" },
        budget_s: 1,
      }),
    ).toBe("nm3 (1 s)");
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
