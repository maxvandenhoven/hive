/*
 * The background hex grid of the board: the hexes in view, and one SVG path that outlines
 * them. Hexes have radius 1 and are centred on `axialToPixel`, so the grid lines up with
 * the tiles at any pan and zoom.
 */
import { axialToPixel, HEX_HALF_WIDTH, hexPoints } from "@/components/board/hex";
import type { HexCoord } from "@/components/board/types";
import type { ViewBox } from "@/components/board/viewBox";

const SQRT3 = Math.sqrt(3);

/** Every hex that overlaps the view, row by row. */
export function gridCells(view: ViewBox): HexCoord[] {
  const cells: HexCoord[] = [];
  const firstRow = Math.floor((view.y - 1) / 1.5);
  const lastRow = Math.ceil((view.y + view.height + 1) / 1.5);

  for (let r = firstRow; r <= lastRow; r++) {
    const firstColumn = Math.floor((view.x - HEX_HALF_WIDTH) / SQRT3 - r / 2);
    const lastColumn = Math.ceil((view.x + view.width + HEX_HALF_WIDTH) / SQRT3 - r / 2);

    for (let q = firstColumn; q <= lastColumn; q++) {
      cells.push([q, r]);
    }
  }

  return cells;
}

/** The outlines of the hexes as one SVG path. */
export function gridPath(cells: HexCoord[]): string {
  return cells.map((cell) => `M${hexPoints(axialToPixel(cell))}Z`).join("");
}
