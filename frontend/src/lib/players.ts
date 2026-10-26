import type {
  AgentRegistration,
  GameResult,
  GameSummary,
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

/** An agent side as the form edits it, with the text typed into each input. */
export interface AgentPlayerDraft {
  type: "agent";
  kind: string;
  label: string;
  budget: string;
  params: AgentParamDrafts;
}

/** A side setup as the form edits it. */
export type PlayerDraft = { type: "human" } | AgentPlayerDraft;

export interface PlayerDraftErrors {
  kind?: string;
  budget?: string;
  params: AgentParamErrors;
}

export type PlayerDraftResult =
  { ok: true; player: PlayerConfig } | { ok: false; errors: PlayerDraftErrors };

export const HUMAN_DRAFT: PlayerDraft = { type: "human" };

/** The draft of an agent of a kind, with its default params and budget. */
export function agentDraft(registration: AgentRegistration): AgentPlayerDraft {
  return {
    type: "agent",
    kind: registration.kind,
    label: "",
    budget: String(DEFAULT_AGENT_BUDGET_S),
    params: defaultAgentParamDrafts(parseAgentParamFields(registration.params_schema)),
  };
}

function parseBudget(text: string): number | null {
  const budget = Number(text.trim());

  return text.trim() !== "" && Number.isFinite(budget) && budget > 0 ? budget : null;
}

/** Parse and check a side setup against the registered agent kinds. */
export function parsePlayerDraft(
  draft: PlayerDraft,
  agentKinds: AgentRegistration[],
): PlayerDraftResult {
  if (draft.type === "human") {
    return { ok: true, player: { type: "human" } };
  }

  const errors: PlayerDraftErrors = { params: {} };
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

/** A short name of a side, such as `Human` or `negamax (5 s)`. */
export function describePlayer(player: PlayerConfig): string {
  if (player.type === "human") {
    return "Human";
  }

  return `${player.spec.label ?? player.spec.kind} (${player.budget_s} s)`;
}

const RESULT_LABELS: Record<GameResult, string> = {
  white: "White won",
  black: "Black won",
  draw: "Draw",
};

/** The status of a game as shown in the list, with the result once it is finished. */
export function describeGameStatus(game: Pick<GameSummary, "status" | "result">): string {
  if (game.result !== null) {
    return RESULT_LABELS[game.result];
  }

  return game.status === "active" ? "Active" : "Abandoned";
}
