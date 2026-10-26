import { ArrowLeftIcon, DownloadIcon } from "lucide-react";
import { Link, useParams } from "react-router";

import { gameExportUrl } from "@/api/client";
import { useGame } from "@/api/queries";
import { GameStatusBadge } from "@/components/GameStatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { describePlayer } from "@/lib/players";

/** A game with its players and status; the board and moves build on this page. */
export function GamePage() {
  const { gameId = "" } = useParams();
  const game = useGame(gameId);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Button variant="ghost" asChild>
          <Link to="/">
            <ArrowLeftIcon />
            Games
          </Link>
        </Button>
      </div>
      {game.isPending && <p className="text-muted-foreground">Loading the game…</p>}
      {game.isError && (
        <p className="text-destructive">Could not load the game: {game.error.message}</p>
      )}
      {game.isSuccess && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-xl">
              {game.data.name}
              <GameStatusBadge game={game.data} />
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2">
              <dt className="text-muted-foreground">White</dt>
              <dd>{describePlayer(game.data.white)}</dd>
              <dt className="text-muted-foreground">Black</dt>
              <dd>{describePlayer(game.data.black)}</dd>
              <dt className="text-muted-foreground">Ply</dt>
              <dd className="tabular-nums">{game.data.ply_count}</dd>
            </dl>
            <div>
              <Button variant="outline" asChild>
                <a href={gameExportUrl(game.data.id)} download>
                  <DownloadIcon />
                  Export
                </a>
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
