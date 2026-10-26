import { useEffect, useRef } from "react";

import type { GameDetail, MoveSource } from "@/api/client";
import { PieceIcon } from "@/components/board/PieceTile";
import { describeMove, playerAtPly } from "@/lib/moves";
import { SIDE_TITLES } from "@/lib/players";

const SOURCE_LABELS: Record<MoveSource, string | null> = {
  manual: null,
  photo: "photo",
  agent: "agent",
};

/** The moves of a game, oldest first, scrolled to the latest. */
export function MoveList({
  game,
}: {
  game: Pick<GameDetail, "moves" | "rules" | "setup">;
}) {
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
      className="flex max-h-64 flex-col gap-0.5 overflow-y-auto text-sm lg:max-h-96"
    >
      {game.moves.map((move) => {
        const player = playerAtPly(game, move.ply);
        const source = SOURCE_LABELS[move.source];

        return (
          <li key={move.ply} className="flex items-center gap-2 rounded-md px-1 py-0.5">
            <span className="w-6 text-right text-muted-foreground tabular-nums">
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
          </li>
        );
      })}
    </ol>
  );
}
