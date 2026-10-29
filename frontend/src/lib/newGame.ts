/**
 * The choices of the new game flow, the request they create and how they are remembered.
 *
 * The flow asks for a scenario (D26) and sets up the players from it, so a person never
 * picks human or agent per side. Agents are presets by name, or an advanced draft.
 */

import type {
  AgentPlayer,
  AgentPreset,
  AgentRegistration,
  GameCreate,
  HumanPlayer,
  PlayerConfig,
} from "@/api/client";
import {
  agentDraft,
  agentName,
  DEFAULT_AGENT_BUDGET_S,
  GAME_SCENARIOS,
  parseAgentDraft,
  type AgentDraftErrors,
  type AgentPlayerDraft,
  type GameScenario,
  type PlayerSide,
} from "@/lib/players";

/** The longest game name the API accepts. */
export const GAME_NAME_MAX_LENGTH = 100;

/** The longest player name the API accepts. */
export const PLAYER_NAME_MAX_LENGTH = 40;

/** The name of the opponent at the table when none is entered. */
export const OPPONENT_DEFAULT_NAME = "Opponent";

/** Where the flow remembers the last choices, per device. */
export const NEW_GAME_STORAGE_KEY = "hive.new-game.choices";

/** An agent as the flow picks it: a preset by name, or an advanced draft. */
export type AgentChoice =
  { mode: "preset"; preset: string } | { mode: "advanced"; draft: AgentPlayerDraft };

/** The colour a person plays against an agent; `random` is drawn when the game starts. */
export type ColourChoice = PlayerSide | "random";

export interface AgentGameChoices {
  colour: ColourChoice;
  opponent: AgentChoice;
  hints: boolean;
  hint: AgentChoice;
}

/** A game against a friend at the table, where only the person using the app gets hints. */
export interface HintsGameChoices {
  colour: ColourChoice;
  opponentName: string;
  hint: AgentChoice;
}

export interface WatchGameChoices {
  white: AgentChoice;
  black: AgentChoice;
}

/** Everything the flow asks, for every scenario, so switching scenarios keeps choices. */
export interface NewGameChoices {
  scenario: GameScenario;
  agentGame: AgentGameChoices;
  hintsGame: HintsGameChoices;
  watchGame: WatchGameChoices;
}

/** The agents the flow offers: the presets, and the kinds for advanced drafts. */
export interface NewGameAgents {
  presets: AgentPreset[];
  agentKinds: AgentRegistration[];
}

/** The choice of a preset, or of an advanced draft of the first kind without presets. */
function defaultAgentChoice(
  preset: AgentPreset | undefined,
  { agentKinds }: NewGameAgents,
): AgentChoice | null {
  if (preset) {
    return { mode: "preset", preset: preset.name };
  }

  const [firstKind] = agentKinds;

  return firstKind ? { mode: "advanced", draft: agentDraft(firstKind) } : null;
}

/**
 * The choices of a first game: the strongest preset as the opponent and for hints, and
 * the strongest against the weakest when watching.
 *
 * Presets come sorted by name, which for the shipped ones (`nm2`, `nm3`) is by strength.
 * Returns `null` when there is no agent to offer.
 */
export function defaultNewGameChoices(agents: NewGameAgents): NewGameChoices | null {
  const strongest = defaultAgentChoice(agents.presets.at(-1), agents);
  const weakest = defaultAgentChoice(agents.presets.at(0), agents);

  if (strongest === null || weakest === null) {
    return null;
  }

  return {
    scenario: "agent",
    agentGame: {
      colour: "white",
      opponent: strongest,
      hints: false,
      hint: strongest,
    },
    hintsGame: { colour: "white", opponentName: "", hint: strongest },
    watchGame: { white: strongest, black: weakest },
  };
}

