import type {
  AgentPlayer,
  AgentRegistration,
  AgentSpec,
  GameResult,
  GameSummary,
  HintAgent,
  PlayerConfig,
} from "@/api/client";
import {
  defaultAgentParamDrafts,
  parseAgentParamFields,
  parseAgentParams,
  type AgentParamDrafts,
  type AgentParamErrors,
} from "@/lib/agentParams";

/** The time budget of an agent decision in seconds when none is entered. */
export const DEFAULT_AGENT_BUDGET_S = 5;

export type PlayerSide = "white" | "black";

export const PLAYER_SIDES: PlayerSide[] = ["white", "black"];

export const SIDE_TITLES: Record<PlayerSide, string> = { white: "White", black: "Black" };

/** An agent as the advanced form edits it, with the text typed into each input. */
export interface AgentPlayerDraft {
  type: "agent";
  kind: string;
  label: string;
  budget: string;
  params: AgentParamDrafts;
}

export interface AgentDraftErrors {
  kind?: string;
  budget?: string;
  params: AgentParamErrors;
}

export type AgentDraftResult =
  { ok: true; player: AgentPlayer } | { ok: false; errors: AgentDraftErrors };

/**
 * The draft of an agent of a kind, with its default params and budget.
 *
 * `params` and `label` start the draft from a spec instead, such as a preset.
 */
export function agentDraft(
  registration: AgentRegistration,
  { params = {}, label = "" }: { params?: AgentSpec["params"]; label?: string } = {},
): AgentPlayerDraft {
  // The drafts of a form whose defaults are the values of the spec.
  const drafts = defaultAgentParamDrafts(
    parseAgentParamFields(registration.params_schema).map((field) =>
      field.name in params ? { ...field, defaultValue: params[field.name] } : field,
    ),
  );

  return {
    type: "agent",
    kind: registration.kind,
    label,
    budget: String(DEFAULT_AGENT_BUDGET_S),
    params: drafts,
  };
}

function parseBudget(text: string): number | null {
  const budget = Number(text.trim());

  return text.trim() !== "" && Number.isFinite(budget) && budget > 0 ? budget : null;
}

/** Parse and check an agent draft against the registered agent kinds. */
export function parseAgentDraft(
  draft: AgentPlayerDraft,
  agentKinds: AgentRegistration[],
): AgentDraftResult {
  const errors: AgentDraftErrors = { params: {} };
  const registration = agentKinds.find((kind) => kind.kind === draft.kind);
  const budget = parseBudget(draft.budget);

  if (budget === null) {
    errors.budget = "Must be a positive number of seconds.";
  }

  if (registration === undefined) {
    errors.kind = "Choose an agent.";

    return { ok: false, errors };
  }

  const params = parseAgentParams(
    parseAgentParamFields(registration.params_schema),
    draft.params,
  );

  if (!params.ok) {
    errors.params = params.errors;
  }

  if (budget === null || !params.ok) {
    return { ok: false, errors };
  }

  const label = draft.label.trim();

  return {
    ok: true,
    player: {
      type: "agent",
      spec: { kind: draft.kind, params: params.params, label: label || null },
      budget_s: budget,
    },
  };
}

/** The name of an agent: its label, or its kind without one. */
export function agentName(spec: AgentSpec): string {
  return spec.label ?? spec.kind;
}

/** A short name of an agent with its budget, such as `nm3 (5 s)`. */
export function describeAgent(agent: { spec: AgentSpec; budget_s: number }): string {
  return `${agentName(agent.spec)} (${agent.budget_s} s)`;
}

/** A short description of the hints of a side, such as `hints from nm3 (5 s)`. */
export function describeHintAgent(hint: HintAgent): string {
  return `hints from ${describeAgent(hint)}`;
}

/** A short name of a side, such as `Human`, `Human · hints from nm3 (5 s)` or `nm3 (5 s)`. */
export function describePlayer(player: PlayerConfig): string {
  if (player.type === "agent") {
    return describeAgent(player);
  }

  const name = player.name ?? "Human";

  return player.hint ? `${name} · ${describeHintAgent(player.hint)}` : name;
}

/**
 * The side the person using the app plays, or `null` when it is unknown.
 *
 * Against an agent it is the human side. At the table it is the side without a name
 * when the opponent has one; older hints games named neither side.
 */
