import {
  useEffect,
  useRef,
  type MouseEvent,
  type PointerEvent,
  type RefObject,
} from "react";

import type { PixelPoint } from "@/components/board/hex";
import {
  panViewBox,
  zoomViewBox,
  type ViewBox,
  type ViewBoxLimits,
} from "@/components/board/viewBox";

/** How far a pointer moves before a press becomes a drag rather than a click. */
const DRAG_THRESHOLD_PX = 6;

/** How fast the mouse wheel zooms, per pixel of scrolling. */
const WHEEL_ZOOM_RATE = 0.002;

/** The pointers and view when a gesture started, which every move is measured from. */
interface GestureStart {
  view: ViewBox;
  points: PixelPoint[];
  /** Turns screen points into board points, as the view was at the start. */
  toBoard: DOMMatrix;
}

function transform(matrix: DOMMatrix, { x, y }: PixelPoint): PixelPoint {
  const point = new DOMPoint(x, y).matrixTransform(matrix);

  return { x: point.x, y: point.y };
}

function midpoint(a: PixelPoint, b: PixelPoint): PixelPoint {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

function distance(a: PixelPoint, b: PixelPoint): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** The board point under a screen point, or `null` before the SVG is laid out. */
export function screenToBoard(svg: SVGSVGElement, point: PixelPoint): PixelPoint | null {
  const matrix = svg.getScreenCTM();

  return matrix === null ? null : transform(matrix.inverse(), point);
}

interface ViewGesturesOptions {
  svgRef: RefObject<SVGSVGElement | null>;
  view: ViewBox;
  limits: ViewBoxLimits;
  onViewChange: (view: ViewBox) => void;
}

/**
 * Pan with one pointer, pinch to zoom with two and zoom with the mouse wheel.
 *
 * Returns the pointer handlers for the SVG and `consumeDrag`, which tells a click
 * handler whether the click ended a drag and should be ignored.
 */
export function useViewGestures({
  svgRef,
  view,
  limits,
  onViewChange,
}: ViewGesturesOptions) {
  const pointers = useRef(new Map<number, PixelPoint>());
  const start = useRef<GestureStart | null>(null);
  const dragged = useRef(false);

  // The wheel listener is not passive, so it can keep the page from scrolling.
  useEffect(() => {
    const svg = svgRef.current;

    if (svg === null) {
      return;
    }

    const zoom = (event: WheelEvent) => {
      const focus = screenToBoard(svg, { x: event.clientX, y: event.clientY });

      if (focus === null) {
        return;
      }

      event.preventDefault();
      const factor = Math.exp(event.deltaY * WHEEL_ZOOM_RATE);
      onViewChange(zoomViewBox({ view, factor, focus, limits }));
    };

    svg.addEventListener("wheel", zoom, { passive: false });

    return () => {
      svg.removeEventListener("wheel", zoom);
    };
  }, [svgRef, view, limits, onViewChange]);

  /** Measure the gesture from here, whenever a pointer is added or lifted. */
  const restart = () => {
    const matrix = svgRef.current?.getScreenCTM() ?? null;
    start.current =
      matrix === null || pointers.current.size === 0
        ? null
        : { view, points: [...pointers.current.values()], toBoard: matrix.inverse() };
  };

  const onPointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) {
      return;
    }

    if (pointers.current.size === 0) {
      dragged.current = false;
    }

    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    restart();
  };

  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const gesture = start.current;

    if (gesture === null || !pointers.current.has(event.pointerId)) {
      return;
    }

    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const points = [...pointers.current.values()];
    const [first, second] = points;
    const [startFirst, startSecond] = gesture.points;

    if (first === undefined || startFirst === undefined) {
      return;
    }

    if (
      !dragged.current &&
      distance(first, startFirst) < DRAG_THRESHOLD_PX &&
      second === undefined
    ) {
      return;
    }

    dragged.current = true;
    // Keep receiving the pointer when it leaves the board; the click then ends on the
    // SVG rather than on a tile.
    event.currentTarget.setPointerCapture(event.pointerId);

    if (second === undefined || startSecond === undefined) {
      const from = transform(gesture.toBoard, startFirst);
      const to = transform(gesture.toBoard, first);
      onViewChange(panViewBox(gesture.view, { x: from.x - to.x, y: from.y - to.y }));

      return;
    }

    const startCentre = transform(gesture.toBoard, midpoint(startFirst, startSecond));
    const centre = transform(gesture.toBoard, midpoint(first, second));
    const factor =
      distance(startFirst, startSecond) / Math.max(distance(first, second), 1);
    const zoomed = zoomViewBox({
      view: gesture.view,
      factor,
      focus: startCentre,
      limits,
    });
    const scale = zoomed.width / gesture.view.width;
    onViewChange(
      panViewBox(zoomed, {
        x: (startCentre.x - centre.x) * scale,
        y: (startCentre.y - centre.y) * scale,
      }),
    );
  };

  const onPointerEnd = (event: PointerEvent<SVGSVGElement>) => {
    pointers.current.delete(event.pointerId);
    restart();
  };

  /** Whether a click ended a drag, which then is not a click; forgets the drag. */
  const consumeDrag = (event: MouseEvent) => {
    const wasDrag = dragged.current;
    dragged.current = false;

    if (wasDrag) {
      event.stopPropagation();
    }

    return wasDrag;
  };

  return {
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp: onPointerEnd,
      onPointerCancel: onPointerEnd,
    },
    consumeDrag,
  };
}
