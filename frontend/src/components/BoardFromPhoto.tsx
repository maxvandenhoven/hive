import { CircleAlertIcon, CircleCheckIcon, CircleHelpIcon } from "lucide-react";
import { useMemo } from "react";

import type { BoardEstimate } from "@/api/client";
import { useEstimateBoard } from "@/api/queries";
import { CameraCapture } from "@/components/CameraCapture";
import { ChoiceCards } from "@/components/ChoiceCards";
import { BoardDiagram } from "@/components/help/BoardDiagram";
import { toBoardView } from "@/lib/moves";
import { formatProbability } from "@/lib/photos";
import { SIDE_TITLES, type PlayerSide } from "@/lib/players";
import { cn } from "@/lib/utils";

/** How a board read from a photo is introduced, by how sure the reading is. */
const ESTIMATE_TITLES: Record<BoardEstimate["status"], string> = {
  confident: "Read the board from the photo",
  uncertain: "Read the board, but check it before you start",
  failed: "Could not read a board to start from",
};

interface BoardFromPhotoProps {
  /** The board read so far, or `null` before a photo. */
  estimate: BoardEstimate | null;
  /** The side to move next on the board. */
  nextPlayer: PlayerSide;
  onEstimate: (estimate: BoardEstimate | null) => void;
  onNextPlayer: (side: PlayerSide) => void;
}

/**
 * The starting position from a photo of a physical board: the board the photo shows,
 * how sure the reading is and why, and who moves next. Stacks cannot be read from one
 * photo, since the tiles under a beetle are hidden.
 */
export function BoardFromPhoto({
  estimate,
  nextPlayer,
  onEstimate,
  onNextPlayer,
}: BoardFromPhotoProps) {
  const estimateBoard = useEstimateBoard();
  const board = useMemo(() => toBoardView(estimate?.board ?? []), [estimate]);
  const Icon =
    estimate?.status === "confident"
      ? CircleCheckIcon
      : estimate?.status === "uncertain"
        ? CircleHelpIcon
        : CircleAlertIcon;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <CameraCapture
          label={estimate === null ? "Take a photo" : "Another photo"}
          busy={estimateBoard.isPending}
          onCapture={(image) => {
            estimateBoard.mutate(image, {
              onSuccess: onEstimate,
              onError: () => {
                onEstimate(null);
              },
            });
          }}
        />
        <p className="text-sm text-muted-foreground">
          Take the photo from above with every tile of the hive in view.
        </p>
      </div>
      {estimate !== null && (
        <div className="flex flex-col gap-3" aria-live="polite">
          <div className="flex items-start gap-2">
            <Icon
              aria-hidden="true"
              className={cn(
                "mt-0.5 size-4 shrink-0",
                estimate.status === "failed"
                  ? "text-destructive"
                  : "text-board-suggestion",
              )}
            />
            <div className="flex flex-col gap-1">
              <p className="font-medium">{ESTIMATE_TITLES[estimate.status]}</p>
              {estimate.tiles.length > 0 && (
                <p className="text-sm text-muted-foreground">
                  {estimate.tiles.length} {estimate.tiles.length === 1 ? "tile" : "tiles"}
                  , the least clear {formatProbability(estimate.lowest_probability)} sure.
                  {estimate.ignored > 0 &&
                    ` ${estimate.ignored} tiles away from the hive were left out.`}
                </p>
              )}
              {estimate.reasons.map((reason) => (
                <p key={reason} className="text-sm">
                  {reason}
                </p>
              ))}
            </div>
          </div>
          {board.length > 0 && (
            <BoardDiagram
              board={board}
              title="The board from the photo"
              caption="Compare it with the table; take another photo if a tile is wrong."
            />
          )}
          {estimate.players.length > 0 && estimate.status !== "failed" && (
            <ChoiceCards
              legend="Who moves next"
              layout="row"
              value={
                estimate.players.includes(nextPlayer)
                  ? nextPlayer
                  : (estimate.players[0] ?? nextPlayer)
              }
              options={estimate.players.map((side) => ({
                value: side,
                title: `${SIDE_TITLES[side]} to move`,
              }))}
              onChange={onNextPlayer}
            />
          )}
        </div>
      )}
    </div>
  );
}
