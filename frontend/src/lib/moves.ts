import type { BoardCell, GameDetail, Move, MoveRead, PieceType } from "@/api/client";
import { formatHex } from "@/components/board/hex";
import type { BoardView, MoveView } from "@/components/board/types";
import type { PlayerSide } from "@/lib/players";

/** The piece types in the order of the engine, queen first. */
export const PIECE_TYPES: PieceType[] = [
  "queen",
  "beetle",
  "grasshopper",
  "spider",
  "ant",
];

export const PIECE_NAMES: Record<PieceType, string> = {
  queen: "Queen",
  beetle: "Beetle",
  grasshopper: "Grasshopper",
  spider: "Spider",
  ant: "Ant",
};

/** Describe a move as the engine does, such as `Move ant from (0, 0) to (1, 0)`. */
export function describeMove(move: Move | null): string {
  if (move === null) {
    return "Pass";
  }

  const piece = PIECE_NAMES[move.piece].toLowerCase();

  if (move.from === null) {
    return `Place ${piece} at ${formatHex(move.to)}`;
  }

  return `Move ${piece} from ${formatHex(move.from)} to ${formatHex(move.to)}`;
}

/** The side that plays the move at a record ply, which alternates from the start. */
export function playerAtPly(
  game: Pick<GameDetail, "rules" | "setup">,
  ply: number,
): PlayerSide {
  const first = game.setup?.current_player ?? game.rules.starting_player;
  const second = first === "white" ? "black" : "white";

  return ply % 2 === 0 ? first : second;
}

/** The board of a position as renderers draw it, with the top piece of a stack first. */
export function toBoardView(cells: BoardCell[]): BoardView {
  return cells.map((cell) => ({ coord: cell.coord, pieces: [...cell.stack].reverse() }));
}

/** The move to mark on the board, or `null` at the start and after a pass. */
export function toMoveView(move: MoveRead | null): MoveView | null {
  if (move?.move == null) {
    return null;
  }

  return { from: move.move.from, to: move.move.to };
}
