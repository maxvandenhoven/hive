import css from "@/index.css?raw";

import { BOARD_COLORS, TILE_COLORS } from "@/components/board/colors";

function cssToken(name: string): string | undefined {
  return new RegExp(`--${name}:\\s*([^;]+);`).exec(css)?.[1]?.trim();
}

describe("board colours", () => {
  it.each([
    ["board-surface", BOARD_COLORS.surface],
    ["board-grid", BOARD_COLORS.grid],
    ["tile-stroke", BOARD_COLORS.tileStroke],
    ["board-movable", BOARD_COLORS.movable],
    ["board-target", BOARD_COLORS.target],
    ["board-forbidden", BOARD_COLORS.forbidden],
    ["board-last-move", BOARD_COLORS.lastMove],
    ["board-suggestion", BOARD_COLORS.suggestion],
    ["tile-white", TILE_COLORS.white],
    ["tile-black", TILE_COLORS.black],
  ])("match the --%s token of the theme", (name, value) => {
    expect(cssToken(name)).toBe(value);
  });
});
