import type { BoardCell, GameDetail, Move, Piece, PieceType } from "@/api/client";
import { formatHex, hexKey, hexNeighbors, sameHex } from "@/components/board/hex";
import type { BoardView, HexCoord, MoveView } from "@/components/board/types";
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

/** The words for small counts, as a sentence spells them. */
const COUNT_WORDS = ["no", "one", "two", "three", "four", "five", "six"];

/** The top pieces of the stacks around a hex, by stacks keyed with `hexKey`. */
function piecesAround(stacks: Map<string, Piece[]>, coord: HexCoord): Piece[] {
  return hexNeighbors(coord).flatMap((neighbor) => {
    const top = stacks.get(hexKey(neighbor))?.[0];

    return top === undefined ? [] : [top];
  });
}

/**
 * Pieces as a sentence lists them, such as `the white queen, two black ants and the
 * black beetle`: white first, then in the order of `PIECE_TYPES`.
 */
export function listPieces(pieces: Piece[]): string {
  const counts = new Map<string, { piece: Piece; count: number }>();
  const sorted = [...pieces].sort(
    (a, b) =>
      Number(a.owner === "black") - Number(b.owner === "black") ||
      PIECE_TYPES.indexOf(a.piece) - PIECE_TYPES.indexOf(b.piece),
  );

  for (const piece of sorted) {
    const key = `${piece.owner} ${piece.piece}`;
    const entry = counts.get(key);
    counts.set(key, { piece, count: (entry?.count ?? 0) + 1 });
  }

  const names = [...counts.values()].map(({ piece, count }) => {
    const name = `${piece.owner} ${PIECE_NAMES[piece.piece].toLowerCase()}`;

    return count === 1 ? `the ${name}` : `${COUNT_WORDS[count] ?? count} ${name}s`;
  });
  const last = names.pop() ?? "";

  return names.length === 0 ? last : `${names.join(", ")} and ${last}`;
}

/** The board before a move, from the board after it: the moved piece goes back. */
export function boardBeforeMove(board: BoardView, move: Move | null): BoardView {
  if (move === null) {
    return board;
  }

  const target = board.find((stack) => sameHex(stack.coord, move.to));
  const piece = target?.pieces[0];

  if (piece === undefined) {
    return board;
  }

  const before = board
    .map((stack) =>
      sameHex(stack.coord, move.to) ? { ...stack, pieces: stack.pieces.slice(1) } : stack,
    )
    .filter((stack) => stack.pieces.length > 0);

  if (move.from === null) {
    return before;
  }

  const from = move.from;
  const source = before.find((stack) => sameHex(stack.coord, from));

  return source === undefined
    ? [...before, { coord: from, pieces: [piece] }]
    : before.map((stack) =>
        stack === source ? { ...stack, pieces: [piece, ...stack.pieces] } : stack,
      );
}

/**
 * Describe a move by the pieces it touches rather than by coordinates, so it can be made
 * on a physical board from any side: `place ant next to the white queen`, `ant moves
 * next to the white queen and the black beetle`, `beetle climbs onto the black queen`,
 * `grasshopper jumps over the white queen` or `pass`.
 *
 * `board` is the board before the move. When another piece of the same kind and owner
 * could be meant, the piece is told apart by where it stands (`ant beside the black
 * spider moves …`), and by its coordinate if that is not enough.
 */
export function describeMoveOnBoard(move: Move | null, board: BoardView): string {
  if (move === null) {
    return "pass";
  }

  const name = PIECE_NAMES[move.piece].toLowerCase();
  const stacks = new Map(board.map((stack) => [hexKey(stack.coord), stack.pieces]));
  const from = move.from;
  const moving = from === null ? undefined : stacks.get(hexKey(from))?.[0];
  const below = from === null ? [] : (stacks.get(hexKey(from))?.slice(1) ?? []);

  if (from !== null) {
    // The piece leaves its hex, so it is not a neighbour of where it goes.
    stacks.set(hexKey(from), below);
  }

  const covered = stacks.get(hexKey(move.to))?.[0];
  const around = piecesAround(stacks, move.to);
  let target = `next to ${listPieces(around)}`;

  if (covered !== undefined) {
    target = `onto ${listPieces([covered])}`;
  } else if (around.length === 0) {
    target = from === null ? "as the first piece" : `to ${formatHex(move.to)}`;
  }

  if (from === null || moving === undefined) {
    return `place ${name} ${target}`;
  }

  const subject = `${name}${describeSource({ board, from, moving })}`;

  if (move.piece === "grasshopper") {
    const jumped = hexesBetween(from, move.to).flatMap((coord) => {
      const top = stacks.get(hexKey(coord))?.[0];

      return top === undefined ? [] : [top];
    });

    return `${subject} jumps over ${listPieces(jumped)}`;
  }

  if (covered !== undefined) {
    return `${subject} climbs ${target}`;
  }

  return below.length > 0
    ? `${subject} climbs down ${target}`
    : `${subject} moves ${target}`;
}

/**
 * Where a moving piece stands, when another piece of the same kind and owner could be
 * meant: ` on the white queen`, ` beside the black spider` or with its coordinate.
 */
function describeSource({
  board,
  from,
  moving,
}: {
  board: BoardView;
  from: HexCoord;
  moving: Piece;
}): string {
  const twins = board.filter(
    (stack) =>
      !sameHex(stack.coord, from) &&
      stack.pieces[0]?.piece === moving.piece &&
      stack.pieces[0].owner === moving.owner,
  );

  if (twins.length === 0) {
    return "";
  }

  const stacks = new Map(board.map((stack) => [hexKey(stack.coord), stack.pieces]));
  const place = (coord: HexCoord): string => {
    const under = stacks.get(hexKey(coord))?.[1];

    return under === undefined
      ? `beside ${listPieces(piecesAround(stacks, coord))}`
      : `on ${listPieces([under])}`;
  };
  const own = place(from);

  return twins.some((twin) => place(twin.coord) === own)
    ? ` at ${formatHex(from)}`
    : ` ${own}`;
}

/** The hexes strictly between two hexes on one line, as a grasshopper jumps. */
function hexesBetween(from: HexCoord, to: HexCoord): HexCoord[] {
  const dq = to[0] - from[0];
  const dr = to[1] - from[1];
  const steps = Math.max(Math.abs(dq), Math.abs(dr), Math.abs(dq + dr));

  if (steps < 2) {
    return [];
  }

  return Array.from({ length: steps - 1 }, (_, index) => [
    from[0] + (dq / steps) * (index + 1),
    from[1] + (dr / steps) * (index + 1),
  ]);
}

/** A description that starts a sentence, with a capital first letter. */
export function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
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

/** The move to mark on the board, or `null` for none, such as after a pass. */
export function toMoveView(move: Move | null | undefined): MoveView | null {
  return move == null ? null : { from: move.from, to: move.to };
}
