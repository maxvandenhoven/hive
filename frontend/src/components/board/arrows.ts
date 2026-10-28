/*
 * The geometry of move arrows and of the arc a moving tile travels along, in board units.
 * Both bend the same way, away from the hive where they can, so a tile follows its
 * arrow.
 */
import { axialToPixel, type PixelPoint } from "@/components/board/hex";
import type { HexCoord } from "@/components/board/types";

/** How far the middle of an arc bends from the straight line, per unit of its length. */
const ARC_BEND = 0.2;

/** The least and the most an arc bends: short arrows still curve, long ones stay calm. */
const ARC_BEND_MIN = 0.3;
const ARC_BEND_MAX = 1.2;

/** How far from the centre of its source hex an arrow starts. */
export const ARROW_START_OFFSET = 0.25;

/**
 * How far from the centre of its target an arrow ends: at the edge of the tile there, so
 * the head stays visible next to it.
 */
export const ARROW_END_OFFSET = 0.8;

/** The length and the width of an arrow head. */
const HEAD_LENGTH = 0.4;
const HEAD_WIDTH = 0.42;

/** Which side of the straight line from source to target an arc bends to. */
export type ArcSide = "left" | "right";

/** A quadratic curve from the centre of one hex to the centre of another. */
export interface MoveArc {
  from: PixelPoint;
  control: PixelPoint;
  to: PixelPoint;
  side: ArcSide;
}

/** A move arrow: a curved line and a head whose tip is at the edge of the target. */
export interface MoveArrowGeometry {
  /** The SVG path of the line, from near the source to the base of the head. */
  path: string;
  /** The tip of the head and its two back corners. */
  head: [PixelPoint, PixelPoint, PixelPoint];
}

function distance(a: PixelPoint, b: PixelPoint): number {
  return Math.hypot(b.x - a.x, b.y - a.y);
}

/** The point at `length` from `from` towards `towards`. */
function stepTowards(from: PixelPoint, towards: PixelPoint, length: number): PixelPoint {
  const total = distance(from, towards);

  return total === 0
    ? from
    : {
        x: from.x + ((towards.x - from.x) * length) / total,
        y: from.y + ((towards.y - from.y) * length) / total,
      };
}

/** The centre of the stacks on the board, or `null` for an empty board. */
export function hiveCentre(coords: HexCoord[]): PixelPoint | null {
  if (coords.length === 0) {
    return null;
  }

  const points = coords.map((coord) => axialToPixel(coord));

  return {
    x: points.reduce((sum, point) => sum + point.x, 0) / points.length,
    y: points.reduce((sum, point) => sum + point.y, 0) / points.length,
  };
}

/**
 * The arc of a move from one hex to another. It bends to the side away from `centre`
 * (the centre of the hive), or to the left (as seen along the move) when the centre is
 * on the line or unknown.
 */
export function moveArc({
  from,
  to,
  centre,
}: {
  from: HexCoord;
  to: HexCoord;
  centre: PixelPoint | null;
}): MoveArc {
  const start = axialToPixel(from);
  const end = axialToPixel(to);
  const length = distance(start, end);
  const middle = { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 };

  if (length === 0) {
    return { from: start, control: middle, to: end, side: "left" };
  }

  // The unit normal to the left of the move; `y` points down, as on the screen.
  const left = { x: (end.y - start.y) / length, y: -(end.x - start.x) / length };
  const centreSide =
    centre === null ? 0 : (centre.x - middle.x) * left.x + (centre.y - middle.y) * left.y;
  const side: ArcSide = centreSide > 1e-6 ? "right" : "left";
  const sign = side === "left" ? 1 : -1;
  const bend = Math.min(Math.max(length * ARC_BEND, ARC_BEND_MIN), ARC_BEND_MAX);
  // The middle of a quadratic curve lies halfway between its control point and the line.
  const control = {
    x: middle.x + left.x * sign * bend * 2,
    y: middle.y + left.y * sign * bend * 2,
  };

  return { from: start, control, to: end, side };
}

/** The point at `progress` (0 to 1) along an arc. */
export function pointOnArc(arc: MoveArc, progress: number): PixelPoint {
  const rest = 1 - progress;
  const weights = [rest * rest, 2 * rest * progress, progress * progress] as const;

  return {
    x: weights[0] * arc.from.x + weights[1] * arc.control.x + weights[2] * arc.to.x,
    y: weights[0] * arc.from.y + weights[1] * arc.control.y + weights[2] * arc.to.y,
  };
}

function formatPoint({ x, y }: PixelPoint): string {
  return `${Math.round(x * 1000) / 1000} ${Math.round(y * 1000) / 1000}`;
}

/**
 * The arrow along an arc: it starts a little off the centre of the source and its tip
 * ends at the edge of the target, so neither covers the tiles there.
 */
export function moveArrow(arc: MoveArc): MoveArrowGeometry {
  const start = stepTowards(arc.from, arc.control, ARROW_START_OFFSET);
  const tip = stepTowards(arc.to, arc.control, ARROW_END_OFFSET);
  const base = stepTowards(tip, arc.control, HEAD_LENGTH);
  const across = distance(tip, base) === 0 ? 0 : HEAD_WIDTH / 2 / distance(tip, base);
  const corner = (sign: number) => ({
    x: base.x - (tip.y - base.y) * across * sign,
    y: base.y + (tip.x - base.x) * across * sign,
  });

  return {
    path: `M ${formatPoint(start)} Q ${formatPoint(arc.control)} ${formatPoint(base)}`,
    head: [tip, corner(1), corner(-1)],
  };
}
