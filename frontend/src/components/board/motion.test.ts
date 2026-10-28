import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { moveArc, pointOnArc } from "@/components/board/arrows";
import {
  FADE_DURATION_MS,
  MOVE_DURATION_MS,
  PLACE_DURATION_MS,
  RESTING_FRAME,
  transitionDuration,
  transitionFrame,
  usePrefersReducedMotion,
} from "@/components/board/motion";

const ARC = moveArc({ from: [-2, 0], to: [1, 0], centre: { x: 0, y: 3 } });

describe("transitionDuration", () => {
  it("drops placements faster than moves travel, and fades with reduced motion", () => {
    expect(transitionDuration("place", false)).toBe(PLACE_DURATION_MS);
    expect(transitionDuration("move", false)).toBe(MOVE_DURATION_MS);
    expect(transitionDuration("climb", false)).toBe(MOVE_DURATION_MS);
    expect(transitionDuration("move", true)).toBe(FADE_DURATION_MS);
  });
});

describe("transitionFrame", () => {
  it("drops a placement from above, larger and with a shadow, onto its hex", () => {
    const first = transitionFrame({
      kind: "place",
      arc: null,
      progress: 0,
      reducedMotion: false,
    });
    const middle = transitionFrame({
      kind: "place",
      arc: null,
      progress: 0.5,
      reducedMotion: false,
    });

    expect(first.y).toBeLessThan(0);
    expect(first.scale).toBeGreaterThan(1);
    expect(first.shadowOpacity).toBeGreaterThan(0);
    // Ease-out: most of the drop is done halfway, with no overshoot.
    expect(middle.y).toBeLessThan(0);
    expect(Math.abs(middle.y)).toBeLessThan(Math.abs(first.y) / 4);
    expect(middle.scale).toBeGreaterThan(1);
  });

  it("travels a move along its arc, lifted in the middle, and settles", () => {
    const first = transitionFrame({
      kind: "move",
      arc: ARC,
      progress: 0,
      reducedMotion: false,
    });
    const middle = transitionFrame({
      kind: "move",
      arc: ARC,
      progress: 0.5,
      reducedMotion: false,
    });
    const last = transitionFrame({
      kind: "climb",
      arc: ARC,
      progress: 1,
      reducedMotion: false,
    });
    const apex = pointOnArc(ARC, 0.5);

    expect({ x: first.x, y: first.y }).toEqual({
      x: ARC.from.x - ARC.to.x,
      y: ARC.from.y - ARC.to.y,
    });
    expect(middle.x).toBeCloseTo(apex.x - ARC.to.x, 5);
    expect(middle.y).toBeCloseTo(apex.y - ARC.to.y, 5);
    expect(middle.scale).toBeGreaterThan(1);
    expect(middle.shadowOpacity).toBeGreaterThan(0);
    expect(last.x).toBeCloseTo(0, 5);
    expect(last.y).toBeCloseTo(0, 5);
    expect(last.scale).toBeCloseTo(1, 5);
  });

  it("cross-fades instead of dropping or travelling with reduced motion", () => {
    for (const progress of [0, 0.3, 0.7, 1]) {
      const move = transitionFrame({
        kind: "move",
        arc: ARC,
        progress,
        reducedMotion: true,
      });
      const place = transitionFrame({
        kind: "place",
        arc: null,
        progress,
        reducedMotion: true,
      });

      expect(move).toEqual({
        ...RESTING_FRAME,
        opacity: progress,
        ghostOpacity: 1 - progress,
      });
      expect(place).toEqual({ ...RESTING_FRAME, opacity: progress });
    }
  });
});

describe("usePrefersReducedMotion", () => {
  function stubMotionQuery(reduce: boolean) {
    vi.stubGlobal("matchMedia", (query: string) => {
      const list = new EventTarget() as MediaQueryList;

      return Object.assign(list, {
        matches: reduce && query === "(prefers-reduced-motion: reduce)",
        media: query,
        onchange: null,
      });
    });
  }

  it("follows the system setting", () => {
    stubMotionQuery(true);
    expect(renderHook(() => usePrefersReducedMotion()).result.current).toBe(true);

    stubMotionQuery(false);
    expect(renderHook(() => usePrefersReducedMotion()).result.current).toBe(false);
  });
});
