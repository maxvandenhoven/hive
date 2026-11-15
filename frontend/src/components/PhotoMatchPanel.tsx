import {
  CheckIcon,
  ChevronDownIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  CircleHelpIcon,
  Loader2Icon,
  XIcon,
} from "lucide-react";
import { useState } from "react";

import { CameraCapture } from "@/components/CameraCapture";
import type { PhotoMoves } from "@/components/usePhotoMoves";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  formatProbability,
  type PhotoCandidateView,
  type PhotoOutcome,
} from "@/lib/photos";
import { cn } from "@/lib/utils";

/** The icon of each outcome: a check when clear, a question when unsure, else a warning. */
const OUTCOME_ICONS: Record<PhotoOutcome, typeof CheckIcon> = {
  proposal: CircleCheckIcon,
  matched: CircleCheckIcon,
  candidates: CircleHelpIcon,
  unclear: CircleHelpIcon,
  failed: CircleAlertIcon,
  mismatched: CircleAlertIcon,
  unread: CircleAlertIcon,
};

interface MatchCandidatesProps {
  candidates: PhotoCandidateView[];
  selected: number;
  onSelect: (index: number) => void;
}

/** The candidate moves of a photo, best first, each with how likely it is. */
function MatchCandidates({ candidates, selected, onSelect }: MatchCandidatesProps) {
  return (
    <ul aria-label="Moves the photo may show" className="flex flex-col gap-1">
      {candidates.map((candidate, index) => (
        <li key={index}>
          <Button
            variant="outline"
            size="sm"
            aria-pressed={index === selected}
            className="h-auto w-full justify-between gap-2 py-1.5 text-left font-normal whitespace-normal aria-pressed:border-board-suggestion aria-pressed:bg-muted"
            onClick={() => {
              onSelect(index);
            }}
          >
            <span>{candidate.text}</span>
            <Badge variant="secondary" className="tabular-nums">
              {formatProbability(candidate.probability)}
            </Badge>
          </Button>
        </li>
      ))}
    </ul>
  );
}

/**
 * What the last photo of the board showed, under the turn prompt: the proposed move to
 * play (shown on the board), the candidates when the photo is unclear, or why it could
 * not be read, with a retake and a way back to entering the move by hand.
 */
export function PhotoMatchPanel({ photos }: { photos: PhotoMoves }) {
  const [showOthers, setShowOthers] = useState(false);
  const { state } = photos;

  if (state.type === "idle") {
    return null;
  }

  const retake = (
    <CameraCapture
      label="Another photo"
      disabled={photos.busy}
      busy={state.type === "reading"}
      onCapture={(image) => {
        setShowOthers(false);
        photos.take(image);
      }}
    />
  );

  if (state.type === "reading") {
    return (
      <Card size="sm" role="region" aria-label="Photo of the board">
        <CardContent className="flex items-center gap-3">
          <img
            src={state.previewUrl}
            alt="The photo being read"
            className="size-16 shrink-0 rounded-md object-cover"
          />
          <p className="flex items-center gap-2 text-sm" aria-live="polite">
            <Loader2Icon className="size-4 animate-spin" aria-hidden="true" />
            Reading the photo…
          </p>
        </CardContent>
      </Card>
    );
  }

  const { view, selected } = state;
  const Icon = OUTCOME_ICONS[view.outcome];
  const offersMove = view.outcome === "proposal" || view.outcome === "candidates";
  const listed =
    view.outcome === "candidates" || (view.outcome === "proposal" && showOthers);
  const doubtful = ["failed", "mismatched", "unread"].includes(view.outcome);

  return (
    <Card
      size="sm"
      role="region"
      aria-label="Photo of the board"
      className={cn(offersMove && "ring-2 ring-board-suggestion")}
    >
      <CardContent className="flex gap-3">
        <a href={state.previewUrl} target="_blank" rel="noreferrer" className="shrink-0">
          <img
            src={state.previewUrl}
            alt="The photo of the board"
            className="size-16 rounded-md object-cover sm:size-20"
          />
        </a>
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex items-start gap-2">
            <Icon
              aria-hidden="true"
              className={cn(
                "mt-0.5 size-4 shrink-0",
                doubtful ? "text-destructive" : "text-board-suggestion",
              )}
            />
            <div className="flex min-w-0 flex-1 flex-col gap-0.5" aria-live="polite">
              <p className="font-medium">{view.title}</p>
              {view.detail !== null && (
                <p className="text-sm text-muted-foreground">{view.detail}</p>
              )}
            </div>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Close the photo"
              onClick={photos.dismiss}
            >
              <XIcon />
            </Button>
          </div>
          {view.notes.length > 0 && (
            <ul className="flex flex-col gap-0.5 text-xs text-muted-foreground">
              {view.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
          {listed && (
            <MatchCandidates
              candidates={view.candidates}
              selected={selected}
              onSelect={photos.select}
            />
          )}
          <div className="flex flex-wrap items-center gap-2">
            {offersMove && view.candidates.length > 0 && (
              <Button disabled={photos.busy} onClick={photos.play}>
                <CheckIcon />
                {view.outcome === "proposal" && selected === 0
                  ? "Play this move"
                  : "Play the picked move"}
              </Button>
            )}
            {view.outcome === "mismatched" && (
              <Button variant="outline" disabled={photos.busy} onClick={photos.play}>
                Keep the move made at the table
              </Button>
            )}
            {retake}
            {view.outcome === "proposal" && view.candidates.length > 1 && (
              <Button
                variant="ghost"
                aria-expanded={showOthers}
                onClick={() => {
                  setShowOthers(!showOthers);
                }}
              >
                <ChevronDownIcon className={cn(showOthers && "rotate-180")} />
                Other moves
              </Button>
            )}
            {view.outcome !== "mismatched" && view.outcome !== "unclear" && (
              <Button variant="ghost" onClick={photos.dismiss}>
                Enter by hand
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
