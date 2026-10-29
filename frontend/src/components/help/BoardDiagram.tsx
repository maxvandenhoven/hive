import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { SvgBoard } from "@/components/board/SvgBoard";
import type {
  BoardRenderer,
  BoardView,
  HexCoord,
  MoveView,
} from "@/components/board/types";
import { Button } from "@/components/ui/button";
import type { DiagramStep } from "@/lib/rulesDiagrams";

/** The renderer of the diagrams, the same as on the game page. */
const Board: BoardRenderer = SvgBoard;

interface BoardDiagramProps {
  board: BoardView;
  /** What the diagram shows in a few words, above the board. */
  title: string;
  caption: ReactNode;
  highlights?: HexCoord[];
  movable?: HexCoord[];
  selected?: HexCoord | null;
  lastMove?: MoveView | null;
  proposedMove?: MoveView | null;
  forbidden?: HexCoord[];
  /** The positions to step through after the first, one per step of the move. */
  steps?: DiagramStep[];
}

/**
 * A small static board drawn by the real renderer, with a caption. A diagram with steps
 * has buttons to step through the move, each step marked as the last move.
 */
export function BoardDiagram({
  board,
  title,
  caption,
  highlights = [],
  movable = [],
  selected = null,
  lastMove = null,
  proposedMove = null,
  forbidden = [],
  steps = [],
}: BoardDiagramProps) {
  const [stepIndex, setStepIndex] = useState(0);
  const step = stepIndex > 0 ? steps[stepIndex - 1] : undefined;

  return (
    <figure className="flex flex-col gap-2" aria-label={title}>
      <div className="flex min-h-8 items-center justify-between gap-2">
        <span className="text-sm font-medium">{title}</span>
        {steps.length > 0 && (
          <div className="flex items-center gap-1">
            <span className="text-xs text-muted-foreground" aria-live="polite">
              Step {stepIndex} of {steps.length}
            </span>
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Previous step"
              disabled={stepIndex === 0}
              onClick={() => {
                setStepIndex(stepIndex - 1);
              }}
            >
              <ChevronLeftIcon />
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Next step"
              disabled={stepIndex === steps.length}
              onClick={() => {
                setStepIndex(stepIndex + 1);
              }}
            >
              <ChevronRightIcon />
            </Button>
          </div>
        )}
      </div>
      <div className="aspect-[4/3] w-full overflow-hidden rounded-xl bg-board-surface ring-1 ring-border">
        <Board
          diagram
          board={step?.board ?? board}
          highlights={step ? [] : highlights}
          movable={step ? [] : movable}
          selected={step ? null : selected}
          lastMove={step?.lastMove ?? lastMove}
          proposedMove={step ? null : proposedMove}
          forbidden={step ? [] : forbidden}
          onHexClick={() => undefined}
        />
      </div>
      <figcaption className="text-sm text-muted-foreground">{caption}</figcaption>
    </figure>
  );
}
