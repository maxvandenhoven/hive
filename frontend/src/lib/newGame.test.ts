import { describe, expect, it } from "vitest";

import {
  advancedAgentChoice,
  buildNewGameRequest,
  defaultGameName,
  defaultNewGameChoices,
  NEW_GAME_STORAGE_KEY,
  readNewGameChoices,
  resolveAgentChoice,
  writeNewGameChoices,
  type NewGameAgents,
  type NewGameChoices,
} from "@/lib/newGame";
import { agentDraft } from "@/lib/players";
import { AGENT_KINDS, AGENT_PRESETS } from "@/test/fixtures";

const AGENTS: NewGameAgents = { presets: AGENT_PRESETS, agentKinds: AGENT_KINDS };
const [negamax] = AGENT_KINDS;

if (negamax === undefined) {
  throw new Error("The fixtures have no agent kinds.");
}

function defaults(): NewGameChoices {
  const choices = defaultNewGameChoices(AGENTS);

  if (choices === null) {
    throw new Error("The fixtures offer no agents.");
  }

  return choices;
}

const NM2 = {
  type: "agent",
  spec: { kind: "negamax", params: { depth: 2 }, label: "nm2" },
  budget_s: 5,
};
const NM3 = { ...NM2, spec: { kind: "negamax", params: { depth: 3 }, label: "nm3" } };

describe("defaultNewGameChoices", () => {
  it("picks the strongest preset, and the weakest as black when watching", () => {
    const choices = defaults();

    expect(choices.scenario).toBe("agent");
    expect(choices.agentGame.opponent).toEqual({ mode: "preset", preset: "nm3" });
    expect(choices.watchGame).toEqual({
      white: { mode: "preset", preset: "nm3" },
      black: { mode: "preset", preset: "nm2" },
    });
  });

  it("falls back to an advanced draft without presets, and to nothing without kinds", () => {
    expect(
      defaultNewGameChoices({ presets: [], agentKinds: AGENT_KINDS })?.agentGame.opponent,
    ).toEqual({ mode: "advanced", draft: agentDraft(negamax) });
    expect(defaultNewGameChoices({ presets: [], agentKinds: [] })).toBeNull();
  });
});

describe("advancedAgentChoice", () => {
  it("starts the advanced draft from the preset", () => {
    expect(advancedAgentChoice({ mode: "preset", preset: "nm2" }, AGENTS)).toEqual({
      mode: "advanced",
      draft: agentDraft(negamax, { params: { depth: 2 } }),
    });
  });
});

describe("resolveAgentChoice", () => {
  it("gives presets the default budget and checks advanced drafts", () => {
    expect(resolveAgentChoice({ mode: "preset", preset: "nm3" }, AGENTS)).toEqual({
      ok: true,
      agent: NM3,
    });
    expect(resolveAgentChoice({ mode: "preset", preset: "gone" }, AGENTS)).toEqual({
      ok: false,
      errors: null,
    });
    expect(
      resolveAgentChoice(
        { mode: "advanced", draft: { ...agentDraft(negamax), budget: "0" } },
        AGENTS,
      ),
    ).toMatchObject({ ok: false, errors: { budget: expect.any(String) as string } });
  });
});

describe("buildNewGameRequest", () => {
  const build = (choices: NewGameChoices, { name = "", random = 0.9 } = {}) =>
    buildNewGameRequest({ choices, agents: AGENTS, name, random: () => random });

  it("plays against an agent at the chosen place and colour, with hints", () => {
    const choices = defaults();

    expect(build(choices)).toEqual({
      name: "You vs nm3",
      white: { type: "human" },
      black: NM3,
      board_location: "screen",
    });
    expect(
      build({
        ...choices,
        agentGame: {
          ...choices.agentGame,
          location: "table",
          colour: "black",
          opponent: { mode: "preset", preset: "nm2" },
          hints: true,
        },
      }),
    ).toEqual({
      name: "You vs nm2",
      white: NM2,
      black: { type: "human", hint: { spec: NM3.spec, budget_s: 5 } },
      board_location: "table",
    });
  });

  it("draws a random colour", () => {
    const choices = defaults();
    const random = { ...choices, agentGame: { ...choices.agentGame, colour: "random" } };

    expect(build(random as NewGameChoices, { random: 0.2 })?.white).toEqual({
      type: "human",
    });
    expect(build(random as NewGameChoices, { random: 0.7 })?.black).toEqual({
      type: "human",
    });
  });

  it("gives hints to the chosen sides of a hints game at the table", () => {
    const choices: NewGameChoices = {
      ...defaults(),
      scenario: "hints",
      hintsGame: { sides: "black", hint: { mode: "preset", preset: "nm2" } },
    };

    expect(build(choices)).toEqual({
      name: "Hints game",
      white: { type: "human" },
      black: { type: "human", hint: { spec: NM2.spec, budget_s: 5 } },
      board_location: "table",
    });
    expect(
      build({ ...choices, hintsGame: { ...choices.hintsGame, sides: "both" } }),
    ).toMatchObject({
      white: { type: "human", hint: { spec: NM2.spec } },
      black: { type: "human", hint: { spec: NM2.spec } },
    });
  });

  it("watches two agents on the screen", () => {
    expect(build({ ...defaults(), scenario: "watch" }, { name: " Bots " })).toEqual({
      name: "Bots",
      white: NM3,
      black: NM2,
      board_location: "screen",
    });
    expect(defaultGameName({ ...defaults(), scenario: "watch" }, AGENTS)).toBe(
      "nm3 vs nm2",
    );
  });

  it("builds nothing while a choice is invalid", () => {
    const choices = defaults();
    const invalid = {
      ...choices,
      agentGame: {
        ...choices.agentGame,
        opponent: {
          mode: "advanced" as const,
          draft: { ...agentDraft(negamax), budget: "" },
        },
      },
    };

    expect(build(invalid)).toBeNull();
    expect(defaultGameName(invalid, AGENTS)).toBeNull();
  });
});

describe("remembered choices", () => {
  it("reads nothing until choices are written", () => {
    expect(readNewGameChoices(defaults(), AGENTS)).toBeNull();
  });

  it("reads back the written choices", () => {
    const choices: NewGameChoices = {
      ...defaults(),
      scenario: "hints",
      hintsGame: {
        sides: "white",
        hint: { mode: "advanced", draft: { ...agentDraft(negamax), budget: "2" } },
      },
    };
    writeNewGameChoices(choices);

    expect(readNewGameChoices(defaults(), AGENTS)).toEqual(choices);
  });

  it("replaces invalid or outdated fields with the defaults", () => {
    window.localStorage.setItem(
      NEW_GAME_STORAGE_KEY,
      JSON.stringify({
        scenario: "watch",
        agentGame: { location: "moon", colour: "black", hints: "yes" },
        watchGame: {
          white: { mode: "preset", preset: "removed" },
          black: { mode: "advanced", draft: { kind: "gone" } },
        },
      }),
    );

    expect(readNewGameChoices(defaults(), AGENTS)).toEqual({
      ...defaults(),
      scenario: "watch",
      agentGame: { ...defaults().agentGame, colour: "black" },
    });

    window.localStorage.setItem(NEW_GAME_STORAGE_KEY, "{not json");

    expect(readNewGameChoices(defaults(), AGENTS)).toBeNull();
  });
});
