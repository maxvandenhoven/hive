import antUrl from "@insects/ant.svg";
import beetleUrl from "@insects/beetle.svg";
import grasshopperUrl from "@insects/grasshopper.svg";
import queenUrl from "@insects/queen.svg";
import spiderUrl from "@insects/spider.svg";

import type { PieceType } from "@/api/client";

/** The insect graphics of the Python package, by piece type. */
export const INSECT_IMAGE_URLS: Record<PieceType, string> = {
  queen: queenUrl,
  beetle: beetleUrl,
  grasshopper: grasshopperUrl,
  spider: spiderUrl,
  ant: antUrl,
};