/** Switch an agent choice to the advanced form, starting from its preset. */
export function advancedAgentChoice(
  choice: AgentChoice,
  { presets, agentKinds }: NewGameAgents,
): AgentChoice {
  if (choice.mode === "advanced") {
    return choice;
  }

  const preset = presets.find((candidate) => candidate.name === choice.preset);
  const registration = agentKinds.find((kind) => kind.kind === preset?.spec.kind);
  const [firstKind] = agentKinds;

  if (preset && registration) {
    return {
      mode: "advanced",
      draft: agentDraft(registration, { params: preset.spec.params }),
    };
  }

  return firstKind ? { mode: "advanced", draft: agentDraft(firstKind) } : choice;
}

export type AgentChoiceResult =
  { ok: true; agent: AgentPlayer } | { ok: false; errors: AgentDraftErrors | null };

/**
 * The agent of a choice with its budget, or the errors of an advanced draft.
 *
 * A preset gets the default budget; an unknown preset fails without field errors.
 */
export function resolveAgentChoice(
  choice: AgentChoice,
  { presets, agentKinds }: NewGameAgents,
): AgentChoiceResult {
  if (choice.mode === "advanced") {
    const result = parseAgentDraft(choice.draft, agentKinds);

    return result.ok
      ? { ok: true, agent: result.player }
      : { ok: false, errors: result.errors };
  }

  const preset = presets.find((candidate) => candidate.name === choice.preset);

  return preset
    ? {
        ok: true,
        agent: { type: "agent", spec: preset.spec, budget_s: DEFAULT_AGENT_BUDGET_S },
      }
    : { ok: false, errors: null };
}

/** A person's side, with hints from `hint` when given. */
function humanPlayer(hint: AgentPlayer | null): HumanPlayer {
  return hint
    ? { type: "human", hint: { spec: hint.spec, budget_s: hint.budget_s } }
    : { type: "human" };
}

/**
 * The request that creates the game of the chosen scenario, or `null` while a choice is
 * invalid.
 *
 * An empty `name` defaults from the scenario (`You vs nm3`, `Hints game`, `nm3 vs nm2`),
 * and `random` (between 0 and 1) draws a random colour: white below one half.
 */
export function buildNewGameRequest({
  choices,
  agents,
  name,
  random,
}: {
  choices: NewGameChoices;
  agents: NewGameAgents;
  name: string;
  random: () => number;
}): GameCreate | null {
  const resolve = (choice: AgentChoice) => {
    const result = resolveAgentChoice(choice, agents);

    return result.ok ? result.agent : null;
  };
  let players: { white: PlayerConfig; black: PlayerConfig };
  let location: GameCreate["board_location"];
  let defaultName: string;

  switch (choices.scenario) {
    case "agent": {
      const { colour, hints } = choices.agentGame;
      const opponent = resolve(choices.agentGame.opponent);
      const hint = hints ? resolve(choices.agentGame.hint) : null;

      if (opponent === null || (hints && hint === null)) {
        return null;
      }

      const side = colour === "random" ? (random() < 0.5 ? "white" : "black") : colour;
      const person = humanPlayer(hint);
      players =
        side === "white"
          ? { white: person, black: opponent }
          : { white: opponent, black: person };
      location = "screen";
      defaultName = `You vs ${agentName(opponent.spec)}`;
      break;
    }
    case "hints": {
      const { colour } = choices.hintsGame;
      const hint = resolve(choices.hintsGame.hint);

      if (hint === null) {
        return null;
      }

      const side = colour === "random" ? (random() < 0.5 ? "white" : "black") : colour;
      const opponentName = choices.hintsGame.opponentName.trim() || OPPONENT_DEFAULT_NAME;
      const person = humanPlayer(hint);
      const opponent: HumanPlayer = {
        type: "human",
        name: opponentName.slice(0, PLAYER_NAME_MAX_LENGTH),
      };
      players =
        side === "white"
          ? { white: person, black: opponent }
          : { white: opponent, black: person };
      location = "table";
      defaultName = `You vs ${opponentName}`;
      break;
    }
    case "watch": {
      const white = resolve(choices.watchGame.white);
      const black = resolve(choices.watchGame.black);

      if (white === null || black === null) {
        return null;
      }

      players = { white, black };
      location = "screen";
      defaultName = `${agentName(white.spec)} vs ${agentName(black.spec)}`;
      break;
    }
  }

  return {
    name: (name.trim() || defaultName).slice(0, GAME_NAME_MAX_LENGTH),
    ...players,
    board_location: location,
  };
}

