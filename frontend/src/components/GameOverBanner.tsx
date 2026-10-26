import { FlagIcon, TrophyIcon } from "lucide-react";

import type { GameDetail, GamePosition } from "@/api/client";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { SIDE_TITLES } from "@/lib/players";

/** The result of a finished game, or a note that an abandoned game is read-only. */
export function GameOverBanner({
  game,
  position,
}: {
  game: Pick<GameDetail, "status">;
  position: GamePosition;
}) {
  if (position.result !== null) {
    const title =
      position.result === "draw" ? "Draw" : `${SIDE_TITLES[position.result]} won`;

    return (
      <Alert>
        <TrophyIcon />
        <AlertTitle>{title}</AlertTitle>
        <AlertDescription>
          The game ended after {position.ply} moves. Undo the last move to play on.
        </AlertDescription>
      </Alert>
    );
  }

  if (game.status === "abandoned") {
    return (
      <Alert>
        <FlagIcon />
        <AlertTitle>Abandoned</AlertTitle>
        <AlertDescription>No more moves can be played in this game.</AlertDescription>
      </Alert>
    );
  }

  return null;
}
