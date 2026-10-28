import antUrl from "@insects/ant.svg";
import beetleUrl from "@insects/beetle.svg";
import grasshopperUrl from "@insects/grasshopper.svg";
import queenUrl from "@insects/queen.svg";
import spiderUrl from "@insects/spider.svg";

import type { PieceType } from "@/api/client";
import type { PlayerSide } from "@/lib/players";

/** The insect graphics of the Python package, by piece type. */
export const INSECT_IMAGE_URLS: Record<PieceType, string> = {
  queen: queenUrl,
  beetle: beetleUrl,
  grasshopper: grasshopperUrl,
  spider: spiderUrl,
  ant: antUrl,
};

/** The tile colours of each side, as in the board plots of the Python package. */
export const TILE_COLORS: Record<PlayerSide, string> = {
  white: "#F5F0E1",
  black: "#2C2C2C",
};

/** The outline of every tile. */
export const TILE_STROKE = "#555555";
