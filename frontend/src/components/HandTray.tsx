import type { ReactNode } from "react";

import type { PieceType, PlayerConfig } from "@/api/client";
import { MovableRing, MovableShadow, SelectedHalo } from "@/components/board/marks";
import { PieceTile } from "@/components/board/PieceTile";
import { Button } from "@/components/ui/button";
import { PIECE_NAMES, PIECE_TYPES } from "@/lib/moves";
import { describePlayer, SIDE_TITLES, type PlayerSide } from "@/lib/players";
import { cn } from "@/lib/utils";

interface HandTrayProps {
  side: PlayerSide;
  player: PlayerConfig;
  /** The number of pieces left to place, by piece type. */
  hand: Partial<Record<PieceType, number>>;
  /** The piece types that may be selected now; empty unless a person places here. */
  placeable: PieceType[];
  selected: PieceType | null;
  toMove: boolean;
  /** An action of the side, such as the Hint button on its turn. */
  action?: ReactNode;
  onSelect: (piece: PieceType) => void;
}

interface TrayPieceProps {
  piece: PieceType;
  side: PlayerSide;
  placeable: boolean;
  selected: boolean;
}

/** A piece in hand with the board's marks: raised when placeable, a halo when selected. */
function TrayPiece({ piece, side, placeable, selected }: TrayPieceProps) {
  return (
    <svg viewBox="-1.1 -1.1 2.25 2.25" aria-hidden="true" className="size-9 shrink-0">
      {selected && <SelectedHalo />}
      {placeable && <MovableShadow />}
      <PieceTile piece={{ piece, owner: side }} />
      {placeable && <MovableRing />}
    </svg>
  );
}

/** The pieces one side has left to place; tapping one highlights where it may go. */
export function HandTray({
  side,
  player,
  hand,
  placeable,
  selected,
  toMove,
  action,
  onSelect,
}: HandTrayProps) {
  const pieces = PIECE_TYPES.filter((piece) => (hand[piece] ?? 0) > 0);

  return (
    <section
      aria-label={`${SIDE_TITLES[side]} hand`}
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl bg-card px-3 py-2 ring-1 ring-border",
        toMove && "ring-2 ring-primary",
      )}
    >
      <div className="flex min-w-24 flex-col text-sm leading-tight">
        <span className="font-medium">{SIDE_TITLES[side]}</span>
        <span className="truncate text-muted-foreground">{describePlayer(player)}</span>
      </div>
      <ul className="flex flex-wrap gap-1">
        {pieces.map((piece) => {
          const count = hand[piece] ?? 0;

          return (
            <li key={piece}>
              <Button
                variant="ghost"
                size="lg"
                aria-pressed={selected === piece}
                aria-label={`Place ${SIDE_TITLES[side].toLowerCase()} ${PIECE_NAMES[piece].toLowerCase()}, ${count} left`}
                disabled={!placeable.includes(piece)}
                className={cn(
                  "h-11 gap-1 px-1 tabular-nums",
                  // Only pieces that cannot be placed on this turn look disabled.
                  placeable.length === 0 && "disabled:opacity-100",
                )}
                onClick={() => {
                  onSelect(piece);
                }}
              >
                <TrayPiece
                  piece={piece}
                  side={side}
                  placeable={placeable.includes(piece)}
                  selected={selected === piece}
                />
                <span className="text-muted-foreground">×{count}</span>
              </Button>
            </li>
          );
        })}
        {pieces.length === 0 && (
          <li className="text-sm text-muted-foreground">No pieces left to place</li>
        )}
      </ul>
      {action !== undefined && <div className="ml-auto">{action}</div>}
    </section>
  );
}
