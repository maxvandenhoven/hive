import type { ComponentType } from "react";

import type { Coordinate, Piece } from "@/api/client";

/** An axial coordinate `[q, r]` on the pointy-top hex grid of the engine. */
export type HexCoord = Coordinate;

/** The pieces on one hex, top piece first. */
export interface BoardStack {
  coord: HexCoord;
  pieces: Piece[];
}

/** The stacks on the board. */
export type BoardView = BoardStack[];

/** A move to mark on the board, from `null` for a placement. */
export interface MoveView {
  from: HexCoord | null;
  to: HexCoord;
}

/** How a piece arrives on its hex: placed from the hand, moved, or climbing a stack. */
export type BoardTransitionKind = "place" | "move" | "climb";

/**
 * A move to animate, set when the position shown advances by exactly one ply: a live
 * move, a committed agent move or a replay step forward. Jumps, steps back and undo show
 * the new position at once and have none.
 *
 * The board passed with it is already the position after the move, so a renderer draws
 * the moved piece on `to` and animates it in: a placement drops onto its hex, a move or
 * climb travels from `from` along an arc, ending on top of a stack for a climb while the
 * pieces below stay put. A new `key` starts a new animation and cancels a running one;
 * the same key never animates twice. Animations never delay input.
 */
export interface BoardTransition {
  /** Identifies the ply and its move. */
  key: string;
  kind: BoardTransitionKind;
  /** The piece that moved, as it stands on top of `to`. */
  piece: Piece;
  /** Where the piece came from, `null` for a placement. */
  from: HexCoord | null;
  to: HexCoord;
}

/**
 * What a board renderer draws and reports; renderers know nothing about the game.
 *
 * Every hex the renderer draws reports clicks through `onHexClick`, also empty ones;
 * interaction code decides what a click means. Tapping a stack of two or more pieces
 * shows its contents.
 */
export interface BoardRendererProps {
  board: BoardView;
  /** The hexes a click plays a move to: legal targets or placements. */
  highlights: HexCoord[];
  /** The tiles that may move, ringed and raised. */
  movable: HexCoord[];
  selected: HexCoord | null;
  lastMove: MoveView | null;
  /**
   * A move an agent suggests: its best move while thinking, the move to make on the
   * table or a hint. They share one mark and never show at once, so it has no kind.
   */
  proposedMove: MoveView | null;
  /** Hexes marked "not allowed", for the rule diagrams; games leave it out. */
  forbidden?: HexCoord[];
  /** The move to animate, if the position shown just advanced by one ply. */
  transition?: BoardTransition | null;
  onHexClick: (coord: HexCoord) => void;
}

/** A component that draws the board, such as `SvgBoard`. */
export type BoardRenderer = ComponentType<BoardRendererProps>;
