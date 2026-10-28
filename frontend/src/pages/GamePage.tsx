import { ArrowLeftIcon, DownloadIcon, SkipForwardIcon, Undo2Icon } from "lucide-react";
import { useMemo, useState } from "react";
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
import { MatchControls } from "@/components/MatchControls";
import { MoveList } from "@/components/MoveList";
import { ReplayControls } from "@/components/ReplayControls";
import { ThinkingPanel } from "@/components/ThinkingPanel";
import { useAgentTurns, type AgentTurns } from "@/components/useAgentTurns";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { playerAtPly, toBoardView, toMoveView } from "@/lib/moves";
import type { PlayerSide } from "@/lib/players";

/** The board renderer; a 3D renderer can take its place behind the same props. */
const Board: BoardRenderer = SvgBoard;

/** The side drawn below the board: the side a person plays, white if both or none. */
function homeSide(game: GameDetail): PlayerSide {
  return game.black.type === "human" && game.white.type !== "human" ? "black" : "white";
}

/**
 * How many moves undo takes back: in a human game back to the person's last turn, so
 * the agent does not answer the undone move again at once; otherwise one.
 */
function undoPlies(game: GameDetail, turns: AgentTurns, plyCount: number): number {
  const lastMover = plyCount > 0 ? game[playerAtPly(game, plyCount - 1)] : null;

  return turns.mode === "human" && plyCount >= 2 && lastMover?.type === "agent" ? 2 : 1;
}

/** The move to point out on the board: the agent's best move, or the move to make. */
function proposedMove(turns: AgentTurns): Move | null | undefined {
  if (turns.state.type === "thinking") {
    return turns.state.candidate;
  }

  return turns.awaitingDone && turns.state.type === "committed" ? turns.state.move : null;
}

interface GameScreenProps {
  game: GameDetail;
  /** The latest position. */
  position: GamePosition;
}

/** The board, hands, moves, agent turns, replay and actions of a loaded game. */
function GameScreen({ game, position }: GameScreenProps) {
  const playMove = usePlayMove(game.id);
  const undoMove = useUndoMove(game.id);
  const busy = playMove.isPending || undoMove.isPending;
  const turns = useAgentTurns({ game, position, idle: !busy });
  const [replayPly, setReplayPly] = useState<number | null>(null);
  // A replay past the last move, for example after an undo, shows the latest position.
  const shownPly =
    replayPly !== null && replayPly < position.ply_count ? replayPly : null;
  const replay = useGamePosition(game.id, shownPly);
  const live = shownPly === null;
  const shown = live ? position : (replay.data ?? position);
  const sideToMove = position.current_player;
  const active = game.status === "active" && position.result === null;
  const humanTurn = active && game[sideToMove].type === "human" && !turns.awaitingDone;
  const canPlay = humanTurn && !busy && live;

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
    enabled: canPlay,
    onMove: play,
  });
  const board = useMemo(() => toBoardView(shown.board), [shown.board]);
  const lastMove = useMemo(() => toMoveView(shown.last_move?.move), [shown.last_move]);
  const proposed = live ? toMoveView(proposedMove(turns)) : null;
  const home = homeSide(game);
  const away = home === "white" ? "black" : "white";
  const selectedPiece =
    interaction.selection?.type === "hand" ? interaction.selection.piece : null;

  const renderTray = (side: PlayerSide) => (
    <HandTray
      side={side}
      player={game[side]}
      hand={shown.hands[side] ?? {}}
      placeable={side === sideToMove && canPlay ? position.placeable_piece_types : []}
      selected={side === sideToMove ? selectedPiece : null}
      toMove={live && active && side === sideToMove}
      onSelect={interaction.clickHandPiece}
    />
  );

  const undo = () => {
    if (turns.mode === "match") {
      turns.setAutoplay(false);
    }

    const plies = undoPlies(game, turns, position.ply_count);
    undoMove.mutate(
      { expectedPly: position.ply_count, plies },
      {
        onSuccess: () => {
          toast.success(plies === 1 ? "Undid the last move." : "Undid the last 2 moves.");
        },
      },
    );
  };

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem] lg:grid-rows-[auto_1fr]">
      <div className="flex flex-col gap-3 lg:col-start-2 lg:row-start-1">
        <GameHeader game={game} position={position} />
        <GameOverBanner game={game} position={position} />
        <ThinkingPanel game={game} position={position} turns={turns} />
      </div>
      <div className="flex flex-col gap-2 lg:col-start-1 lg:row-span-2 lg:row-start-1">
        {renderTray(away)}
        <Card className="relative aspect-square max-h-[65dvh] w-full bg-muted/30 py-0 lg:aspect-auto lg:h-[max(24rem,calc(100dvh-19rem))] lg:max-h-none">
          <Board
            board={board}
            highlights={interaction.highlights}
            movable={interaction.movable}
            selected={
              interaction.selection?.type === "board" ? interaction.selection.coord : null
            }
            lastMove={lastMove}
            proposedMove={proposed}
            onHexClick={interaction.clickHex}
          />
          {!live && (
            <Badge variant="secondary" className="absolute top-2 left-2">
              Replay · ply {shown.ply}
            </Badge>
          )}
        </Card>
        {renderTray(home)}
      </div>
      <div className="flex flex-col gap-4 lg:col-start-2 lg:row-start-2">
        {turns.mode === "match" && game.status === "active" && (
          <MatchControls turns={turns} />
        )}
        <div className="flex flex-wrap gap-2">
          {canPlay && position.must_pass && (
            <Button
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
          <CardContent className="flex flex-col gap-3">
            <ReplayControls
              ply={shownPly}
              plyCount={position.ply_count}
              onChange={setReplayPly}
            />
            <MoveList game={game} shownPly={shownPly} onShowPly={setReplayPly} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/**
 * A game: the board with manual move entry and agent turns, the hands, the moves,
 * replay and undo.
 */
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
        <GameScreen key={game.data.id} game={game.data} position={position.data} />
      )}
    </div>
  );
}
