import {
  CheckIcon,
  Loader2Icon,
  RadioIcon,
  RotateCcwIcon,
  SkipForwardIcon,
  Undo2Icon,
} from "lucide-react";
import type { ReactNode } from "react";

import type { GamePosition } from "@/api/client";
import type { BoardView } from "@/components/board/types";
import { HintButton, HintStatus } from "@/components/HintButton";
import { MatchControls } from "@/components/MatchControls";
import { NewGameDialog } from "@/components/NewGameDialog";
import type { AgentTurns } from "@/components/useAgentTurns";
import type { Hint } from "@/components/useHint";
import { Button } from "@/components/ui/button";
import type { TurnPrompt as TurnPromptView } from "@/lib/turnPrompt";
import { cn } from "@/lib/utils";

interface TurnPromptProps {
  prompt: TurnPromptView;
  /** The latest position. */
  position: GamePosition;
  /** The latest board, which a hint is described on. */
  board: BoardView;
  turns: AgentTurns;
  hint: Hint;
  /** Whether a move, undo or confirmation is being sent. */
  busy: boolean;
  onPass: () => void;
  onUndo: () => void;
  /** Return from a replayed position to the live one. */
  onLive: () => void;
  /** The help button for the current scenario and turn, after the actions. */
  help?: ReactNode;
}

/**
 * The strip above the board that says what to do now in one sentence, with only the
 * actions that fit: **Done** for an agent move to make on the table, **Hint** and
 * **Pass** on a person's turn, the match controls when watching, **Undo** and **New
 * game** once the game is over.
 */
export function TurnPrompt({
  prompt,
  position,
  board,
  turns,
  hint,
  busy,
  onPass,
  onUndo,
  onLive,
  help,
}: TurnPromptProps) {
  const { kind } = prompt;
  const suggests = kind === "pending" || (kind === "turn" && hint.state.type === "shown");

  return (
    <section
      aria-label="Turn prompt"
      className={cn(
        "flex flex-col gap-2 rounded-xl bg-card px-3 py-2 ring-1 ring-border",
        suggests && "ring-2 ring-board-suggestion",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p aria-live="polite" className="min-w-0 flex-1 basis-56 font-medium">
          {kind === "thinking" && (
            <Loader2Icon
              aria-hidden="true"
              className="mr-2 inline size-4 animate-spin align-[-0.125em]"
            />
          )}
          {prompt.text}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {kind === "replay" && (
            <Button variant="outline" onClick={onLive}>
              <RadioIcon />
              Go live
            </Button>
          )}
          {kind === "pending" && (
            <Button size="lg" disabled={busy || turns.confirming} onClick={turns.done}>
              <CheckIcon />
              Done
            </Button>
          )}
          {kind === "turn" && position.must_pass && (
            <Button disabled={busy} onClick={onPass}>
              <SkipForwardIcon />
              Pass
            </Button>
          )}
          {kind === "turn" && hint.agent !== null && <HintButton hint={hint} />}
          {kind === "failed" && (
            <Button variant="outline" onClick={turns.retry}>
              <RotateCcwIcon />
              Try again
            </Button>
          )}
          {kind === "over" && (
            <Button variant="outline" disabled={busy} onClick={onUndo}>
              <Undo2Icon />
              Undo
            </Button>
          )}
          {(kind === "over" || kind === "abandoned") && <NewGameDialog />}
          {help}
        </div>
      </div>
      {kind === "watching" && <MatchControls turns={turns} />}
      {kind === "turn" && hint.agent !== null && (
        <HintStatus agent={hint.agent} state={hint.state} board={board} />
      )}
    </section>
  );
}