/** The name a game of the choices gets without one, or `null` while a choice is invalid. */
export function defaultGameName(choices: NewGameChoices, agents: NewGameAgents) {
  return (
    buildNewGameRequest({ choices, agents, name: "", random: () => 0 })?.name ?? null
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readOption<T extends string>(value: unknown, options: T[], fallback: T): T {
  return options.find((option) => option === value) ?? fallback;
}

/** A stored agent choice if it names a known preset or kind, else `fallback`. */
function readAgentChoice(
  value: unknown,
  fallback: AgentChoice,
  { presets, agentKinds }: NewGameAgents,
): AgentChoice {
  if (!isRecord(value)) {
    return fallback;
  }

  if (value.mode === "preset") {
    return presets.some((preset) => preset.name === value.preset)
      ? { mode: "preset", preset: value.preset as string }
      : fallback;
  }

  const draft = value.draft;

  if (
    value.mode === "advanced" &&
    isRecord(draft) &&
    agentKinds.some((kind) => kind.kind === draft.kind) &&
    typeof draft.label === "string" &&
    typeof draft.budget === "string" &&
    isRecord(draft.params)
  ) {
    return { mode: "advanced", draft: draft as unknown as AgentPlayerDraft };
  }

  return fallback;
}

/**
 * The choices stored on this device, checked field by field against `defaults` and the
 * agents now offered, or `null` when none are stored or storage is unavailable.
 */
export function readNewGameChoices(
  defaults: NewGameChoices,
  agents: NewGameAgents,
): NewGameChoices | null {
  let stored: unknown;

  try {
    const text = window.localStorage.getItem(NEW_GAME_STORAGE_KEY);

    if (text === null) {
      return null;
    }

    stored = JSON.parse(text);
  } catch {
    return null;
  }

  if (!isRecord(stored)) {
    return null;
  }

  const agentGame = isRecord(stored.agentGame) ? stored.agentGame : {};
  const hintsGame = isRecord(stored.hintsGame) ? stored.hintsGame : {};
  const watchGame = isRecord(stored.watchGame) ? stored.watchGame : {};

  return {
    scenario: readOption(stored.scenario, GAME_SCENARIOS, defaults.scenario),
    agentGame: {
      colour: readOption<ColourChoice>(
        agentGame.colour,
        ["white", "black", "random"],
        defaults.agentGame.colour,
      ),
      opponent: readAgentChoice(agentGame.opponent, defaults.agentGame.opponent, agents),
      hints:
        typeof agentGame.hints === "boolean" ? agentGame.hints : defaults.agentGame.hints,
      hint: readAgentChoice(agentGame.hint, defaults.agentGame.hint, agents),
    },
    hintsGame: {
      colour: readOption<ColourChoice>(
        hintsGame.colour,
        ["white", "black", "random"],
        defaults.hintsGame.colour,
      ),
      opponentName:
        typeof hintsGame.opponentName === "string"
          ? hintsGame.opponentName.slice(0, PLAYER_NAME_MAX_LENGTH)
          : defaults.hintsGame.opponentName,
      hint: readAgentChoice(hintsGame.hint, defaults.hintsGame.hint, agents),
    },
    watchGame: {
      white: readAgentChoice(watchGame.white, defaults.watchGame.white, agents),
      black: readAgentChoice(watchGame.black, defaults.watchGame.black, agents),
    },
  };
}

/** Remember the choices on this device; without storage they are forgotten. */
export function writeNewGameChoices(choices: NewGameChoices) {
  try {
    window.localStorage.setItem(NEW_GAME_STORAGE_KEY, JSON.stringify(choices));
  } catch {
    // Without storage the flow starts from the defaults next time.
  }
}
