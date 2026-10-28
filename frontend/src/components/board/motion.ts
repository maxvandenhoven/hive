/*
 * How the SVG board animates a transition: a pure frame function of the progress, and a
 * hook that plays it on the elements of the moved tile with `requestAnimationFrame`.
 * A new transition cancels a running one, and nothing waits for an animation to end.
 */
import { useLayoutEffect, useRef, useSyncExternalStore, type RefObject } from "react";

import { pointOnArc, type MoveArc } from "@/components/board/arrows";
import type { BoardTransition, BoardTransitionKind } from "@/components/board/types";

/** How long a placement drops, a move travels and a reduced motion cross-fade takes. */
export const PLACE_DURATION_MS = 300;
export const MOVE_DURATION_MS = 450;
export const FADE_DURATION_MS = 200;

/** How far above its hex and how much larger a placed tile starts. */
const DROP_HEIGHT = 0.35;
const DROP_SCALE = 0.2;

/** How much larger a moving tile gets at the top of its lift. */
const LIFT_SCALE = 0.1;

/** Where the shadow of a tile on the board falls, and how far it spreads when raised. */
const SHADOW_OFFSET = { x: 0.06, y: 0.1 };
const SHADOW_SPREAD = 3;
const SHADOW_OPACITY = 0.3;

/** How the moved tile, its shadow and the tile left at the source look at one moment. */
export interface TransitionFrame {
  /** The offset of the tile from the centre of its target. */
  x: number;
  y: number;
  scale: number;
  opacity: number;
  /** The offset, scale and opacity of the shadow under the tile. */
  shadowX: number;
  shadowY: number;
  shadowScale: number;
  shadowOpacity: number;
  /** The opacity of the tile fading out at the source, for reduced motion. */
  ghostOpacity: number;
}

/** The frame at rest: the tile on its target, without a shadow or a ghost. */
export const RESTING_FRAME: TransitionFrame = {
  x: 0,
  y: 0,
  scale: 1,
  opacity: 1,
  shadowX: 0,
  shadowY: 0,
  shadowScale: 1,
  shadowOpacity: 0,
  ghostOpacity: 0,
};

function easeOutCubic(progress: number): number {
  return 1 - (1 - progress) ** 3;
}

function easeInOutCubic(progress: number): number {
  return progress < 0.5 ? 4 * progress ** 3 : 1 - (-2 * progress + 2) ** 3 / 2;
}

/** How long a transition of this kind takes. */
export function transitionDuration(
  kind: BoardTransitionKind,
  reducedMotion: boolean,
): number {
  if (reducedMotion) {
    return FADE_DURATION_MS;
  }

  return kind === "place" ? PLACE_DURATION_MS : MOVE_DURATION_MS;
}

/** The shadow of a tile raised by `lift` (0 on the board, 1 at the highest). */
function shadowAt(lift: number) {
  const spread = 1 + SHADOW_SPREAD * lift;

  return {
    shadowX: SHADOW_OFFSET.x * spread,
    shadowY: SHADOW_OFFSET.y * spread,
    shadowScale: 1 + 0.1 * lift,
    shadowOpacity: lift === 0 ? 0 : SHADOW_OPACITY * (0.6 + 0.4 * (1 - lift)),
  };
}

/**
 * The frame of a transition at `progress` (0 to 1).
 *
 * A placement drops from slightly above, larger and with a soft shadow, and eases out
 * onto its hex. A move or climb lifts, travels along `arc` and settles. With reduced
 * motion the tile fades in on its target while a ghost fades out at the source.
 */
export function transitionFrame({
  kind,
  arc,
  progress,
  reducedMotion,
}: {
  kind: BoardTransitionKind;
  /** The arc of a move or climb; placements have none. */
  arc: MoveArc | null;
  progress: number;
  reducedMotion: boolean;
}): TransitionFrame {
  const clamped = Math.min(Math.max(progress, 0), 1);

  if (reducedMotion) {
    return {
      ...RESTING_FRAME,
      opacity: clamped,
      ghostOpacity: kind === "place" ? 0 : 1 - clamped,
    };
  }

  if (kind === "place" || arc === null) {
    const height = 1 - easeOutCubic(clamped);

    return {
      ...RESTING_FRAME,
      ...shadowAt(height),
      y: -DROP_HEIGHT * height,
      scale: 1 + DROP_SCALE * height,
      opacity: Math.min(1, clamped / 0.3),
    };
  }

  const travelled = pointOnArc(arc, easeInOutCubic(clamped));
  const lift = Math.sin(Math.PI * clamped);

  return {
    ...RESTING_FRAME,
    ...shadowAt(lift),
    x: travelled.x - arc.to.x,
    y: travelled.y - arc.to.y,
    scale: 1 + LIFT_SCALE * lift,
  };
}

