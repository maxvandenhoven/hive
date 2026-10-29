/*
 * The rule diagrams of the help, written by `scripts/rules_diagrams.py` with their
 * allowed targets computed by the engine (`make rules-diagrams`), and how they are
 * stepped through.
 */
import type { BoardCell, PieceType } from "@/api/client";
import { hexKey, sameHex } from "@/components/board/hex";
import type { BoardView, HexCoord, MoveView } from "@/components/board/types";
import rulesDiagramsJson from "@/components/help/rulesDiagrams.json";
import { PIECE_NAMES } from "@/lib/moves";
import { SIDE_TITLES, type PlayerSide } from "@/lib/players";

/** One rule diagram as the script writes it. */
export interface RulesDiagramData {
  id: string;
  caption: string;
  board: BoardCell[];
  current_player: PlayerSide;
  /** The piece that moves or is placed, or `null` for a diagram without a move. */
  piece: PieceType | null;
  /** Where the piece moves from, or `null` for a placement. */
  source: HexCoord | null;
  /** The targets the engine allows. */
  allowed: HexCoord[];
  /** Targets listed by hand that the engine does not allow. */
  forbidden: HexCoord[];
  /** The hexes the piece passes through, empty when the move is not stepped. */
  path: HexCoord[];
  must_pass: boolean;
  result: PlayerSide | "draw" | null;
}

/** Every rule diagram, in the order of the rules reference. */
export const RULES_DIAGRAMS = rulesDiagramsJson.diagrams as RulesDiagramData[];

/** The rule diagram with this id. */
export function rulesDiagram(id: string): RulesDiagramData {
  const diagram = RULES_DIAGRAMS.find((candidate) => candidate.id === id);

  if (diagram === undefined) {
    throw new Error(`There is no rule diagram "${id}".`);
  }

  return diagram;
}

/** One position while stepping through a move, with the step just made. */
export interface DiagramStep {
  board: BoardView;
  lastMove: MoveView;
}

/** The board with the top piece of one hex moved on top of another. */
export function moveTopPiece(board: BoardView, from: HexCoord, to: HexCoord): BoardView {
  const piece = board.find((stack) => sameHex(stack.coord, from))?.pieces[0];

  if (piece === undefined) {
    return board;
  }

  const moved = board
    .map((stack) =>
      sameHex(stack.coord, from) ? { ...stack, pieces: stack.pieces.slice(1) } : stack,
    )
    .filter((stack) => stack.pieces.length > 0);
  const target = moved.find((stack) => hexKey(stack.coord) === hexKey(to));

  return target === undefined
    ? [...moved, { coord: to, pieces: [piece] }]
    : moved.map((stack) =>
        stack === target ? { ...stack, pieces: [piece, ...stack.pieces] } : stack,
      );
}

/** The positions after each step along the path of a diagram's move. */
export function diagramSteps(board: BoardView, path: HexCoord[]): DiagramStep[] {
  const steps: DiagramStep[] = [];
  let current = board;

  for (const [index, to] of path.entries()) {
    const from = path[index - 1];

    if (from !== undefined) {
      current = moveTopPiece(current, from, to);
      steps.push({ board: current, lastMove: { from, to } });
    }
  }

  return steps;
}

/** What a diagram shows in a few words, such as `White places a spider`. */
export function describeDiagram(diagram: RulesDiagramData): string {
  const side = SIDE_TITLES[diagram.current_player];

  if (diagram.result !== null) {
    return diagram.result === "draw" ? "Draw" : `${SIDE_TITLES[diagram.result]} wins`;
  }

  if (diagram.must_pass) {
    return `${side} must pass`;
  }

  if (diagram.piece === null) {
    return `${side} to move`;
  }

  const piece = PIECE_NAMES[diagram.piece].toLowerCase();

  return diagram.source === null
    ? `${side} places a ${piece}`
    : `${side} moves the ${piece}`;
}
