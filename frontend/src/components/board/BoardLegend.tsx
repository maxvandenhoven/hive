import { KeyRoundIcon, XIcon } from "lucide-react";
import { useId, useState } from "react";

import {
  BOARD_MARKS,
  type BoardMarkInfo,
  type BoardMarkKind,
} from "@/components/board/boardMarks";
import { MarkSwatch } from "@/components/board/marks";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Where the legend remembers whether it is open, per device. */
export const LEGEND_STORAGE_KEY = "hive.board-legend.open";

function readOpen(): boolean {
  try {
    return window.localStorage.getItem(LEGEND_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function writeOpen(open: boolean) {
  try {
    window.localStorage.setItem(LEGEND_STORAGE_KEY, String(open));
  } catch {
    // Without storage the legend just forgets.
  }
}

interface BoardMarkListProps {
  title: string;
  marks: readonly BoardMarkInfo[];
  /** Show the descriptions on a phone too, as the help does; the legend hides them. */
  describeOnPhone?: boolean;
}

/** A titled list of marks, each with its swatch, label and description. */
export function BoardMarkList({
  title,
  marks,
  describeOnPhone = false,
}: BoardMarkListProps) {
  if (marks.length === 0) {
    return null;
  }

  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
      <ul aria-label={title} className="flex flex-col gap-1.5">
        {marks.map((mark) => (
          <li key={mark.kind} className="flex items-center gap-2">
            <span className="flex w-12 shrink-0 justify-center sm:w-16">
              <MarkSwatch kind={mark.kind} />
            </span>
            <span className="flex flex-col leading-tight">
              <span className="font-medium">{mark.label}</span>
              <span
                className={cn(
                  "text-xs text-muted-foreground",
                  !describeOnPhone && "hidden sm:block",
                )}
              >
                {mark.description}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

interface BoardLegendProps {
  /** The marks on the board now, listed first; `boardMarksShown` finds them. */
  shown: BoardMarkKind[];
  className?: string;
}

/**
 * A Key button that opens a small legend of the board marks: the marks on the board now
 * first, then the rest. Whether it is open is remembered per device. Renderers place it
 * on top of the board.
 */
export function BoardLegend({ shown, className }: BoardLegendProps) {
  const [open, setOpen] = useState(readOpen);
  const panelId = useId();
  const onBoard = BOARD_MARKS.filter((mark) => shown.includes(mark.kind));
  const others = BOARD_MARKS.filter((mark) => !shown.includes(mark.kind));

  const toggle = () => {
    setOpen(!open);
    writeOpen(!open);
  };

  return (
    <div
      className={cn(
        "pointer-events-none flex max-w-[min(19rem,calc(100%-1rem))] flex-col items-start justify-end gap-1",
        className,
      )}
    >
      {open && (
        <div
          id={panelId}
          role="region"
          aria-label="Board key"
          className="pointer-events-auto flex min-h-0 flex-col gap-3 overflow-y-auto rounded-lg bg-popover p-3 text-sm text-popover-foreground shadow-md ring-1 ring-border"
        >
          <BoardMarkList title="On the board" marks={onBoard} />
          <BoardMarkList
            title={onBoard.length > 0 ? "Other marks" : "Marks"}
            marks={others}
          />
        </div>
      )}
      <Button
        variant="outline"
        size="sm"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        className="pointer-events-auto"
        onClick={toggle}
      >
        {open ? <XIcon /> : <KeyRoundIcon />}
        Key
      </Button>
    </div>
  );
}
