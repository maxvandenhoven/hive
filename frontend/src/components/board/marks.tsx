/*
 * The marks of the SVG board, centred on the origin in board units. Each has one meaning
 * and one colour token, and differs from the others in shape, dash or fill too, so it
 * reads without colour. The legend draws its swatches with the same components.
 */
import { useId } from "react";

import type { BoardMarkKind } from "@/components/board/boardMarks";
import { hexPoints, roundedHexPath, type PixelPoint } from "@/components/board/hex";
import { TILE_RADIUS } from "@/components/board/PieceTile";
import { cn } from "@/lib/utils";

const ORIGIN = { x: 0, y: 0 };
const HALO_POINTS = hexPoints(ORIGIN, 1);
const SELECTED_PATH = roundedHexPath(0.96);
const TILE_PATH = roundedHexPath(TILE_RADIUS);
const RING_POINTS = hexPoints(ORIGIN, TILE_RADIUS);
const TARGET_POINTS = hexPoints(ORIGIN, 0.8);
const LAST_MOVE_POINTS = hexPoints(ORIGIN, 0.96);
// The rings stay inside the hex, radius plus half the stroke at most 1, and the outer
// one leaves a gap around a tile.
const SUGGESTION_STROKE = 0.07;
const SUGGESTION_OUTER_PATH = roundedHexPath(1 - SUGGESTION_STROKE / 2);
const SUGGESTION_INNER_PATH = roundedHexPath(0.8);

/** How far the shadow of a raised tile falls, down and to the right. */
const SHADOW_OFFSET = { x: 0.06, y: 0.1 };

/** The shadow under a tile that can move, drawn before the tile so it looks raised. */
export function MovableShadow() {
  return (
    <path
      data-mark="movable"
      d={TILE_PATH}
      transform={`translate(${SHADOW_OFFSET.x} ${SHADOW_OFFSET.y})`}
      className="fill-foreground/35"
    />
  );
}

/** The ring on a tile that can move, drawn over the tile. */
export function MovableRing() {
  return (
    <path
      data-mark="movable"
      d={TILE_PATH}
      fill="none"
      strokeWidth={0.08}
      className="stroke-board-movable"
    />
  );
}

/** An unfilled outline around the selected tile that leaves neighbours visible. */
export function SelectedOutline() {
  return (
    <path
      data-mark="selected"
      d={SELECTED_PATH}
      fill="none"
      strokeWidth={0.06}
      className="stroke-board-movable"
    />
  );
}

/**
 * Where the selection can go: a dashed hex with a dot on an empty hex, or a dashed ring
 * with a dot on a tile it climbs onto.
 */
export function TargetMark({ occupied }: { occupied: boolean }) {
  return (
    <g data-mark={occupied ? "climb" : "target"}>
      {occupied ? (
        <polygon
          points={RING_POINTS}
          strokeWidth={0.12}
          strokeDasharray="0.2 0.1"
          className="fill-board-target/20 stroke-board-target"
        />
      ) : (
        <polygon
          points={TARGET_POINTS}
          strokeWidth={0.05}
          strokeDasharray="0.15 0.1"
          className="fill-board-target/15 stroke-board-target"
        />
      )}
      <circle r={0.16} className="fill-board-target" />
    </g>
  );
}

/**
 * A dotted outline with a light fill on where the last move came from, and a stronger one
 * behind the tile where it went.
 */
export function LastMoveMark({ part }: { part: "from" | "to" }) {
  return (
    <g data-mark="lastMove" pointerEvents="none">
      <polygon
        points={HALO_POINTS}
        className={part === "to" ? "fill-board-last-move/45" : "fill-board-last-move/20"}
      />
      <polygon
        points={LAST_MOVE_POINTS}
        fill="none"
        strokeWidth={0.09}
        strokeLinecap="round"
        strokeDasharray="0 0.19"
        className="stroke-board-last-move"
      />
    </g>
  );
}

interface SuggestionMarkProps {
  /** Where the move starts, or `null` for a placement. */
  from: PixelPoint | null;
  to: PixelPoint;
}

/** A single rounded ring around the piece an agent suggests to move, on the board or in hand. */
export function SuggestionSourceRing() {
  return (
    <path
      data-mark="suggestion"
      d={SUGGESTION_OUTER_PATH}
      fill="none"
      strokeWidth={SUGGESTION_STROKE}
      pointerEvents="none"
      className="stroke-board-suggestion"
    />
  );
}

