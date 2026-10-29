import { ScanIcon, ZoomInIcon, ZoomOutIcon } from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type RefObject,
} from "react";

import type { Piece } from "@/api/client";
import { BoardLegend } from "@/components/board/BoardLegend";
import { boardMarksShown } from "@/components/board/boardMarks";
import { TILE_FILL_CLASSES } from "@/components/board/colors";
import { gridCells, gridPath } from "@/components/board/grid";
import {
  axialToPixel,
  formatHex,
  hexKey,
  roundedHexPath,
  pixelToAxial,
  sameHex,
} from "@/components/board/hex";
import {
  ForbiddenMark,
  LastMoveMark,
  MovableRing,
  MovableShadow,
  SelectedOutline,
  SuggestionMark,
  TargetMark,
} from "@/components/board/marks";
import { PieceIcon, PieceTile, TILE_RADIUS } from "@/components/board/PieceTile";
import type { BoardRendererProps, BoardStack, HexCoord } from "@/components/board/types";
import { screenToBoard, useViewGestures } from "@/components/board/useViewGestures";
import {
  fitViewBox,
  viewBoxAttribute,
  visibleViewBox,
  zoomViewBox,
  type ScreenSize,
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
import { cn } from "@/lib/utils";

/** The narrowest view, about two hexes across. */
const MIN_VIEW_WIDTH = 4;

/** How far the view may zoom out, relative to the fitted view. */
const MAX_ZOOM_OUT = 3;

/** How much one press of a zoom button zooms. */
const ZOOM_STEP = 1.25;

/** How far each piece below the top one peeks out of a stack. */
const STACK_OFFSET = 0.08;

const TILE_PATH = roundedHexPath(TILE_RADIUS);

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
      <path
        key={depth}
        d={TILE_PATH}
        transform={`translate(${depth * STACK_OFFSET} ${depth * STACK_OFFSET})`}
        strokeWidth={0.04}
        className={cn(TILE_FILL_CLASSES[piece.owner], "stroke-tile-stroke")}
      />
    ));
}

/** A keyboard focus mark whose stroke stays small at every board zoom. */
function BoardFocusRing() {
  return (
    <path
      d={TILE_PATH}
      fill="none"
      strokeWidth={2}
      vectorEffect="non-scaling-stroke"
      pointerEvents="none"
      className="hidden stroke-ring group-focus-visible/board-button:block"
    />
  );
}

function StackBadge({ height }: { height: number }) {
  return (
    <g transform="translate(0.52 -0.56)" aria-hidden="true">
      <circle r={0.25} strokeWidth={0.04} className="fill-card stroke-foreground" />
      <text
        fontSize={0.3}
        fontWeight="bold"
        textAnchor="middle"
        dominantBaseline="central"
        className="fill-foreground"
      >
        {height}
      </text>
    </g>
  );
}

/** The size of the SVG on the screen, or `null` before it is laid out. */
function useScreenSize(ref: RefObject<SVGSVGElement | null>): ScreenSize | null {
  const [size, setSize] = useState<ScreenSize | null>(null);

  useEffect(() => {
    const element = ref.current;

    if (element === null) {
      return;
    }

    const observer = new ResizeObserver(([entry]) => {
      if (entry !== undefined) {
        const { width, height } = entry.contentRect;
        setSize({ width, height });
      }
    });
    observer.observe(element);

    return () => {
      observer.disconnect();
    };
  }, [ref]);

  return size;
}

/** How close in pixels a mouse pointer comes to the stack contents before they fade out. */
const STACK_POPUP_FADE_MARGIN = 24;

/**
 * Whether a mouse pointer is near the element, so a popup over the board can fade out
 * and let clicks through to the tiles below it while it stays open.
 */
