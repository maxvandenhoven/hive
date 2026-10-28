import { LightbulbIcon, Loader2Icon, TriangleAlertIcon } from "lucide-react";

import type { HintAgent } from "@/api/client";
import type { BoardView } from "@/components/board/types";
import type { Hint, HintState } from "@/components/useHint";
import { useSecondsLeft } from "@/components/useSecondsLeft";
import { Button } from "@/components/ui/button";
import { describeMoveOnBoard } from "@/lib/moves";

/** The Hint button: asks for a hint, and hides it (or stops its search) when pressed again. */
export function HintButton({
  hint,
  size = "default",
}: {
  hint: Hint;
  size?: "default" | "sm";
}) {
  const active = hint.state.type !== "hidden";

  return (
    <Button
      variant={active ? "secondary" : "outline"}
      size={size}
      aria-pressed={active}
      onClick={hint.toggle}
    >
      <LightbulbIcon />
      Hint
    </Button>
  );
}

/** The seconds the hint agent has left, as a compact countdown. */
function HintCountdown({
  startedAt,
  agent,
}: {
  startedAt: number | null;
  agent: HintAgent;
}) {
  const left = useSecondsLeft(startedAt, agent.budget_s);

  return (
    <span className="text-muted-foreground tabular-nums">{left.toFixed(1)} s left</span>
  );
}

interface HintStatusProps {
  agent: HintAgent;
  state: HintState;
  /** The latest board, which the hinted move is described on. */
  board: BoardView;
}

/**
 * The hint in one line: a compact indicator with the time left while the hint agent
 * thinks, then the hinted move as a sentence (`Hint: grasshopper jumps over the white
 * queen`), which the board shows as an arrow.
 */
export function HintStatus({ agent, state, board }: HintStatusProps) {
  if (state.type === "hidden") {
    return null;
  }

  if (state.type === "thinking") {
    return (
      <p className="flex items-center gap-2 text-sm">
        <Loader2Icon className="size-4 animate-spin" aria-hidden="true" />
        <span>Hint: thinking…</span>
        <HintCountdown startedAt={state.startedAt} agent={agent} />
      </p>
    );
  }

  if (state.type === "failed") {
    return (
      <p className="flex items-center gap-2 text-sm text-destructive">
        <TriangleAlertIcon className="size-4" aria-hidden="true" />
        No hint: {state.message}
      </p>
    );
  }

  return (
    <p className="flex items-center gap-2 text-sm font-medium">
      <LightbulbIcon className="size-4 text-board-suggestion" aria-hidden="true" />
      Hint: {describeMoveOnBoard(state.move, board)}
    </p>
  );
}
