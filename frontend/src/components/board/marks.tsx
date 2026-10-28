/*
 * The marks of the SVG board, centred on the origin in board units. Each has one meaning
 * and one colour token, and differs from the others in shape, dash or fill too, so it
 * reads without colour. The legend draws its swatches with the same components.
 */
import type { ReactNode } from "react";

import { moveArc, moveArrow, type MoveArrowGeometry } from "@/components/board/arrows";
import type { BoardMarkKind } from "@/components/board/boardMarks";
import { hexPoints } from "@/components/board/hex";
import { TILE_RADIUS } from "@/components/board/PieceTile";
import { cn } from "@/lib/utils";

const ORIGIN = { x: 0, y: 0 };
const HALO_POINTS = hexPoints(ORIGIN, 1);
// A little larger than a hex, so it reads as a wide band rather than a thick ring; the
// tiles next to it are drawn over its edge.
const SELECTED_POINTS = hexPoints(ORIGIN, 1.08);
const RING_POINTS = hexPoints(ORIGIN, TILE_RADIUS);
const TARGET_POINTS = hexPoints(ORIGIN, 0.8);
const LAST_MOVE_POINTS = hexPoints(ORIGIN, 0.96);
const SUGGESTION_OUTER_POINTS = hexPoints(ORIGIN, 1);
const SUGGESTION_INNER_POINTS = hexPoints(ORIGIN, 0.8);

/** How far the shadow of a raised tile falls, down and to the right. */
const SHADOW_OFFSET = { x: 0.06, y: 0.1 };

/** The shadow under a tile that can move, drawn before the tile so it looks raised. */
export function MovableShadow() {
  return (
    <polygon
      data-mark="movable"
      points={RING_POINTS}
      transform={`translate(${SHADOW_OFFSET.x} ${SHADOW_OFFSET.y})`}
      className="fill-foreground/35"
    />
  );
}

/** The ring on a tile that can move, drawn over the tile. */
export function MovableRing() {
  return (
    <polygon
      data-mark="movable"
      points={RING_POINTS}
      fill="none"
      strokeWidth={0.08}
      className="stroke-board-movable"
    />
  );
}

/** How far a selected tile lifts towards the top of the screen. */
const SELECTED_LIFT = 0.1;

/**
 * Lifts its tile a little when it is selected, easing up and down; the shadow under it,
 * drawn outside, then shows more. The lift is a CSS transform, separate from the
 * `transform` attribute that animates a move.
 */
export function SelectionLift({
  lifted,
  children,
}: {
  lifted: boolean;
  children: ReactNode;
}) {
  return (
    <g
      data-lifted={lifted ? "" : undefined}
      style={{ transform: `translateY(${lifted ? -SELECTED_LIFT : 0}px)` }}
      className="transition-transform duration-150 ease-out motion-reduce:transition-none"
    >
      {children}
    </g>
  );
}

/** A solid halo behind the selected tile. */
export function SelectedHalo() {
  return (
    <polygon
      data-mark="selected"
      points={SELECTED_POINTS}
      className="fill-board-movable"
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
 * A dotted outline with a light fill: faint on the hex the last move came from (its arrow
 * goes from there), stronger behind a tile that was placed.
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

/** The marks drawn as a move arrow. */
export type MoveArrowMark = "lastMove" | "suggestion";

const ARROW_CLASSES: Record<MoveArrowMark, { stroke: string; fill: string }> = {
  lastMove: { stroke: "stroke-board-last-move", fill: "fill-board-last-move" },
  suggestion: { stroke: "stroke-board-suggestion", fill: "fill-board-suggestion" },
};

/**
 * A curved arrow for a move, in the colour of its mark, on a light casing so it reads
 * over tiles of both colours. It fades in whenever it is drawn anew.
 */
export function MoveArrow({
  arrow,
  mark,
}: {
  arrow: MoveArrowGeometry;
  mark: MoveArrowMark;
}) {
  const head = arrow.head.map(({ x, y }) => `${x},${y}`).join(" ");
  const classes = ARROW_CLASSES[mark];

  return (
    <g
      data-mark={mark}
      data-arrow={mark}
      pointerEvents="none"
      aria-hidden="true"
      className="animate-in duration-300 fade-in"
    >
      <path
        d={arrow.path}
        fill="none"
        strokeWidth={0.28}
        strokeLinecap="round"
        className="stroke-card/80"
      />
      <polygon
        points={head}
        strokeWidth={0.14}
        strokeLinejoin="round"
        className="fill-card/80 stroke-card/80"
      />
      <path
        d={arrow.path}
        fill="none"
        strokeWidth={0.14}
        strokeLinecap="round"
        className={classes.stroke}
      />
      <polygon points={head} className={classes.fill} />
    </g>
  );
}

/**
 * A faint dotted hex where a suggested move starts, so it shows also once the piece has
 * left it on the screen while it still stands there on the table.
 */
export function SuggestionSource() {
  return (
    <g data-mark="suggestion" pointerEvents="none">
      <polygon points={HALO_POINTS} className="fill-board-suggestion/15" />
      <polygon
        points={LAST_MOVE_POINTS}
        fill="none"
        strokeWidth={0.09}
        strokeLinecap="round"
        strokeDasharray="0 0.19"
        className="stroke-board-suggestion"
      />
    </g>
  );
}

/** A double ring where an agent suggests a piece goes, at the end of its arrow. */
export function SuggestionRing() {
  return (
    <g data-mark="suggestion" pointerEvents="none" fill="none" aria-hidden="true">
      <polygon
        points={SUGGESTION_OUTER_POINTS}
        strokeWidth={0.08}
        className="stroke-board-suggestion"
      />
      <polygon
        points={SUGGESTION_INNER_POINTS}
        strokeWidth={0.06}
        className="stroke-board-suggestion"
      />
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

/** The arrow of the swatches, from the hex left of the origin to the origin. */
const SWATCH_ARROW = moveArrow(moveArc({ from: [-1, 0], to: [0, 0], centre: null }));
const SWATCH_SOURCE = "translate(-1.732 0)";

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
          <SelectedHalo />
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
          <g transform={SWATCH_SOURCE}>
            <LastMoveMark part="from" />
          </g>
          <BlankTile />
          <MoveArrow arrow={SWATCH_ARROW} mark="lastMove" />
        </>
      );
    case "suggestion":
      return (
        <>
          <g transform={SWATCH_SOURCE}>
            <BlankTile />
          </g>
          <SuggestionRing />
          <MoveArrow arrow={SWATCH_ARROW} mark="suggestion" />
        </>
      );
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
  const viewBox =
    kind === "suggestion" || kind === "lastMove"
      ? "-2.8 -1.2 4 2.4"
      : "-1.2 -1.2 2.4 2.4";

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
