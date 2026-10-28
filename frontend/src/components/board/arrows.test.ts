import { describe, expect, it } from "vitest";

import {
  ARROW_END_OFFSET,
  ARROW_START_OFFSET,
  hiveCentre,
  moveArc,
  moveArrow,
  pointOnArc,
} from "@/components/board/arrows";
import { axialToPixel, type PixelPoint } from "@/components/board/hex";

function distance(a: PixelPoint, b: PixelPoint): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** The start of an arrow's path, from its `M x y` command. */
function pathStart(path: string): PixelPoint {
  const [, x = "", y = ""] = path.split(" ");

  return { x: Number(x), y: Number(y) };
}

describe("hiveCentre", () => {
  it("is the mean of the stacks, or null without any", () => {
    expect(hiveCentre([])).toBeNull();
    expect(
      hiveCentre([
        [0, 0],
        [2, 0],
      ]),
    ).toEqual(axialToPixel([1, 0]));
  });
});

describe("moveArc", () => {
  // A move to the right along the top of a hive that lies below it.
  const from = [-1, 0] as const;
  const to = [1, 0] as const;

  it("bends away from the hive", () => {
    const below = moveArc({ from: [...from], to: [...to], centre: { x: 0, y: 3 } });
    const above = moveArc({ from: [...from], to: [...to], centre: { x: 0, y: -3 } });

    expect(below.side).toBe("left");
    expect(pointOnArc(below, 0.5).y).toBeLessThan(0);
    expect(above.side).toBe("right");
    expect(pointOnArc(above, 0.5).y).toBeGreaterThan(0);
  });

  it("bends left when the hive is on the line or unknown", () => {
    expect(moveArc({ from: [...from], to: [...to], centre: { x: 5, y: 0 } }).side).toBe(
      "left",
    );
    expect(moveArc({ from: [...from], to: [...to], centre: null }).side).toBe("left");
  });

  it("runs from centre to centre and bends more for longer moves, within limits", () => {
    const short = moveArc({ from: [0, 0], to: [1, 0], centre: null });
    const long = moveArc({ from: [-4, 0], to: [4, 0], centre: null });
    const longest = moveArc({ from: [-20, 0], to: [20, 0], centre: null });
    const bend = (arc: typeof short) => Math.abs(pointOnArc(arc, 0.5).y);

    expect(pointOnArc(short, 0)).toEqual(axialToPixel([0, 0]));
    expect(pointOnArc(short, 1)).toEqual(axialToPixel([1, 0]));
    expect(bend(short)).toBeCloseTo(0.35, 2);
    expect(bend(long)).toBeGreaterThan(bend(short));
    expect(bend(longest)).toBeCloseTo(1.2, 5);
  });
});

describe("moveArrow", () => {
  const arc = moveArc({ from: [0, 0], to: [2, -1], centre: { x: 0, y: 3 } });
  const arrow = moveArrow(arc);

  it("ends at the edge of the target, so its head stays visible", () => {
    const [tip] = arrow.head;

    expect(distance(tip, arc.to)).toBeCloseTo(ARROW_END_OFFSET, 5);
  });

  it("starts a little off the centre of the source", () => {
    expect(distance(pathStart(arrow.path), arc.from)).toBeCloseTo(ARROW_START_OFFSET, 2);
  });

  it("points its head along the curve into the target", () => {
    const [tip, left, right] = arrow.head;
    const base = { x: (left.x + right.x) / 2, y: (left.y + right.y) / 2 };

    // The head is symmetric and its base is farther from the target than its tip.
    expect(distance(tip, left)).toBeCloseTo(distance(tip, right), 5);
    expect(distance(base, arc.to)).toBeGreaterThan(distance(tip, arc.to));
    expect(arrow.path).toContain(`Q`);
  });
});
