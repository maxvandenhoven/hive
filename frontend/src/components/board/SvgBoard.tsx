import { ScanIcon, ZoomInIcon, ZoomOutIcon } from "lucide-react";
import { useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";

import type { Piece } from "@/api/client";
import {
  axialToPixel,
  formatHex,
  hexKey,
  hexPoints,
  pixelToAxial,
  sameHex,
} from "@/components/board/hex";
import { TILE_COLORS, TILE_STROKE } from "@/components/board/insects";
import { PieceIcon, PieceTile, TILE_RADIUS } from "@/components/board/PieceTile";
import type { BoardRendererProps, BoardStack, HexCoord } from "@/components/board/types";
import { screenToBoard, useViewGestures } from "@/components/board/useViewGestures";
import {
  fitViewBox,
  viewBoxAttribute,
  zoomViewBox,
  type ViewBox,
} from "@/components/board/viewBox";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
  PopoverHeader,
  PopoverTitle,
} from "@/components/ui/popover";
import { PIECE_NAMES } from "@/lib/moves";
import { SIDE_TITLES } from "@/lib/players";

/** The narrowest view, about two hexes across. */
const MIN_VIEW_WIDTH = 4;

/** How far the view may zoom out, relative to the fitted view. */
const MAX_ZOOM_OUT = 3;

/** How much one press of a zoom button zooms. */
const ZOOM_STEP = 1.25;

/** How far each piece below the top one peeks out of a stack. */
const STACK_OFFSET = 0.08;

const ORIGIN = { x: 0, y: 0 };
const HALO_POINTS = hexPoints(ORIGIN, 1);
const RING_POINTS = hexPoints(ORIGIN, TILE_RADIUS);
const TARGET_POINTS = hexPoints(ORIGIN, 0.8);

function describePiece(piece: Piece): string {
  return `${SIDE_TITLES[piece.owner]} ${PIECE_NAMES[piece.piece].toLowerCase()}`;
}

function translate(coord: HexCoord): string {
  const { x, y } = axialToPixel(coord);

  return `translate(${x} ${y})`;
}

/** The pieces below the top one, drawn behind it with an offset. */
function StackLayers({ pieces }: { pieces: Piece[] }) {
  return pieces
    .slice(1)
    .map((piece, index) => ({ piece, depth: index + 1 }))
    .reverse()
    .map(({ piece, depth }) => (
      <polygon
        key={depth}
        points={RING_POINTS}
        transform={`translate(${depth * STACK_OFFSET} ${depth * STACK_OFFSET})`}
        fill={TILE_COLORS[piece.owner]}
        stroke={TILE_STROKE}
        strokeWidth={0.04}
      />
    ));
}

function StackBadge({ height }: { height: number }) {
  return (
    <g transform="translate(0.52 -0.56)" aria-hidden="true">
      <circle r={0.25} fill="white" stroke="#CC4444" strokeWidth={0.04} />
      <text
        fontSize={0.3}
        fontWeight="bold"
        textAnchor="middle"
        dominantBaseline="central"
        fill="#CC4444"
      >
        {height}
      </text>
    </g>
  );
}

/** The SVG attributes that make a part of the board a button. */
function buttonProps(
  label: string,
  onActivate: () => void,
  onClick: (event: MouseEvent) => void,
) {
  return {
    role: "button",
    tabIndex: 0,
    "aria-label": label,
    className: "cursor-pointer",
    onClick,
    onKeyDown: (event: KeyboardEvent) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onActivate();
      }
    },
  };
}

/**
 * The board as an SVG: tiles with their insects, owner colours and stack heights, the
 * movable outlines, the targets and the last move.
 *
 * The view fits the board until it is panned (drag) or zoomed (pinch, mouse wheel or the
 * buttons); the fit button returns to fitting. Tapping a stack shows its contents.
 */
