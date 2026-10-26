import { useState } from "react";

import type { GamePosition, MovablePiece, Move, PieceType } from "@/api/client";
import { usePieceTargets } from "@/api/queries";
import { sameHex } from "@/components/board/hex";
import type { HexCoord } from "@/components/board/types";

/** What the person picked to play: a tile on the board or a piece type in hand. */
export type BoardSelection =
  | { type: "board"; coord: HexCoord; piece: PieceType }
  | { type: "hand"; piece: PieceType };

/** What a click asks for. */
export type BoardIntent =
  | { type: "play"; move: Move }
  | { type: "select"; selection: BoardSelection }
  | { type: "clear" };

interface HexClickContext {
  selection: BoardSelection | null;
  movablePieces: MovablePiece[];
  highlights: HexCoord[];
}

/**
 * The intent of a click on a hex: play the selection to a highlighted hex, select a
 * movable tile, or clear the selection for anything else, including the selected tile.
 */
export function resolveHexClick(
  { selection, movablePieces, highlights }: HexClickContext,
  coord: HexCoord,
): BoardIntent {
  if (selection !== null && highlights.some((highlight) => sameHex(highlight, coord))) {
    const from = selection.type === "board" ? selection.coord : null;

    return { type: "play", move: { piece: selection.piece, from, to: coord } };
  }

  const movable = movablePieces.find((piece) => sameHex(piece.coord, coord));
  const isSelected = selection?.type === "board" && sameHex(selection.coord, coord);

  if (movable === undefined || isSelected) {
    return { type: "clear" };
  }

  return { type: "select", selection: { type: "board", coord, piece: movable.piece } };
}

interface HandClickContext {
  selection: BoardSelection | null;
  placeablePieceTypes: PieceType[];
}

/** The intent of a click on a piece type in hand: select it if it may be placed. */
export function resolveHandClick(
  { selection, placeablePieceTypes }: HandClickContext,
  piece: PieceType,
): BoardIntent {
  const isSelected = selection?.type === "hand" && selection.piece === piece;

  if (!placeablePieceTypes.includes(piece) || isSelected) {
    return { type: "clear" };
  }

  return { type: "select", selection: { type: "hand", piece } };
}

interface BoardInteractionOptions {
  gameId: string;
  /** The latest position, or `undefined` while it loads. */
  position: GamePosition | undefined;
  /** Whether the side to move is played here now: a person's turn in an active game. */
  enabled: boolean;
  onMove: (move: Move) => void;
}

export interface BoardInteraction {
  selection: BoardSelection | null;
  /** The tiles that may move, empty while disabled. */
  movable: HexCoord[];
  /** Where the selection may go: the targets of a tile or the placements of a piece. */
  highlights: HexCoord[];
  clickHex: (coord: HexCoord) => void;
  clickHandPiece: (piece: PieceType) => void;
}

/**
 * The selection state of manual move entry, which turns clicks into legal moves.
 *
 * Selecting a movable tile fetches its targets; selecting a piece type in hand
 * highlights the placements. Clicking a highlighted hex plays the move. Only legal moves
 * are ever played, since moves are built from the targets and placements of the API.
 * The selection is dropped when the position changes or the board is disabled.
 */
export function useBoardInteraction({
  gameId,
  position,
  enabled,
  onMove,
}: BoardInteractionOptions): BoardInteraction {
  const [stored, setStored] = useState<{ ply: number; selection: BoardSelection } | null>(
    null,
  );
  const live = enabled && position !== undefined ? position : null;
  const ply = live?.ply_count ?? 0;
  const selection = live !== null && stored?.ply === ply ? stored.selection : null;
  const targets = usePieceTargets(
    gameId,
    ply,
    selection?.type === "board" ? selection.coord : null,
  );
  const movablePieces = live?.movable_pieces ?? [];
  let highlights: HexCoord[] = [];

  if (selection?.type === "hand") {
    highlights = live?.placeable_coords ?? [];
  } else if (selection?.type === "board") {
    highlights = targets.data?.targets ?? [];
  }

  const apply = (intent: BoardIntent) => {
    if (intent.type === "play") {
      setStored(null);
      onMove(intent.move);
    } else if (intent.type === "select") {
      setStored({ ply, selection: intent.selection });
    } else {
      setStored(null);
    }
  };

  return {
    selection,
    movable: movablePieces.map((piece) => piece.coord),
    highlights,
    clickHex: (coord) => {
      if (live !== null) {
        apply(resolveHexClick({ selection, movablePieces, highlights }, coord));
      }
    },
    clickHandPiece: (piece) => {
      if (live !== null) {
        apply(
          resolveHandClick(
            { selection, placeablePieceTypes: live.placeable_piece_types },
            piece,
          ),
        );
      }
    },
  };
}
