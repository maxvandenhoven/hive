import type { PlayerSide } from "@/lib/players";

/**
 * The raw values of the board colour tokens in `index.css`, for renderers that cannot
 * use Tailwind classes. Components that can should use the classes, for example
 * `fill-board-target`. Each colour has one meaning; see the Theme section of
 * `docs/plans/frontend.md`.
 */
export const BOARD_COLORS = {
  /** The background of the board. */
  surface: "#d5dde5",
  /** The background hex grid. */
  grid: "rgb(28 37 48 / 16%)",
  /** The outline of every tile. */
  tileStroke: "#4a5562",
  /** Tiles that can move, and the selection. */
  movable: "#2b7fd6",
  /** Where the selection can go; "allowed" in rule diagrams. */
  target: "#2f9e6b",
  /** "Not allowed" in rule diagrams. */
  forbidden: "#d64545",
  /** The last move. */
  lastMove: "#e0a526",
  /** A move suggested by an agent: its best move while thinking, a move to make, a hint. */
  suggestion: "#8b5cf6",
} as const;

/** The tile colour of each side. */
export const TILE_COLORS: Record<PlayerSide, string> = {
  white: "#f6f1e6",
  black: "#2a2f36",
};

/** The Tailwind fill class of each side's tiles. */
export const TILE_FILL_CLASSES: Record<PlayerSide, string> = {
  white: "fill-tile-white",
  black: "fill-tile-black",
};
