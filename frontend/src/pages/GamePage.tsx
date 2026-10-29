import { ArrowLeftIcon, DownloadIcon, Undo2Icon } from "lucide-react";
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
import { HandTray } from "@/components/HandTray";
import { HintButton } from "@/components/HintButton";
import { MoveList } from "@/components/MoveList";
import { ReplayControls } from "@/components/ReplayControls";
import { ThinkingPanel } from "@/components/ThinkingPanel";
import { TurnPrompt } from "@/components/TurnPrompt";
import { useAgentTurns, type AgentTurns } from "@/components/useAgentTurns";
import { useHint, type Hint } from "@/components/useHint";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { playerAtPly, toBoardView, toMoveView } from "@/lib/moves";
import { ownSide, type PlayerSide } from "@/lib/players";
import { describeTurnPrompt } from "@/lib/turnPrompt";

/** The board renderer; a 3D renderer can take its place behind the same props. */
const Board: BoardRenderer = SvgBoard;

/**
 * The side drawn below the board: the side of the person using the app, else white.
 */
function homeSide(game: GameDetail): PlayerSide {
  return ownSide(game) ?? "white";
}

/**
 * How many moves undo takes back: in a human game back to the person's last turn, so
 * the agent does not answer the undone move again at once; otherwise one.
 *
 * A pending agent move counts as the agent's answer: undoing it takes back the person's
 * move too, and the person takes both back on the table.
 */
function undoPlies(game: GameDetail, turns: AgentTurns, plyCount: number): number {
  const lastMover = plyCount > 0 ? game[playerAtPly(game, plyCount - 1)] : null;

  return turns.mode === "human" && plyCount >= 2 && lastMover?.type === "agent" ? 2 : 1;
}

/**
 * The move to point out on the board: the agent's best move while it thinks, the
 * pending move to make on the table, or a hint that was asked for.
 */
function proposedMove(
  turns: AgentTurns,
  hint: Hint,
  position: GamePosition,
): Move | null | undefined {
  if (turns.state.type === "thinking") {
    return turns.state.candidate;
  }

  if (turns.awaitingDone) {
    return position.last_move?.move;
  }

  return hint.state.type === "shown" ? hint.state.move : null;
}

interface GameScreenProps {
  game: GameDetail;
  /** The latest position. */
  position: GamePosition;
}

/**
 * The turn prompt, board, hands, moves, agent turns, hints, replay and actions of a
 * loaded game.
 */
function GameScreen({ game, position }: GameScreenProps) {
  const playMove = usePlayMove(game.id);
  const undoMove = useUndoMove(game.id);
  const writing = playMove.isPending || undoMove.isPending;
  const turns = useAgentTurns({ game, position, idle: !writing });
  const hint = useHint({ game, position });
  const busy = writing || turns.confirming;
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

  const hintMove = hint.state.type === "shown" ? hint.state.move : null;
  const interaction = useBoardInteraction({
    gameId: game.id,
    position,
    enabled: canPlay,
    hint: hintMove,
    onMove: play,
  });
  const board = useMemo(() => toBoardView(shown.board), [shown.board]);
  const liveBoard = useMemo(() => toBoardView(position.board), [position.board]);
  const lastMove = useMemo(() => toMoveView(shown.last_move?.move), [shown.last_move]);
  const proposedFull = live ? proposedMove(turns, hint, position) : null;
  const proposed = toMoveView(proposedFull);
  // A pending move is already in the game, so its piece is no longer in hand.
  const suggestedPiece =
    proposedFull != null && proposedFull.from === null && !turns.awaitingDone
      ? proposedFull.piece
      : null;
  const prompt = describeTurnPrompt({
    game,
    position,
    turnState: turns.state.type,
    shownPly,
  });
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
      suggested={side === sideToMove ? suggestedPiece : null}
      suggestionShown={proposed !== null}
      toMove={live && active && side === sideToMove}
      action={
        side === sideToMove && prompt.kind === "turn" && hint.agent !== null ? (
          <HintButton hint={hint} size="sm" />
        ) : undefined
      }
      onSelect={interaction.clickHandPiece}
    />
  );

  const pass = () => {
    play(null);
  };

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
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem] lg:grid-rows-[auto_1fr] xl:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="flex flex-col gap-3 lg:col-start-2 lg:row-start-1">
        <GameHeader game={game} position={position} />
        <ThinkingPanel game={game} position={position} turns={turns} />
      </div>
      <div className="flex flex-col gap-2 lg:col-start-1 lg:row-span-2 lg:row-start-1">
        <TurnPrompt
          prompt={prompt}
          position={position}
          board={liveBoard}
          turns={turns}
          hint={hint}
          busy={busy}
          onPass={pass}
          onUndo={undo}
          onLive={() => {
            setReplayPly(null);
          }}
        />
        {renderTray(away)}
        <Card className="relative aspect-square max-h-[65dvh] w-full bg-board-surface py-0 lg:aspect-auto lg:h-[max(24rem,calc(100dvh-19rem))] lg:max-h-none">
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
        <div className="flex flex-wrap gap-2">
          {prompt.kind !== "over" && (
            <Button
              variant="outline"
              disabled={position.ply_count === 0 || busy || game.status === "abandoned"}
              onClick={undo}
            >
              <Undo2Icon />
              Undo
            </Button>
          )}
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
 * A game: what to do now for its scenario, the board with manual move entry, agent
 * turns and hints, the hands, the moves, replay and undo.
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
