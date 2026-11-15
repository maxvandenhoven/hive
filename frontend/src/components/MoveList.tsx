import { useEffect, useRef } from "react";

import { photoImageUrl, type GameDetail, type MoveSource } from "@/api/client";
import { PieceIcon } from "@/components/board/PieceTile";
import { Button } from "@/components/ui/button";
import { describeMove, playerAtPly } from "@/lib/moves";
import { SIDE_TITLES } from "@/lib/players";
import { cn } from "@/lib/utils";

const SOURCE_LABELS: Record<MoveSource, string | null> = {
  manual: null,
  photo: "photo",
  agent: "agent",
};

interface MoveListProps {
  game: Pick<GameDetail, "moves" | "rules" | "setup">;
  /** The ply of the position shown in a replay, or `null` for the latest. */
  shownPly: number | null;
  /** Show the position after a move, which is the ply after its own. */
  onShowPly: (ply: number) => void;
}

/**
 * The moves of a game, oldest first and scrolled to the latest; a move replays it, and
 * the thumbnail of a move read from a photo opens the photo.
 */
export function MoveList({ game, shownPly, onShowPly }: MoveListProps) {
  const listRef = useRef<HTMLOListElement>(null);
  const moveCount = game.moves.length;

  useEffect(() => {
    const list = listRef.current;

    if (list !== null && moveCount > 0) {
      list.scrollTop = list.scrollHeight;
    }
  }, [moveCount]);

  if (moveCount === 0) {
    return <p className="text-sm text-muted-foreground">No moves yet.</p>;
  }

  return (
    <ol
      ref={listRef}
      aria-label="Moves"
      className="flex max-h-64 flex-col overflow-y-auto text-sm lg:max-h-96"
    >
      {game.moves.map((move) => {
        const player = playerAtPly(game, move.ply);
        const source = SOURCE_LABELS[move.source];
        const shown = shownPly === move.ply + 1;

        return (
          <li key={move.ply} className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              aria-current={shown ? "step" : undefined}
              className={cn(
                "h-auto w-full justify-start gap-2 px-1 py-1 text-left font-normal whitespace-normal",
                shown && "bg-muted",
              )}
              onClick={() => {
                onShowPly(move.ply + 1);
              }}
            >
              <span className="w-6 shrink-0 text-right text-muted-foreground tabular-nums">
                {move.ply + 1}.
              </span>
              {move.move === null ? (
                <span className="size-5 shrink-0" />
              ) : (
                <PieceIcon
                  piece={{ piece: move.move.piece, owner: player }}
                  className="size-5"
                />
              )}
              <span className="sr-only">{SIDE_TITLES[player]}:</span>
              <span className="flex-1">{describeMove(move.move)}</span>
              {source !== null && (
                <span className="text-xs text-muted-foreground">{source}</span>
              )}
            </Button>
            {move.photo_id !== null && (
              <a
                href={photoImageUrl(move.photo_id)}
                target="_blank"
                rel="noreferrer"
                aria-label={`Photo of move ${move.ply + 1}`}
                className="shrink-0 rounded-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <img
                  src={photoImageUrl(move.photo_id)}
                  alt=""
                  loading="lazy"
                  className="size-7 rounded-sm object-cover"
                />
              </a>
            )}
          </li>
        );
      })}
    </ol>
  );
}
