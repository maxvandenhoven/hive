import type { AgentRegistration, GameSummary } from "@/api/client";

const SEARCH_PARAMS_SCHEMA = {
  additionalProperties: false,
  properties: {
    depth: {
      anyOf: [{ minimum: 1, type: "integer" }, { type: "null" }],
      default: null,
      description:
        "The maximum search depth in plies, or `None` to search until stopped.",
      title: "Depth",
    },
    queen_safety: {
      default: 1.0,
      description: "The weight of the occupied neighbours of the queens.",
      title: "Queen Safety",
      type: "number",
    },
  },
  title: "NegamaxAgentParams",
  type: "object",
};

/** Agent kinds shaped like the ones the API lists. */
export const AGENT_KINDS: AgentRegistration[] = [
  {
    kind: "negamax",
    description: "Agent that selects moves using the negamax algorithm.",
    params_schema: SEARCH_PARAMS_SCHEMA,
  },
  {
    kind: "random",
    description: "Agent that selects moves uniformly at random.",
    params_schema: {
      additionalProperties: false,
      properties: {},
      title: "RandomAgentParams",
      type: "object",
    },
  },
];

/** A game summary, active and human vs negamax unless overridden. */
export function gameSummary(overrides: Partial<GameSummary> = {}): GameSummary {
  return {
    id: "0c4a3b5e-0000-4000-8000-000000000001",
    name: "Evening game",
    status: "active",
    white: { type: "human" },
    black: { type: "agent", spec: { kind: "negamax", params: {} }, budget_s: 5 },
    result: null,
    ply_count: 12,
    created_at: "2026-10-26T20:00:00Z",
    updated_at: "2026-10-26T21:00:00Z",
    ...overrides,
  };
}
