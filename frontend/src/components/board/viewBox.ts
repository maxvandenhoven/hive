/*
 * The part of the board an SVG shows, in board units (hexes of radius 1). The SVG scales
 * its `viewBox` to fit, so fitting the board needs no measuring.
 */
import {
  axialToPixel,
  HEX_HALF_WIDTH,
  hexKey,
  hexNeighbors,
  type PixelPoint,
} from "@/components/board/hex";
import type { HexCoord } from "@/components/board/types";

export interface ViewBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** The narrowest and widest a view may be zoomed, in board units. */
export interface ViewBoxLimits {
  minWidth: number;
  maxWidth: number;
}

/** The smallest fitted view, about four hexes across, so a few tiles are not huge. */
export const FIT_MIN_WIDTH = 8;
export const FIT_MIN_HEIGHT = 7;

/** The room around the outermost hexes of a fitted view. */
const FIT_PADDING = 0.25;

/**
 * The view of the stacks and every hex next to them, where moves can go.
 *
 * Fitting the neighbours too keeps every legal target in view and the view steady while
 * pieces are selected. An empty board shows the hexes around the origin.
 */
export function fitViewBox(occupied: HexCoord[]): ViewBox {
  const coords = new Map<string, HexCoord>();

  for (const coord of occupied.length > 0 ? occupied : [[0, 0] as HexCoord]) {
    for (const hex of [coord, ...hexNeighbors(coord)]) {
      coords.set(hexKey(hex), hex);
    }
  }

  const centres = [...coords.values()].map((coord) => axialToPixel(coord));
  const left = Math.min(...centres.map(({ x }) => x)) - HEX_HALF_WIDTH - FIT_PADDING;
  const right = Math.max(...centres.map(({ x }) => x)) + HEX_HALF_WIDTH + FIT_PADDING;
  const top = Math.min(...centres.map(({ y }) => y)) - 1 - FIT_PADDING;
  const bottom = Math.max(...centres.map(({ y }) => y)) + 1 + FIT_PADDING;
  const width = Math.max(right - left, FIT_MIN_WIDTH);
  const height = Math.max(bottom - top, FIT_MIN_HEIGHT);

  return {
    x: (left + right) / 2 - width / 2,
    y: (top + bottom) / 2 - height / 2,
    width,
    height,
  };
}

/** Move the view by an offset in board units. */
export function panViewBox(view: ViewBox, offset: PixelPoint): ViewBox {
  return { ...view, x: view.x + offset.x, y: view.y + offset.y };
}

interface ZoomViewBoxOptions {
  view: ViewBox;
  /** How much wider the view gets: below 1 zooms in, above 1 zooms out. */
  factor: number;
  /** The board point that stays in place on the screen. */
  focus: PixelPoint;
  limits: ViewBoxLimits;
}

/** Zoom the view around a point, keeping its width within the limits. */
export function zoomViewBox({
  view,
  factor,
  focus,
  limits,
}: ZoomViewBoxOptions): ViewBox {
  const width = Math.min(Math.max(view.width * factor, limits.minWidth), limits.maxWidth);
  const scale = width / view.width;

  return {
    x: focus.x - (focus.x - view.x) * scale,
    y: focus.y - (focus.y - view.y) * scale,
    width,
    height: view.height * scale,
  };
}

/** The view as an SVG `viewBox` attribute. */
export function viewBoxAttribute({ x, y, width, height }: ViewBox): string {
  return [x, y, width, height].map((value) => Math.round(value * 1000) / 1000).join(" ");
}
