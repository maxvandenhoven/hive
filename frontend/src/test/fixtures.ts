import type {
  AgentPreset,
  AgentRegistration,
  BoardEstimate,
  GameDetail,
  GamePosition,
  GameSummary,
  Move,
  MoveRead,
  PhotoMatch,
  PhotoRead,
  Rules,
} from "@/api/client";

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

/** Presets shaped like the shipped ones, sorted by name as the API lists them. */
export const AGENT_PRESETS: AgentPreset[] = [
  {
    name: "nm2",
    description: "Negamax searching two plies ahead; quick and easy to beat.",
    spec: { kind: "negamax", params: { depth: 2 }, label: "nm2" },
  },
  {
    name: "nm3",
    description: "Negamax searching three plies ahead; slower and stronger.",
    spec: { kind: "negamax", params: { depth: 3 }, label: "nm3" },
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
    board_location: "table",
    result: null,
    ply_count: 12,
    current_player: "white",
    current_player_type: "human",
    pending_move: false,
    created_at: "2026-10-26T20:00:00Z",
    updated_at: "2026-10-26T21:00:00Z",
    ...overrides,
  };
}

/** The default rules, as the API returns them. */
export const RULES: Rules = {
  piece_counts: { queen: 1, beetle: 2, grasshopper: 3, spider: 2, ant: 3 },
  starting_player: "white",
  queen_by_turn: 4,
  allow_queen_first_turn: true,
  move_before_queen: false,
  max_turns: null,
};

/** A stored move, a manual placement of the white queen at the origin unless overridden. */
export function moveRead(overrides: Partial<MoveRead> = {}): MoveRead {
  return {
    ply: 0,
    move: { piece: "queen", from: null, to: [0, 0] },
    source: "manual",
    photo_id: null,
    decision: null,
    pending: false,
    created_at: "2026-10-26T20:01:00Z",
    ...overrides,
  };
}

/** The moves of `gamePosition()`: both queens placed, white at the origin. */
export const OPENING_MOVES: MoveRead[] = [
  moveRead(),
  moveRead({
    ply: 1,
    move: { piece: "queen", from: null, to: [1, 0] },
    source: "agent",
    created_at: "2026-10-26T20:02:00Z",
  }),
];

/** A game with its moves, `gameSummary()` after `OPENING_MOVES` unless overridden. */
export function gameDetail(overrides: Partial<GameDetail> = {}): GameDetail {
  return {
    ...gameSummary({ ply_count: OPENING_MOVES.length }),
    rules: RULES,
    setup: null,
    moves: OPENING_MOVES,
    ...overrides,
  };
}

/** The position after `OPENING_MOVES`, with white (the human side) to move. */
export function gamePosition(overrides: Partial<GamePosition> = {}): GamePosition {
  return {
    ply: 2,
    ply_count: 2,
    board: [
      { coord: [0, 0], stack: [{ piece: "queen", owner: "white" }] },
      { coord: [1, 0], stack: [{ piece: "queen", owner: "black" }] },
    ],
    hands: {
      white: { queen: 0, beetle: 2, grasshopper: 3, spider: 2, ant: 3 },
      black: { queen: 0, beetle: 2, grasshopper: 3, spider: 2, ant: 3 },
    },
    current_player: "white",
    result: null,
    last_move: OPENING_MOVES[1] ?? null,
    movable_pieces: [{ coord: [0, 0], piece: "queen" }],
    placeable_coords: [
      [-1, 0],
      [-1, 1],
      [0, -1],
    ],
    placeable_piece_types: ["beetle", "grasshopper", "spider", "ant"],
    must_pass: false,
    pending_move: false,
    ...overrides,
  };
}

/** A candidate move of a photo with its probability. */
export function photoCandidate(moves: (Move | null)[], probability: number) {
  return { moves, probability, log_likelihood: Math.log(probability), conflicts: 0 };
}

/** What a photo of a person's move showed: one clear move unless overridden. */
export function photoMatch(overrides: Partial<PhotoMatch> = {}): PhotoMatch {
  return {
    purpose: "move",
    resolution: {
      status: "resolved",
      candidates: [photoCandidate([{ piece: "ant", from: null, to: [-1, 0] }], 0.98)],
      reason: null,
    },
    verification: null,
    photo_ids: ["0c4a3b5e-0000-4000-8000-0000000000f1"],
    previous_photo_id: null,
    tile_count: 3,
    edge: false,
    ...overrides,
  };
}

/** A read photo of the game of `gameDetail()` for ply 2. */
export function photoRead(overrides: Partial<PhotoRead> = {}): PhotoRead {
  return {
    id: "0c4a3b5e-0000-4000-8000-0000000000f1",
    game_id: "0c4a3b5e-0000-4000-8000-000000000001",
    ply: 2,
    width: 1024,
    height: 768,
    reader: "yolo",
    model_version: "hive-yolo-seg/v001",
    confirmed: false,
    created_at: "2026-10-26T20:03:00Z",
    match: photoMatch(),
    ...overrides,
  };
}

/** A board read from one photo: both queens, clearly. */
export function boardEstimate(overrides: Partial<BoardEstimate> = {}): BoardEstimate {
  return {
    status: "confident",
    tiles: [
      {
        coord: [0, 0],
        piece: { piece: "queen", owner: "white" },
        probability: 0.97,
        raised: false,
        origin: [2, 1],
      },
      {
        coord: [1, 0],
        piece: { piece: "queen", owner: "black" },
        probability: 0.95,
        raised: false,
        origin: [3, 1],
      },
    ],
    board: [
      { coord: [0, 0], stack: [{ piece: "queen", owner: "white" }] },
      { coord: [1, 0], stack: [{ piece: "queen", owner: "black" }] },
    ],
    lowest_probability: 0.95,
    players: ["white", "black"],
    ignored: 0,
    reasons: [],
    ...overrides,
  };
}