export function ownSide(game: Pick<GameSummary, "white" | "black">): PlayerSide | null {
  const humans = PLAYER_SIDES.filter((side) => game[side].type === "human");

  if (humans.length === 1) {
    return humans[0] ?? null;
  }

  const unnamed = PLAYER_SIDES.filter((side) => {
    const player = game[side];

    return player.type === "human" && !player.name;
  });

  return humans.length === 2 && unnamed.length === 1 ? (unnamed[0] ?? null) : null;
}

/** Who plays a side: `You`, the opponent's name, the agent's name or the colour. */
export function sideName(
  game: Pick<GameSummary, "white" | "black">,
  side: PlayerSide,
): string {
  const player = game[side];

  if (ownSide(game) === side) {
    return "You";
  }

  if (player.type === "agent") {
    return agentName(player.spec);
  }

  return player.name ?? SIDE_TITLES[side];
}

/** Whose turn it is, such as `Your turn` or `Sam's turn`. */
export function describeTurnOf(
  game: Pick<GameSummary, "white" | "black">,
  side: PlayerSide,
): string {
  return ownSide(game) === side ? "Your turn" : `${sideName(game, side)}'s turn`;
}

/** Who is to move, short, such as `Your turn` or `Sam to move`. */
export function describeMover(
  game: Pick<GameSummary, "white" | "black">,
  side: PlayerSide,
): string {
  return ownSide(game) === side ? "Your turn" : `${sideName(game, side)} to move`;
}

/**
 * What a game is for (D26), told apart by its players.
 *
 * `agent` is a person against an agent, `hints` two people with hints at the table and
 * `watch` two agents on the screen.
 */
export type GameScenario = "agent" | "hints" | "watch";

export const GAME_SCENARIOS: GameScenario[] = ["agent", "hints", "watch"];

/** The title and one-sentence description of each scenario, as the new game flow offers it. */
export const GAME_SCENARIO_INFO: Record<
  GameScenario,
  { title: string; description: string }
> = {
  agent: {
    title: "Play against an agent",
    description: "You play one side and an agent plays the other.",
  },
  hints: {
    title: "Play a friend with hints",
    description: "You play a friend at the table, and an agent suggests moves to you.",
  },
  watch: {
    title: "Watch two agents",
    description: "Two agents play each other on this screen.",
  },
};

/** The scenario of a game, from the number of sides people play. */
export function gameScenario(game: Pick<GameSummary, "white" | "black">): GameScenario {
  const humans = [game.white, game.black].filter((player) => player.type === "human");

  if (humans.length === 0) {
    return "watch";
  }

  return humans.length === 1 ? "agent" : "hints";
}

/** The short label of a game's scenario in the list, such as `vs agent`. */
export function describeGameScenario(game: Pick<GameSummary, "white" | "black">): string {
  switch (gameScenario(game)) {
    case "agent":
      return "vs agent";
    case "hints":
      return "hints game";
    case "watch":
      return "watching";
  }
}

const RESULT_LABELS: Record<GameResult, string> = {
  white: "White won",
  black: "Black won",
  draw: "Draw",
};

/** The status of a game, with the result once it is finished. */
export function describeGameStatus(game: Pick<GameSummary, "status" | "result">): string {
  if (game.result !== null) {
    return RESULT_LABELS[game.result];
  }

  return game.status === "active" ? "Active" : "Abandoned";
}

/** What happens next in a game, and whether it waits for a person. */
export interface GameNextAction {
  label: string;
  waitsForPerson: boolean;
}

/**
 * What happens next in a game, as the list shows it.
 *
 * A person's turn is `Your turn` against an agent and `White to move` in a hints game; a
 * pending agent move is `Agent's move to make`, and an agent's turn names the agent.
 * Finished and abandoned games show their status.
 */
export function describeNextAction(
  game: Pick<
    GameSummary,
    "status" | "result" | "white" | "black" | "current_player" | "pending_move"
  >,
): GameNextAction {
  if (game.status !== "active") {
    return { label: describeGameStatus(game), waitsForPerson: false };
  }

  if (game.pending_move) {
    return { label: "Agent's move to make", waitsForPerson: true };
  }

  const player = game[game.current_player];

  if (player.type === "agent") {
    return { label: `${agentName(player.spec)} to move`, waitsForPerson: false };
  }

  return { label: describeMover(game, game.current_player), waitsForPerson: true };
}
