import { PauseIcon, PlayIcon, StepForwardIcon } from "lucide-react";
import { useId } from "react";

import type { AgentTurns } from "@/components/useAgentTurns";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** The pauses between the moves of a match that can be chosen, in seconds. */
const MATCH_DELAYS_S = [0, 1, 2, 5];

/** Play, pause and step through an agent vs agent match, with a pause between moves. */
export function MatchControls({ turns }: { turns: AgentTurns }) {
  const delayId = useId();
  const over = turns.agent === null && turns.state.type === "idle";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        aria-pressed={turns.autoplay}
        disabled={over && !turns.autoplay}
        onClick={() => {
          turns.setAutoplay(!turns.autoplay);
        }}
      >
        {turns.autoplay ? <PauseIcon /> : <PlayIcon />}
        {turns.autoplay ? "Pause" : "Play"}
      </Button>
      <Button
        variant="outline"
        disabled={turns.autoplay || turns.agent === null || turns.state.type !== "idle"}
        onClick={turns.step}
      >
        <StepForwardIcon />
        Step
      </Button>
      <div className="flex items-center gap-2">
        <Label htmlFor={delayId} className="text-muted-foreground">
          Delay
        </Label>
        <Select
          value={String(turns.delayS)}
          onValueChange={(value) => {
            turns.setDelayS(Number(value));
          }}
        >
          <SelectTrigger id={delayId} size="sm" className="w-24">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MATCH_DELAYS_S.map((delay) => (
              <SelectItem key={delay} value={String(delay)}>
                {delay === 0 ? "None" : `${delay} s`}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
