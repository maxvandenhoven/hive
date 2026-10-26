import {
  ChevronFirstIcon,
  ChevronLastIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";

interface ReplayControlsProps {
  /** The ply shown, or `null` for the latest position. */
  ply: number | null;
  plyCount: number;
  /** Show the position after `ply` moves, or the latest position for `null`. */
  onChange: (ply: number | null) => void;
}

/**
 * Step and scrub through the positions of a game; the last ply is the live position,
 * which follows new moves.
 */
export function ReplayControls({ ply, plyCount, onChange }: ReplayControlsProps) {
  const shown = ply ?? plyCount;

  const go = (next: number) => {
    const clamped = Math.min(Math.max(next, 0), plyCount);
    onChange(clamped >= plyCount ? null : clamped);
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground tabular-nums" aria-live="polite">
          {ply === null ? `Live · ply ${plyCount}` : `Replay · ply ${ply} of ${plyCount}`}
        </p>
        <div className="flex gap-1">
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="First position"
            disabled={shown === 0}
            onClick={() => {
              go(0);
            }}
          >
            <ChevronFirstIcon />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Previous position"
            disabled={shown === 0}
            onClick={() => {
              go(shown - 1);
            }}
          >
            <ChevronLeftIcon />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Next position"
            disabled={ply === null}
            onClick={() => {
              go(shown + 1);
            }}
          >
            <ChevronRightIcon />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Live position"
            disabled={ply === null}
            onClick={() => {
              onChange(null);
            }}
          >
            <ChevronLastIcon />
          </Button>
        </div>
      </div>
      <Slider
        aria-label="Ply"
        min={0}
        max={plyCount}
        step={1}
        value={[shown]}
        disabled={plyCount === 0}
        onValueChange={([next]) => {
          if (next !== undefined) {
            go(next);
          }
        }}
      />
    </div>
  );
}
