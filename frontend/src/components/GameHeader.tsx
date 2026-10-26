import type { GameDetail, GamePosition } from "@/api/client";
import { GameStatusBadge } from "@/components/GameStatusBadge";
import { describePlayer, SIDE_TITLES } from "@/lib/players";

/** What happens now in a game: whose turn it is, or how it ended. */
function describeTurn(game: GameDetail, position: GamePosition): string {
  if (position.result !== null) {
    return position.result === "draw" ? "Draw" : `${SIDE_TITLES[position.result]} won`;
  }

  if (game.status === "abandoned") {
    return "Abandoned";
  }

  const side = position.current_player;
  const player = game[side];
  const agent = player.type === "agent" ? ` · ${describePlayer(player)}` : "";

  return `${SIDE_TITLES[side]} to move${agent}`;
}

/** The name, status and players of a game, with whose turn it is. */
export function GameHeader({
  game,
  position,
}: {
  game: GameDetail;
  position: GamePosition;
}) {
  return (
    <header className="flex flex-col gap-1">
      <h1 className="flex flex-wrap items-center gap-2 font-heading text-xl font-semibold">
        <span className="min-w-0 truncate">{game.name}</span>
        <GameStatusBadge game={game} />
      </h1>
      <p className="text-sm text-muted-foreground">
        {describePlayer(game.white)} vs {describePlayer(game.black)}
      </p>
      <p role="status" className="text-sm font-medium">
        {describeTurn(game, position)}
        <span className="text-muted-foreground"> · ply {position.ply_count}</span>
      </p>
    </header>
  );
}
