/*
 * The marks a board renderer draws, each with one meaning, and how the legend explains
 * them. The marks themselves are drawn by `marks.tsx`.
 */
import { hexKey } from "@/components/board/hex";
import type { BoardRendererProps } from "@/components/board/types";

/** A kind of mark on the board. */
export type BoardMarkKind =
  "movable" | "selected" | "target" | "climb" | "lastMove" | "suggestion" | "forbidden";

/** How the legend explains a mark. */
export interface BoardMarkInfo {
  kind: BoardMarkKind;
  label: string;
  description: string;
}

/** Every mark, in the order the legend lists them. */
export const BOARD_MARKS: readonly BoardMarkInfo[] = [
  {
    kind: "movable",
    label: "Can move",
    description: "A raised tile with a ring; tap it to see where it can go.",
  },
  {
    kind: "selected",
    label: "Selected",
    description: "The tile or hand piece you picked.",
  },
  {
    kind: "target",
    label: "Can go here",
    description: "A dashed hex with a dot; tap it to play the move.",
  },
  {
    kind: "climb",
    label: "Can climb on top",
    description: "A dashed ring with a dot on a tile a beetle can climb.",
  },
  {
    kind: "lastMove",
    label: "Last move",
    description: "A dotted outline where it came from and where it went.",
  },
  {
    kind: "suggestion",
    label: "Agent suggestion",
    description: "An arrow to a double ring: an agent's best move or the move to make.",
  },
  {
    kind: "forbidden",
    label: "Not allowed",
    description: "A crossed out hex, used in the rule diagrams.",
  },
];

/** The props of a renderer that decide which marks it draws. */
export type BoardMarkProps = Pick<
  BoardRendererProps,
  | "board"
  | "highlights"
  | "movable"
  | "selected"
  | "lastMove"
  | "proposedMove"
  | "forbidden"
>;

/** The kinds of mark a renderer draws for these props, in legend order. */
export function boardMarksShown({
  board,
  highlights,
  movable,
  selected,
  lastMove,
  proposedMove,
  forbidden = [],
}: BoardMarkProps): BoardMarkKind[] {
  const occupied = new Set(board.map((stack) => hexKey(stack.coord)));
  const climbs = highlights.filter((coord) => occupied.has(hexKey(coord)));
  const shown: Record<BoardMarkKind, boolean> = {
    movable: movable.length > 0,
    selected: selected !== null,
    target: climbs.length < highlights.length,
    climb: climbs.length > 0,
    lastMove: lastMove !== null,
    suggestion: proposedMove !== null,
    forbidden: forbidden.length > 0,
  };

  return BOARD_MARKS.map(({ kind }) => kind).filter((kind) => shown[kind]);
}
