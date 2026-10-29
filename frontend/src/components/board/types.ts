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
  /** Draw a small static diagram for the help, without the key and zoom buttons. */
  diagram?: boolean;
  onHexClick: (coord: HexCoord) => void;
}

/** A component that draws the board, such as `SvgBoard`. */
export type BoardRenderer = ComponentType<BoardRendererProps>;
