import type { Piece } from "@/api/client";
import { roundedHexPath } from "@/components/board/hex";
import { TILE_FILL_CLASSES } from "@/components/board/colors";
import { INSECT_IMAGE_URLS } from "@/components/board/insects";
import { cn } from "@/lib/utils";

/** The radius of a tile, a little smaller than its hex so neighbours stay apart. */
export const TILE_RADIUS = 0.9;

const TILE_PATH = roundedHexPath(TILE_RADIUS);
const INSECT_SIZE = 1.3;

/** A piece as a coloured tile with its insect, centred on the origin in board units. */
export function PieceTile({ piece }: { piece: Piece }) {
  return (
    <g>
      <path
        d={TILE_PATH}
        strokeWidth={0.04}
        className={cn(TILE_FILL_CLASSES[piece.owner], "stroke-tile-stroke")}
      />
      <image
        href={INSECT_IMAGE_URLS[piece.piece]}
        x={-INSECT_SIZE / 2}
        y={-INSECT_SIZE / 2}
        width={INSECT_SIZE}
        height={INSECT_SIZE}
      />
    </g>
  );
}

/** A piece as a small tile next to text, for trays, lists and popovers. */
export function PieceIcon({ piece, className }: { piece: Piece; className?: string }) {
  return (
    <svg
      viewBox="-1 -1 2 2"
      aria-hidden="true"
      className={cn("size-6 shrink-0", className)}
    >
      <PieceTile piece={piece} />
    </svg>
  );
}
