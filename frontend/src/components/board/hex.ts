/*
 * Axial hex grid math for the pointy-top grid of the engine, ported from
 * `src/hive/plotting/svg/geometry.py`. Sizes are the radius of a hex, centre to corner.
 */
import type { HexCoord } from "@/components/board/types";

/** A point in board units, with `y` pointing down as in SVG. */
export interface PixelPoint {
  x: number;
  y: number;
}

const SQRT3 = Math.sqrt(3);

/** The six neighbour offsets, east first and then anticlockwise, as in `engine/grid.py`. */
export const HEX_DIRECTIONS: readonly HexCoord[] = [
  [1, 0],
  [1, -1],
  [0, -1],
  [-1, 0],
  [-1, 1],
  [0, 1],
];

/** Half the width of a pointy-top hex of radius 1; half its height is 1. */
export const HEX_HALF_WIDTH = SQRT3 / 2;

/** The centre of a hex. */
export function axialToPixel([q, r]: HexCoord, size = 1): PixelPoint {
  return { x: size * SQRT3 * (q + r / 2), y: size * 1.5 * r };
}

/** The hex that contains a point, the inverse of `axialToPixel`. */
export function pixelToAxial({ x, y }: PixelPoint, size = 1): HexCoord {
  const q = ((SQRT3 / 3) * x - y / 3) / size;
  const r = ((2 / 3) * y) / size;

  return roundAxial(q, r);
}

/** Round fractional axial coordinates to the hex that contains them, in cube space. */
function roundAxial(q: number, r: number): HexCoord {
  const s = -q - r;
  let roundedQ = Math.round(q);
  let roundedR = Math.round(r);
  const roundedS = Math.round(s);
  const errorQ = Math.abs(roundedQ - q);
  const errorR = Math.abs(roundedR - r);
  const errorS = Math.abs(roundedS - s);

  if (errorQ > errorR && errorQ > errorS) {
    roundedQ = -roundedR - roundedS;
  } else if (errorR > errorS) {
    roundedR = -roundedQ - roundedS;
  }

  // Adding zero turns a negative zero into zero.
  return [roundedQ + 0, roundedR + 0];
}

/** The six corners of a hex, clockwise from the lower right one. */
export function hexCorners(center: PixelPoint, size = 1): PixelPoint[] {
  return Array.from({ length: 6 }, (_, index) => {
    const angle = (Math.PI / 180) * (60 * index + 30);

    return { x: center.x + size * Math.cos(angle), y: center.y + size * Math.sin(angle) };
  });
}

/** The corners of a hex as an SVG `points` attribute. */
export function hexPoints(center: PixelPoint, size = 1): string {
  return hexCorners(center, size)
    .map(({ x, y }) => `${roundForSvg(x)},${roundForSvg(y)}`)
    .join(" ");
}

function roundForSvg(value: number): number {
  return Math.round(value * 1000) / 1000 + 0;
}

/** The number of steps between two hexes. */
export function hexDistance(a: HexCoord, b: HexCoord): number {
  const dq = a[0] - b[0];
  const dr = a[1] - b[1];

  return (Math.abs(dq) + Math.abs(dq + dr) + Math.abs(dr)) / 2;
}

/** The six neighbours of a hex, in the order of `HEX_DIRECTIONS`. */
export function hexNeighbors([q, r]: HexCoord): HexCoord[] {
  return HEX_DIRECTIONS.map(([dq, dr]) => [q + dq, r + dr]);
}

export function sameHex(a: HexCoord, b: HexCoord): boolean {
  return a[0] === b[0] && a[1] === b[1];
}

/** A string that identifies a hex, for keys and sets. */
export function hexKey([q, r]: HexCoord): string {
  return `${q},${r}`;
}

/** A hex as the engine prints it, such as `(1, -2)`. */
export function formatHex([q, r]: HexCoord): string {
  return `(${q}, ${r})`;
}