/** Whether the person asked the system for less motion. */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const query = window.matchMedia("(prefers-reduced-motion: reduce)");
      query.addEventListener("change", onChange);

      return () => {
        query.removeEventListener("change", onChange);
      };
    },
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
}

/** The elements a transition animates; any of them may be missing. */
export interface TransitionElements {
  /** The group of the moved tile on its target. */
  tile: RefObject<SVGGElement | null>;
  /** The shadow under the moved tile, inside `tile`'s parent. */
  shadow: RefObject<SVGElement | null>;
  /** The tile drawn at the source for the reduced motion cross-fade. */
  ghost: RefObject<SVGGElement | null>;
}

/** The elements of one transition, resolved from their refs when it starts. */
interface TransitionNodes {
  tile: SVGGElement | null;
  shadow: SVGElement | null;
  ghost: SVGGElement | null;
}

function applyFrame({ tile, shadow, ghost }: TransitionNodes, frame: TransitionFrame) {
  if (frame === RESTING_FRAME) {
    tile?.removeAttribute("transform");
    tile?.removeAttribute("opacity");
  } else {
    tile?.setAttribute(
      "transform",
      `translate(${frame.x} ${frame.y}) scale(${frame.scale})`,
    );
    tile?.setAttribute("opacity", String(frame.opacity));
  }

  const shadowX = frame.x + frame.shadowX;
  const shadowY = frame.y + frame.shadowY;
  shadow?.setAttribute(
    "transform",
    `translate(${shadowX} ${shadowY}) scale(${frame.shadowScale})`,
  );
  shadow?.setAttribute("opacity", String(frame.shadowOpacity));
  ghost?.setAttribute("opacity", String(frame.ghostOpacity));
}

/**
 * Plays `transition` on `elements`, frame by frame, from when its key first shows up.
 *
 * Only the key starts an animation, so a new board or arc for the same transition does
 * not replay it. A new key, or unmounting, cancels a running animation and leaves the
 * elements at rest.
 */
export function useTransitionAnimation({
  transition,
  arc,
  reducedMotion,
  elements,
}: {
  transition: BoardTransition | null;
  arc: MoveArc | null;
  reducedMotion: boolean;
  elements: TransitionElements;
}): void {
  const latest = useRef({ transition, arc, reducedMotion, elements });
  const key = transition?.key ?? null;

  useLayoutEffect(() => {
    latest.current = { transition, arc, reducedMotion, elements };
  });

  useLayoutEffect(() => {
    const { transition: current, arc: path, reducedMotion: reduced } = latest.current;
    const { elements: refs } = latest.current;
    // Held from the start, since the refs move on to the next transition's elements
    // before this one is cancelled and must be put to rest.
    const targets: TransitionNodes = {
      tile: refs.tile.current,
      shadow: refs.shadow.current,
      ghost: refs.ghost.current,
    };

    if (key === null || current === null) {
      return;
    }

    const duration = transitionDuration(current.kind, reduced);
    const frameAt = (progress: number) =>
      transitionFrame({
        kind: current.kind,
        arc: path,
        progress,
        reducedMotion: reduced,
      });
    let started: number | null = null;
    let request = 0;

    const step = (now: number) => {
      started ??= now;
      const progress = (now - started) / duration;

      if (progress >= 1) {
        applyFrame(targets, RESTING_FRAME);

        return;
      }

      applyFrame(targets, frameAt(progress));
      request = requestAnimationFrame(step);
    };

    applyFrame(targets, frameAt(0));
    request = requestAnimationFrame(step);

    return () => {
      cancelAnimationFrame(request);
      applyFrame(targets, RESTING_FRAME);
    };
  }, [key]);
}