export function SvgBoard({
  board,
  highlights,
  movable,
  selected,
  lastMove,
  onHexClick,
}: BoardRendererProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const fitted = useMemo(() => fitViewBox(board.map((stack) => stack.coord)), [board]);
  const limits = useMemo(
    () => ({
      minWidth: MIN_VIEW_WIDTH,
      maxWidth: Math.max(fitted.width * MAX_ZOOM_OUT, MIN_VIEW_WIDTH),
    }),
    [fitted],
  );
  const [manualView, setManualView] = useState<ViewBox | null>(null);
  const [inspected, setInspected] = useState<HexCoord | null>(null);
  const view = manualView ?? fitted;
  const { handlers, consumeDrag } = useViewGestures({
    svgRef,
    view,
    limits,
    onViewChange: setManualView,
  });
  const highlightKeys = new Set(highlights.map(hexKey));
  const movableKeys = new Set(movable.map(hexKey));
  const stacks = new Map(board.map((stack) => [hexKey(stack.coord), stack]));
  const inspectedStack = inspected === null ? undefined : stacks.get(hexKey(inspected));
  const openStack =
    inspectedStack !== undefined && inspectedStack.pieces.length > 1
      ? inspectedStack
      : undefined;

  /** Report a hex, and show or hide the contents of a stack tapped for itself. */
  const activate = (coord: HexCoord) => {
    const stack = stacks.get(hexKey(coord));
    const showsStack =
      stack !== undefined && stack.pieces.length > 1 && !highlightKeys.has(hexKey(coord));
    const isOpen = openStack !== undefined && sameHex(openStack.coord, coord);
    setInspected(showsStack && !isOpen ? coord : null);
    onHexClick(coord);
  };

  const clickHex = (event: MouseEvent, coord: HexCoord) => {
    if (!consumeDrag(event)) {
      event.stopPropagation();
      activate(coord);
    }
  };

  const clickBackground = (event: MouseEvent<SVGSVGElement>) => {
    if (consumeDrag(event)) {
      return;
    }

    const point = screenToBoard(event.currentTarget, {
      x: event.clientX,
      y: event.clientY,
    });

    if (point !== null) {
      activate(pixelToAxial(point));
    }
  };

  const zoomBy = (factor: number) => {
    const focus = { x: view.x + view.width / 2, y: view.y + view.height / 2 };
    setManualView(zoomViewBox({ view, factor, focus, limits }));
  };

  const renderStack = (stack: BoardStack) => {
    const [top] = stack.pieces;

    if (top === undefined) {
      return null;
    }

    const key = hexKey(stack.coord);
    const height = stack.pieces.length;
    const label = `${describePiece(top)} at ${formatHex(stack.coord)}${
      height > 1 ? `, on a stack of ${height}` : ""
    }`;
    const interactive = movableKeys.has(key) || height > 1;

    return (
      <g
        key={key}
        transform={translate(stack.coord)}
        {...(interactive
          ? buttonProps(
              label,
              () => {
                activate(stack.coord);
              },
              (event) => {
                clickHex(event, stack.coord);
              },
            )
          : {
              role: "img",
              "aria-label": label,
              onClick: (event: MouseEvent) => {
                clickHex(event, stack.coord);
              },
            })}
      >
        <StackLayers pieces={stack.pieces} />
        <PieceTile piece={top} />
        {movableKeys.has(key) && (
          <polygon
            points={RING_POINTS}
            fill="none"
            strokeWidth={0.08}
            className="stroke-sky-500"
          />
        )}
        {height > 1 && <StackBadge height={height} />}
      </g>
    );
  };

  const renderTarget = (coord: HexCoord) => {
    const occupied = stacks.has(hexKey(coord));

    return (
      <g
        key={hexKey(coord)}
        transform={translate(coord)}
        {...buttonProps(
          `Play to ${formatHex(coord)}`,
          () => {
            activate(coord);
          },
          (event) => {
            clickHex(event, coord);
          },
        )}
      >
        {occupied ? (
          <polygon
            points={RING_POINTS}
            strokeWidth={0.12}
            className="fill-emerald-500/20 stroke-emerald-500"
          />
        ) : (
          <polygon
            points={TARGET_POINTS}
            strokeWidth={0.05}
            strokeDasharray="0.15 0.1"
            className="fill-emerald-500/15 stroke-emerald-600"
          />
        )}
        <circle r={0.16} className="fill-emerald-600" />
      </g>
    );
  };

  return (
    <Popover
      open={openStack !== undefined}
      onOpenChange={(open) => {
        if (!open) {
          setInspected(null);
        }
      }}
    >
      <div className="relative size-full overflow-hidden">
        <svg
          ref={svgRef}
          role="group"
          aria-label="Board"
          viewBox={viewBoxAttribute(view)}
          className="size-full touch-none select-none"
          onClick={clickBackground}
          {...handlers}
        >
          {lastMove?.from != null && (
            <polygon
              points={HALO_POINTS}
              transform={translate(lastMove.from)}
              className="fill-amber-400/35"
            />
          )}
          {lastMove !== null && (
            <polygon
              points={HALO_POINTS}
              transform={translate(lastMove.to)}
              className="fill-amber-400/70"
            />
          )}
          {selected !== null && (
            <polygon
              points={HALO_POINTS}
              transform={translate(selected)}
              className="fill-sky-500"
            />
          )}
          {board.map(renderStack)}
          {highlights.map(renderTarget)}
          {openStack !== undefined && (
            <PopoverAnchor asChild>
              <circle
                transform={translate(openStack.coord)}
                r={TILE_RADIUS}
                fill="none"
                pointerEvents="none"
              />
            </PopoverAnchor>
          )}
        </svg>
        <div className="absolute right-2 bottom-2 flex gap-1">
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Zoom in"
            onClick={() => {
              zoomBy(1 / ZOOM_STEP);
            }}
          >
            <ZoomInIcon />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Zoom out"
            onClick={() => {
              zoomBy(ZOOM_STEP);
            }}
          >
            <ZoomOutIcon />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Fit the board"
            disabled={manualView === null}
            onClick={() => {
              setManualView(null);
            }}
          >
            <ScanIcon />
          </Button>
        </div>
      </div>
      {openStack !== undefined && (
        <PopoverContent
          className="w-56"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
          }}
          onPointerDownOutside={(event) => {
            // Taps on the board open, switch and close stacks themselves.
            if (event.target instanceof Node && svgRef.current?.contains(event.target)) {
              event.preventDefault();
            }
          }}
        >
          <PopoverHeader>
            <PopoverTitle>Stack at {formatHex(openStack.coord)}</PopoverTitle>
          </PopoverHeader>
          <ol aria-label="Pieces from top to bottom" className="flex flex-col gap-1.5">
            {openStack.pieces.map((piece, index) => (
              <li key={index} className="flex items-center gap-2">
                <PieceIcon piece={piece} />
                <span>{describePiece(piece)}</span>
                {index === 0 && <span className="text-muted-foreground">top</span>}
              </li>
            ))}
          </ol>
        </PopoverContent>
      )}
    </Popover>
  );
}
