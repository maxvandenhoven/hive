import { describe, expect, it } from "vitest";

import { gridCells, gridPath } from "@/components/board/grid";
import { hexKey, pixelToAxial } from "@/components/board/hex";
import { fitViewBox, zoomViewBox, type ViewBox } from "@/components/board/viewBox";

const FITTED = fitViewBox([
  [0, 0],
  [1, 0],
  [2, -1],
]);
const LIMITS = { minWidth: 1, maxWidth: 1000 };

function zoomed(factor: number): ViewBox {
  return zoomViewBox({
    view: FITTED,
    factor,
    focus: { x: 0.3, y: -0.7 },
    limits: LIMITS,
  });
}

/** Points spread over the view, including its edges and corners. */
function samplePoints(view: ViewBox): { x: number; y: number }[] {
  const steps = 24;

  return Array.from({ length: (steps + 1) ** 2 }, (_, index) => ({
    x: view.x + (view.width * (index % (steps + 1))) / steps,
    y: view.y + (view.height * Math.floor(index / (steps + 1))) / steps,
  }));
}

describe("gridCells", () => {
  it.each([
    ["the fitted view", FITTED],
    ["a zoomed in view", zoomed(0.4)],
    ["a zoomed out view", zoomed(3)],
    ["a far zoomed out view", zoomed(12)],
    ["a panned view", { ...FITTED, x: FITTED.x - 17.3, y: FITTED.y + 41.9 }],
  ])("covers every point of %s", (_, view) => {
    const cells = new Set(gridCells(view).map(hexKey));

    for (const point of samplePoints(view)) {
      expect(cells).toContain(hexKey(pixelToAxial(point)));
    }
  });

  it("draws only the hexes near the view", () => {
    const view = zoomed(3);
    const hexArea = (3 * Math.sqrt(3)) / 2;
    const margin = (view.width + 6) * (view.height + 6);

    expect(gridCells(view).length).toBeLessThan(margin / hexArea);
  });
});

describe("gridPath", () => {
  it("outlines each hex with one closed subpath", () => {
    const path = gridPath([
      [0, 0],
      [1, -1],
    ]);

    expect(path.match(/M/g)).toHaveLength(2);
    expect(path.match(/Z/g)).toHaveLength(2);
    expect(path.startsWith("M0.866,0.5 ")).toBe(true);
  });
});
