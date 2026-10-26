import { ArrowLeftIcon, DownloadIcon, SkipForwardIcon, Undo2Icon } from "lucide-react";
import { useMemo } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import {
  gameExportUrl,
  type GameDetail,
  type GamePosition,
  type Move,
} from "@/api/client";
import { useGame, useGamePosition, usePlayMove, useUndoMove } from "@/api/queries";
import { SvgBoard } from "@/components/board/SvgBoard";
import type { BoardRenderer } from "@/components/board/types";
import { useBoardInteraction } from "@/components/board/useBoardInteraction";
import { GameHeader } from "@/components/GameHeader";
import { GameOverBanner } from "@/components/GameOverBanner";
import { HandTray } from "@/components/HandTray";
import { MoveList } from "@/components/MoveList";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toBoardView, toMoveView } from "@/lib/moves";
import type { PlayerSide } from "@/lib/players";

/** The board renderer; a 3D renderer can take its place behind the same props. */
const Board: BoardRenderer = SvgBoard;

/** The side drawn below the board: the side a person plays, white if both or none. */
function homeSide(game: GameDetail): PlayerSide {
  return game.black.type === "human" && game.white.type !== "human" ? "black" : "white";
}

interface GameScreenProps {
  game: GameDetail;
  /** The latest position. */
  position: GamePosition;
}

/** The board, hands, moves and actions of a loaded game. */
function GameScreen({ game, position }: GameScreenProps) {
  const playMove = usePlayMove(game.id);
  const undoMove = useUndoMove(game.id);
  const sideToMove = position.current_player;
  const active = game.status === "active" && position.result === null;
  const humanTurn = active && game[sideToMove].type === "human";
  const busy = playMove.isPending || undoMove.isPending;

  const play = (move: Move | null) => {
    playMove.mutate({
      move,
      source: "manual",
      expected_ply: position.ply_count,
      allow_agent_side: false,
    });
  };

  const interaction = useBoardInteraction({
    gameId: game.id,
    position,
    enabled: humanTurn && !busy,
    onMove: play,
  });
  const board = useMemo(() => toBoardView(position.board), [position.board]);
  const lastMove = useMemo(() => toMoveView(position.last_move), [position.last_move]);
  const home = homeSide(game);
  const away = home === "white" ? "black" : "white";
  const selectedPiece =
    interaction.selection?.type === "hand" ? interaction.selection.piece : null;

  const renderTray = (side: PlayerSide) => (
    <HandTray
      side={side}
      player={game[side]}
      hand={position.hands[side] ?? {}}
      placeable={
        side === sideToMove && humanTurn && !busy ? position.placeable_piece_types : []
      }
      selected={side === sideToMove ? selectedPiece : null}
      toMove={active && side === sideToMove}
      onSelect={interaction.clickHandPiece}
    />
  );

  const undo = () => {
    undoMove.mutate(position.ply_count, {
      onSuccess: () => {
        toast.success("Undid the last move.");
      },
    });
  };

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem] lg:grid-rows-[auto_1fr]">
      <div className="flex flex-col gap-3 lg:col-start-2 lg:row-start-1">
        <GameHeader game={game} position={position} />
        <GameOverBanner game={game} position={position} />
      </div>
      <div className="flex flex-col gap-2 lg:col-start-1 lg:row-span-2 lg:row-start-1">
        {renderTray(away)}
        <Card className="aspect-square max-h-[65dvh] w-full bg-muted/30 py-0 lg:aspect-auto lg:h-[max(24rem,calc(100dvh-19rem))] lg:max-h-none">
          <Board
            board={board}
            highlights={interaction.highlights}
            movable={interaction.movable}
            selected={
              interaction.selection?.type === "board" ? interaction.selection.coord : null
            }
            lastMove={lastMove}
            onHexClick={interaction.clickHex}
          />
        </Card>
        {renderTray(home)}
      </div>
      <div className="flex flex-col gap-4 lg:col-start-2 lg:row-start-2">
        <div className="flex flex-wrap gap-2">
          {humanTurn && position.must_pass && (
            <Button
              disabled={busy}
              onClick={() => {
                play(null);
              }}
            >
              <SkipForwardIcon />
              Pass
            </Button>
          )}
          <Button
            variant="outline"
            disabled={position.ply_count === 0 || busy || game.status === "abandoned"}
            onClick={undo}
          >
            <Undo2Icon />
            Undo
          </Button>
          <Button variant="outline" asChild>
            <a href={gameExportUrl(game.id)} download>
              <DownloadIcon />
              Export
            </a>
          </Button>
        </div>
        <Card size="sm">
          <CardHeader>
            <CardTitle>Moves</CardTitle>
          </CardHeader>
          <CardContent>
            <MoveList game={game} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/** A game: the board with manual move entry, the hands, the moves and undo. */
export function GamePage() {
  const { gameId = "" } = useParams();
  const game = useGame(gameId);
  const position = useGamePosition(gameId);
  const error = game.error ?? position.error;

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
      {error !== null && (
        <p className="text-destructive">Could not load the game: {error.message}</p>
      )}
      {error === null && (!game.isSuccess || !position.isSuccess) && (
        <p className="text-muted-foreground">Loading the game…</p>
      )}
      {game.isSuccess && position.isSuccess && (
        <GameScreen game={game.data} position={position.data} />
      )}
    </div>
  );
}
