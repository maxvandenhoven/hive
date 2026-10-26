import { describe, expect, it } from "vitest";

import {
  axialToPixel,
  formatHex,
  hexCorners,
  hexDistance,
  hexKey,
  hexNeighbors,
  hexPoints,
  pixelToAxial,
  sameHex,
} from "@/components/board/hex";
import type { HexCoord } from "@/components/board/types";

const SQRT3 = Math.sqrt(3);

describe("axialToPixel", () => {
  it.each<[HexCoord, number, number]>([
    [[0, 0], 0, 0],
    [[1, 0], SQRT3, 0],
    [[0, 1], SQRT3 / 2, 1.5],
    [[-1, 1], -SQRT3 / 2, 1.5],
    [[2, -1], 1.5 * SQRT3, -1.5],
  ])("places %j at the pointy-top centre", (coord, x, y) => {
    const point = axialToPixel(coord);

    expect(point.x).toBeCloseTo(x);
    expect(point.y).toBeCloseTo(y);
  });

  it("scales with the size", () => {
    expect(axialToPixel([0, 2], 10)).toEqual({ x: 10 * SQRT3, y: 30 });
  });
});

describe("pixelToAxial", () => {
  it("inverts axialToPixel", () => {
    for (let q = -3; q <= 3; q++) {
      for (let r = -3; r <= 3; r++) {
        expect(pixelToAxial(axialToPixel([q, r], 2), 2)).toEqual([q, r]);
      }
    }
  });

  it("finds the hex that contains a point off its centre", () => {
    expect(pixelToAxial({ x: 0.8, y: 0.1 })).toEqual([0, 0]);
    expect(pixelToAxial({ x: 0.95, y: 0 })).toEqual([1, 0]);
    expect(pixelToAxial({ x: 0, y: -0.95 })).toEqual([0, 0]);
    expect(pixelToAxial({ x: 0.1, y: -1.2 })).toEqual([1, -1]);
  });

  it("never returns negative zero", () => {
    const [q, r] = pixelToAxial({ x: -0.1, y: -0.1 });

    expect(Object.is(q, 0)).toBe(true);
    expect(Object.is(r, 0)).toBe(true);
  });
});

describe("hexCorners", () => {
  it("puts six corners at the size from the centre, starting at 30 degrees", () => {
    const corners = hexCorners({ x: 1, y: 2 }, 2);

    expect(corners).toHaveLength(6);

    for (const corner of corners) {
      expect(Math.hypot(corner.x - 1, corner.y - 2)).toBeCloseTo(2);
    }

    expect(corners[0]?.x).toBeCloseTo(1 + SQRT3);
    expect(corners[0]?.y).toBeCloseTo(3);
    // Pointy top: one corner straight above the centre.
    expect(corners.some(({ x, y }) => Math.abs(x - 1) < 1e-9 && y < 2)).toBe(true);
  });

  it("formats the corners as SVG points", () => {
    expect(hexPoints({ x: 0, y: 0 }, 1).split(" ")).toHaveLength(6);
    expect(hexPoints({ x: 0, y: 0 }, 1)).toMatch(/^0\.866,0\.5 /);
  });
});

describe("hexDistance", () => {
  it.each<[HexCoord, HexCoord, number]>([
    [[0, 0], [0, 0], 0],
    [[0, 0], [1, 0], 1],
    [[0, 0], [1, -1], 1],
    [[0, 0], [2, -1], 2],
    [[-2, 1], [1, 1], 3],
    [[0, 0], [2, 2], 4],
  ])("counts the steps from %j to %j", (a, b, distance) => {
    expect(hexDistance(a, b)).toBe(distance);
    expect(hexDistance(b, a)).toBe(distance);
  });
});

describe("hexNeighbors", () => {
  it("lists the six neighbours in the order of the engine", () => {
    expect(hexNeighbors([1, 2])).toEqual([
      [2, 2],
      [2, 1],
      [1, 1],
      [0, 2],
      [0, 3],
      [1, 3],
    ]);
  });
});

describe("hex identity", () => {
  it("compares and names coordinates", () => {
    expect(sameHex([1, -2], [1, -2])).toBe(true);
    expect(sameHex([1, -2], [-2, 1])).toBe(false);
    expect(hexKey([1, -2])).toBe("1,-2");
    expect(formatHex([1, -2])).toBe("(1, -2)");
  });
});
