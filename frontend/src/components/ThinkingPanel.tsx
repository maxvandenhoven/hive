import { CheckIcon, Loader2Icon, RotateCcwIcon, TriangleAlertIcon } from "lucide-react";
import { useEffect, useState } from "react";

import type { GameDetail, GamePosition } from "@/api/client";
import type { AgentTurns } from "@/components/useAgentTurns";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { describeMove } from "@/lib/moves";
import { describePlayer, SIDE_TITLES, type PlayerSide } from "@/lib/players";
import { formatCount, formatScore, summarizeSearch, type ThinkInfo } from "@/lib/search";

/** How often the time left is redrawn, in milliseconds. */
const CLOCK_INTERVAL_MS = 100;

/** The seconds an agent has left of its budget, counting down. */
function TimeLeft({ startedAt, budgetS }: { startedAt: number | null; budgetS: number }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const interval = setInterval(() => {
      setNow(Date.now());
    }, CLOCK_INTERVAL_MS);

    return () => {
      clearInterval(interval);
    };
  }, []);

  const left =
    startedAt === null ? budgetS : Math.max(0, budgetS - (now - startedAt) / 1000);

  return (
    <div className="flex items-center gap-3">
      <Progress
        value={(left / budgetS) * 100}
        aria-label="Time left"
        className="flex-1"
      />
      <span className="w-14 text-right text-sm tabular-nums">{left.toFixed(1)} s</span>
    </div>
  );
}

/** The depth, score and speed of a search, as far as the agent reported them. */
function SearchStats({ info }: { info: ThinkInfo | null }) {
  const { depth, score, nodes, nps } = summarizeSearch(info);
  const stats: [string, string][] = [
    ["Depth", depth === null ? "–" : String(depth)],
    ["Score", score === null ? "–" : formatScore(score)],
    ["Nodes", nodes === null ? "–" : formatCount(nodes)],
    ["Nodes/s", nps === null ? "–" : formatCount(nps)],
  ];

  return (
    <dl className="grid grid-cols-4 gap-2 text-sm">
      {stats.map(([label, value]) => (
        <div key={label} className="flex flex-col">
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="font-medium tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

interface ThinkingPanelProps {
  game: GameDetail;
  /** The latest position. */
  position: GamePosition;
  turns: AgentTurns;
}

/**
 * The agent turn: the live search while an agent thinks, the move to make on the board
 * with **Done** once it committed, or the failure with a retry.
 */
export function ThinkingPanel({ game, position, turns }: ThinkingPanelProps) {
  const { state } = turns;

  if (state.type === "idle") {
    return null;
  }

  const side = position.current_player;
  // A committed move was made by the side before the one to move now.
  const mover: PlayerSide = side === "white" ? "black" : "white";

  if (state.type === "thinking") {
    const player = game[side];

    return (
      <Card size="sm" role="region" aria-label="Agent thinking">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Loader2Icon className="size-4 animate-spin" />
            {SIDE_TITLES[side]} is thinking
          </CardTitle>
          <CardDescription>{describePlayer(player)}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {player.type === "agent" && (
            <TimeLeft startedAt={state.startedAt} budgetS={player.budget_s} />
          )}
          <SearchStats info={state.info} />
          <p className="text-sm">
            <span className="text-muted-foreground">Best so far: </span>
            {state.candidate === undefined ? "–" : describeMove(state.candidate)}
          </p>
        </CardContent>
      </Card>
    );
  }

  if (state.type === "failed") {
    return (
      <Card size="sm" role="region" aria-label="Agent thinking">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-destructive">
            <TriangleAlertIcon className="size-4" />
            {SIDE_TITLES[side]} could not move
          </CardTitle>
          <CardDescription>{state.message}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" onClick={turns.retry}>
            <RotateCcwIcon />
            Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card
      size="sm"
      role="region"
      aria-label="Agent thinking"
      className={turns.awaitingDone ? "ring-2 ring-board-suggestion" : undefined}
    >
      <CardHeader>
        <CardTitle>
          {turns.awaitingDone
            ? "Make this move on the board"
            : `${SIDE_TITLES[mover]} played`}
        </CardTitle>
        <CardDescription className="text-base text-foreground">
          {SIDE_TITLES[mover]}: {describeMove(state.move)}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <SearchStats info={state.info} />
        {turns.awaitingDone && (
          <Button size="lg" onClick={turns.done}>
            <CheckIcon />
            Done
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