/**
 * An agent's suggested move: a single ring around the piece to move, an arrow from it and
 * a double ring where it goes. A placement has its single ring on the piece in hand.
 */
export function SuggestionMark({ from, to }: SuggestionMarkProps) {
  const arrowId = useId();
  let arrow = null;

  if (from !== null) {
    const length = Math.hypot(to.x - from.x, to.y - from.y);
    // End the line at the ring, so the arrowhead stays visible.
    const end = length > 0 ? (length - 0.95) / length : 0;

    arrow = (
      <line
        x1={from.x}
        y1={from.y}
        x2={from.x + (to.x - from.x) * end}
        y2={from.y + (to.y - from.y) * end}
        strokeWidth={0.14}
        strokeLinecap="round"
        markerEnd={`url(#${arrowId})`}
        className="stroke-board-suggestion"
      />
    );
  }

  return (
    <g data-mark="suggestion" pointerEvents="none" opacity={0.9} aria-hidden="true">
      <defs>
        <marker
          id={arrowId}
          viewBox="0 0 10 10"
          refX="5"
          refY="5"
          markerWidth="3"
          markerHeight="3"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" className="fill-board-suggestion" />
        </marker>
      </defs>
      {from !== null && (
        <g transform={`translate(${from.x} ${from.y})`}>
          <SuggestionSourceRing />
        </g>
      )}
      {arrow}
      <g transform={`translate(${to.x} ${to.y})`} fill="none">
        <path
          d={SUGGESTION_OUTER_PATH}
          strokeWidth={SUGGESTION_STROKE}
          className="stroke-board-suggestion"
        />
        <path
          d={SUGGESTION_INNER_PATH}
          strokeWidth={SUGGESTION_STROKE}
          className="stroke-board-suggestion"
        />
      </g>
    </g>
  );
}

/** A red hex with a cross: "not allowed" in the rule diagrams. */
export function ForbiddenMark() {
  return (
    <g data-mark="forbidden" pointerEvents="none">
      <polygon
        points={TARGET_POINTS}
        strokeWidth={0.06}
        className="fill-board-forbidden/20 stroke-board-forbidden"
      />
      <path
        d="M -0.3 -0.3 L 0.3 0.3 M 0.3 -0.3 L -0.3 0.3"
        strokeWidth={0.12}
        strokeLinecap="round"
        className="stroke-board-forbidden"
      />
    </g>
  );
}

/** A tile without an insect, for swatches. */
function BlankTile() {
  return (
    <polygon
      points={RING_POINTS}
      strokeWidth={0.04}
      className="fill-tile-white stroke-tile-stroke"
    />
  );
}

/** The marks drawn on each swatch, with a blank tile where the mark needs one. */
function SwatchMarks({ kind }: { kind: BoardMarkKind }) {
  switch (kind) {
    case "movable":
      return (
        <>
          <MovableShadow />
          <BlankTile />
          <MovableRing />
        </>
      );
    case "selected":
      return (
        <>
          <SelectedOutline />
          <MovableShadow />
          <BlankTile />
          <MovableRing />
        </>
      );
    case "target":
      return <TargetMark occupied={false} />;
    case "climb":
      return (
        <>
          <BlankTile />
          <TargetMark occupied />
        </>
      );
    case "lastMove":
      return (
        <>
          <LastMoveMark part="to" />
          <BlankTile />
        </>
      );
    case "suggestion":
      return <SuggestionMark from={{ x: -2.4, y: 0 }} to={ORIGIN} />;
    case "forbidden":
      return <ForbiddenMark />;
  }
}

/** A mark as a small picture for the legend and the help, drawn as on the board. */
export function MarkSwatch({
  kind,
  className,
}: {
  kind: BoardMarkKind;
  className?: string;
}) {
  const viewBox = kind === "suggestion" ? "-2.6 -1.2 3.8 2.4" : "-1.2 -1.2 2.4 2.4";

  return (
    <svg
      viewBox={viewBox}
      aria-hidden="true"
      className={cn("h-7 shrink-0 sm:h-9", className)}
    >
      <SwatchMarks kind={kind} />
    </svg>
  );
}
