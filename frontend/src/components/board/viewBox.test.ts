import { describe, expect, it } from "vitest";

import { axialToPixel, HEX_HALF_WIDTH } from "@/components/board/hex";
import {
  FIT_MIN_HEIGHT,
  FIT_MIN_WIDTH,
  fitViewBox,
  panViewBox,
  viewBoxAttribute,
  visibleViewBox,
  zoomViewBox,
  type ViewBox,
} from "@/components/board/viewBox";

function contains(view: ViewBox, x: number, y: number): boolean {
  return (
    x >= view.x && x <= view.x + view.width && y >= view.y && y <= view.y + view.height
  );
}

describe("fitViewBox", () => {
  it("shows the hexes around the origin on an empty board", () => {
    const view = fitViewBox([]);

    expect(view.width).toBe(FIT_MIN_WIDTH);
    expect(view.height).toBe(FIT_MIN_HEIGHT);
    expect(view.x + view.width / 2).toBeCloseTo(0);
    expect(view.y + view.height / 2).toBeCloseTo(0);
  });

  it("keeps a small board at the minimum size around its centre", () => {
    const view = fitViewBox([
      [0, 0],
      [1, 0],
    ]);
    const centre = axialToPixel([1, 0]).x / 2;

    expect(view.width).toBe(FIT_MIN_WIDTH);
    expect(view.x + view.width / 2).toBeCloseTo(centre);
  });

  it("shows every stack and its neighbours on a large board", () => {
    const coords: [number, number][] = [
      [0, 0],
      [1, 0],
      [2, 0],
      [3, 0],
      [4, -1],
      [-1, 2],
      [-2, 3],
    ];
    const view = fitViewBox(coords);

    for (const coord of coords) {
      const { x, y } = axialToPixel(coord);

      // The neighbours on every side are inside the view.
      expect(contains(view, x - 2 * HEX_HALF_WIDTH - HEX_HALF_WIDTH, y)).toBe(true);
      expect(contains(view, x + 3 * HEX_HALF_WIDTH, y)).toBe(true);
      expect(contains(view, x, y - 2.5)).toBe(true);
      expect(contains(view, x, y + 2.5)).toBe(true);
    }

    expect(view.width).toBeGreaterThan(FIT_MIN_WIDTH);
    expect(view.height).toBeGreaterThan(FIT_MIN_HEIGHT);
  });
});

describe("panViewBox", () => {
  it("moves the view by board units", () => {
    expect(panViewBox({ x: 1, y: 2, width: 10, height: 8 }, { x: -3, y: 4 })).toEqual({
      x: -2,
      y: 6,
      width: 10,
      height: 8,
    });
  });
});

describe("zoomViewBox", () => {
  const view: ViewBox = { x: 0, y: 0, width: 10, height: 8 };
  const limits = { minWidth: 4, maxWidth: 40 };

  it("zooms in around the focus, which stays in place", () => {
    const zoomed = zoomViewBox({ view, factor: 0.5, focus: { x: 10, y: 8 }, limits });

    expect(zoomed).toEqual({ x: 5, y: 4, width: 5, height: 4 });
  });

  it("zooms out around the focus", () => {
    const zoomed = zoomViewBox({ view, factor: 2, focus: { x: 5, y: 4 }, limits });

    expect(zoomed).toEqual({ x: -5, y: -4, width: 20, height: 16 });
  });

  it("keeps the width within the limits and the aspect ratio", () => {
    const tiny = zoomViewBox({ view, factor: 0.01, focus: { x: 0, y: 0 }, limits });
    const huge = zoomViewBox({ view, factor: 100, focus: { x: 0, y: 0 }, limits });

    expect(tiny).toEqual({ x: 0, y: 0, width: 4, height: 3.2 });
    expect(huge).toEqual({ x: 0, y: 0, width: 40, height: 32 });
  });
});

describe("viewBoxAttribute", () => {
  it("formats the view with rounded numbers", () => {
    expect(viewBoxAttribute({ x: -1.23456, y: 2, width: 10.00001, height: 8 })).toBe(
      "-1.235 2 10 8",
    );
  });
});

describe("visibleViewBox", () => {
  const view: ViewBox = { x: -4, y: -3, width: 8, height: 6 };

  it("widens the view on a wide screen, around its centre", () => {
    expect(visibleViewBox(view, { width: 800, height: 300 })).toEqual({
      x: -8,
      y: -3,
      width: 16,
      height: 6,
    });
  });

  it("heightens the view on a tall screen", () => {
    expect(visibleViewBox(view, { width: 400, height: 600 })).toEqual({
      x: -4,
      y: -6,
      width: 8,
      height: 12,
    });
  });

  it("keeps the view before the SVG is laid out", () => {
    expect(visibleViewBox(view, { width: 0, height: 0 })).toEqual(view);
  });
});
