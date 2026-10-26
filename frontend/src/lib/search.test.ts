import { describe, expect, it } from "vitest";

import {
  formatCount,
  formatScore,
  SEARCH_WIN_SCORE,
  summarizeSearch,
} from "@/lib/search";

describe("summarizeSearch", () => {
  it("reads the numbers an agent reported", () => {
    expect(
      summarizeSearch({ depth: 3, score: -1.25, nodes: 4200, nps: 21000, pv: [] }),
    ).toEqual({ depth: 3, score: -1.25, nodes: 4200, nps: 21000 });
  });

  it("leaves out fields that are missing or not numbers", () => {
    expect(summarizeSearch({ depth: "3", nps: null })).toEqual({
      depth: null,
      score: null,
      nodes: null,
      nps: null,
    });
    expect(summarizeSearch(null).depth).toBeNull();
  });
});

describe("formatScore", () => {
  it("signs evaluations", () => {
    expect(formatScore(1.5)).toBe("+1.5");
    expect(formatScore(-0.25)).toBe("-0.3");
    expect(formatScore(0)).toBe("0.0");
  });

  it("names forced results", () => {
    expect(formatScore(SEARCH_WIN_SCORE - 3)).toBe("Win in 3 plies");
    expect(formatScore(-(SEARCH_WIN_SCORE - 1))).toBe("Loss in 1 ply");
  });
});

describe("formatCount", () => {
  it("shortens large counts", () => {
    expect(formatCount(950)).toBe("950");
    expect(formatCount(12_345)).toBe("12.3K");
    expect(formatCount(1_200_000)).toBe("1.2M");
  });
});