function usePointerNear(ref: RefObject<HTMLElement | null>, active: boolean): boolean {
  const [near, setNear] = useState(false);

  useEffect(() => {
    if (!active) {
      return;
    }

    const move = (event: PointerEvent) => {
      const element = ref.current;

      if (element === null || event.pointerType !== "mouse") {
        return;
      }

      const rect = element.getBoundingClientRect();
      setNear(
        event.clientX > rect.left - STACK_POPUP_FADE_MARGIN &&
          event.clientX < rect.right + STACK_POPUP_FADE_MARGIN &&
          event.clientY > rect.top - STACK_POPUP_FADE_MARGIN &&
          event.clientY < rect.bottom + STACK_POPUP_FADE_MARGIN,
      );
    };
    window.addEventListener("pointermove", move);

    return () => {
      window.removeEventListener("pointermove", move);
    };
  }, [ref, active]);

  return active && near;
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
    className: "group/board-button cursor-pointer outline-none",
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
 * The board as an SVG on a background hex grid: tiles with their insects, owner colours
 * and stack heights, and the marks (movable, selected, targets, last move, an agent's
 * suggestion, forbidden), which the Key button explains.
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
  proposedMove,
  forbidden = [],
  onHexClick,
}: BoardRendererProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const stackPopupRef = useRef<HTMLDivElement>(null);
  const screenSize = useScreenSize(svgRef);
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
  const grid = useMemo(() => {
    const visible = screenSize === null ? view : visibleViewBox(view, screenSize);

    return gridPath(gridCells(visible));
  }, [view, screenSize]);
  const shownMarks = boardMarksShown({
    board,
    highlights,
    movable,
    selected,
    lastMove,
    proposedMove,
    forbidden,
  });
  const highlightKeys = new Set(highlights.map(hexKey));
  const movableKeys = new Set(movable.map(hexKey));
  // A suggested move hides the movable marks, so its rings are the only ones shown.
  const marksMovable = proposedMove === null;
  const stacks = new Map(board.map((stack) => [hexKey(stack.coord), stack]));
  const inspectedStack = inspected === null ? undefined : stacks.get(hexKey(inspected));
  const openStack =
    inspectedStack !== undefined && inspectedStack.pieces.length > 1
      ? inspectedStack
      : undefined;
  const stackPopupFaded = usePointerNear(stackPopupRef, openStack !== undefined);

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
        {marksMovable && movableKeys.has(key) && <MovableShadow />}
        <StackLayers pieces={stack.pieces} />
        <PieceTile piece={top} />
        {marksMovable && movableKeys.has(key) && <MovableRing />}
        {height > 1 && <StackBadge height={height} />}
        {interactive && <BoardFocusRing />}
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
        <TargetMark occupied={occupied} />
        <BoardFocusRing />
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
          <path
            d={grid}
            fill="none"
            strokeWidth={1.25}
            vectorEffect="non-scaling-stroke"
            pointerEvents="none"
            className="stroke-board-grid"
          />
          {lastMove?.from != null && (
            <g transform={translate(lastMove.from)}>
              <LastMoveMark part="from" />
            </g>
          )}
          {lastMove !== null && (
            <g transform={translate(lastMove.to)}>
              <LastMoveMark part="to" />
            </g>
          )}
          {selected !== null && (
            <g transform={translate(selected)}>
              <SelectedOutline />
            </g>
          )}
          {board.map(renderStack)}
          {highlights.map(renderTarget)}
          {forbidden.map((coord) => (
            <g key={hexKey(coord)} transform={translate(coord)}>
              <ForbiddenMark />
            </g>
          ))}
          {proposedMove !== null && (
            <SuggestionMark
              from={proposedMove.from === null ? null : axialToPixel(proposedMove.from)}
              to={axialToPixel(proposedMove.to)}
            />
          )}
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
        <BoardLegend shown={shownMarks} className="absolute top-2 bottom-2 left-2" />
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
          ref={stackPopupRef}
          className={cn(
            "w-56 transition-opacity",
            stackPopupFaded && "pointer-events-none opacity-0",
          )}
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
