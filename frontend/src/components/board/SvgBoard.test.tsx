import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FADE_DURATION_MS, MOVE_DURATION_MS } from "@/components/board/motion";
import { SvgBoard } from "@/components/board/SvgBoard";
import type {
  BoardRendererProps,
  BoardTransition,
  HexCoord,
} from "@/components/board/types";

const BOARD: BoardRendererProps["board"] = [
  { coord: [0, 0], pieces: [{ piece: "queen", owner: "white" }] },
  {
    coord: [1, 0],
    pieces: [
      { piece: "beetle", owner: "white" },
      { piece: "queen", owner: "black" },
    ],
  },
  { coord: [2, -1], pieces: [{ piece: "ant", owner: "black" }] },
];

function renderBoard(props: Partial<BoardRendererProps> = {}) {
  const onHexClick = vi.fn<(coord: HexCoord) => void>();
  render(
    <SvgBoard
      board={BOARD}
      highlights={[]}
      movable={[]}
      selected={null}
      lastMove={null}
      proposedMove={null}
      onHexClick={onHexClick}
      {...props}
    />,
  );

  return { onHexClick, user: userEvent.setup() };
}

function viewBox(): string | null {
  return screen.getByRole("group", { name: "Board" }).getAttribute("viewBox");
}

describe("SvgBoard", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("draws the top piece of every stack", () => {
    renderBoard();

    expect(
      screen.getByRole("img", { name: "White queen at (0, 0)" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Black ant at (2, -1)" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "White beetle at (1, 0), on a stack of 2" }),
    ).toBeInTheDocument();
  });

  it("makes movable tiles and targets clickable", async () => {
    const { onHexClick, user } = renderBoard({
      movable: [[0, 0]],
      highlights: [[-1, 0]],
    });

    await user.click(screen.getByRole("button", { name: "White queen at (0, 0)" }));
    await user.click(screen.getByRole("button", { name: "Play to (-1, 0)" }));

    expect(onHexClick.mock.calls).toEqual([[[0, 0]], [[-1, 0]]]);
  });

  it("plays to a target with the keyboard", async () => {
    const { onHexClick, user } = renderBoard({ highlights: [[0, 1]] });

    screen.getByRole("button", { name: "Play to (0, 1)" }).focus();
    await user.keyboard("{Enter}");

    expect(onHexClick).toHaveBeenCalledExactlyOnceWith([0, 1]);
  });

  it("lists the pieces of a tapped stack, top first", async () => {
    const { onHexClick, user } = renderBoard();
    const stack = screen.getByRole("button", { name: /White beetle at \(1, 0\)/ });

    await user.click(stack);

    const pieces = within(
      screen.getByRole("list", { name: "Pieces from top to bottom" }),
    );
    expect(screen.getByText("Stack at (1, 0)")).toBeInTheDocument();
    expect(pieces.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "White beetletop",
      "Black queen",
    ]);
    expect(onHexClick).toHaveBeenCalledWith([1, 0]);

    await user.click(stack);

    expect(screen.queryByText("Stack at (1, 0)")).not.toBeInTheDocument();
  });

  it("does not open a stack that is a target", async () => {
    const { onHexClick, user } = renderBoard({ highlights: [[1, 0]] });

    await user.click(screen.getByRole("button", { name: "Play to (1, 0)" }));

    expect(onHexClick).toHaveBeenCalledExactlyOnceWith([1, 0]);
    expect(screen.queryByText("Stack at (1, 0)")).not.toBeInTheDocument();
  });

  it("zooms with the buttons and fits the board again", async () => {
    const { user } = renderBoard();
    const fitted = viewBox();
    const fit = screen.getByRole("button", { name: "Fit the board" });

    expect(fit).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    const zoomedIn = viewBox();

    expect(zoomedIn).not.toBe(fitted);
    expect(Number(zoomedIn?.split(" ")[2])).toBeLessThan(Number(fitted?.split(" ")[2]));

    await user.click(fit);

    expect(viewBox()).toBe(fitted);
  });

  it("draws a background grid", () => {
    const { container } = render(
      <SvgBoard
        board={BOARD}
        highlights={[]}
        movable={[]}
        selected={null}
        lastMove={null}
        proposedMove={null}
        onHexClick={vi.fn()}
      />,
    );

    expect(container.querySelector("path.stroke-board-grid")?.getAttribute("d")).toMatch(
      /^M.*Z$/,
    );
  });

  it("draws each mark and lists it in the key with its label", async () => {
    const { user } = renderBoard({
      movable: [[0, 0]],
      selected: [0, 0],
      highlights: [
        [-1, 0],
        [1, 0],
      ],
      lastMove: { from: [3, -1], to: [2, -1] },
      proposedMove: { from: [2, -1], to: [3, -2] },
      forbidden: [[0, 1]],
    });
    const svg = screen.getByRole("group", { name: "Board" });

    for (const kind of [
      "movable",
      "selected",
      "target",
      "climb",
      "lastMove",
      "suggestion",
      "forbidden",
    ]) {
      expect(svg.querySelector(`[data-mark="${kind}"]`)).not.toBeNull();
    }

    await user.click(screen.getByRole("button", { name: "Key" }));

    expect(
      within(screen.getByRole("list", { name: "On the board" }))
        .getAllByRole("listitem")
        .map((item) => item.querySelector(".font-medium")?.textContent),
    ).toEqual([
      "Can move",
      "Selected",
      "Can go here",
      "Can climb on top",
      "Last move",
      "Agent suggestion",
      "Not allowed",
    ]);
  });

  it("draws no marks it is not given", () => {
    renderBoard();

    expect(
      screen.getByRole("group", { name: "Board" }).querySelector("[data-mark]"),
    ).toBeNull();
  });

  it("fits the board as it grows", () => {
    const { rerender } = render(
      <SvgBoard
        board={BOARD}
        highlights={[]}
        movable={[]}
        selected={null}
        lastMove={null}
        proposedMove={null}
        onHexClick={vi.fn()}
      />,
    );
    const before = viewBox();

    rerender(
      <SvgBoard
        board={[...BOARD, { coord: [6, 0], pieces: [{ piece: "ant", owner: "white" }] }]}
        highlights={[]}
        movable={[]}
        selected={null}
        lastMove={null}
        proposedMove={null}
        onHexClick={vi.fn()}
      />,
    );

    expect(viewBox()).not.toBe(before);
  });

  it("draws a move as an arrow from a faint source hex", () => {
    renderBoard({ lastMove: { from: [3, -1], to: [2, -1] } });
    const svg = screen.getByRole("group", { name: "Board" });

    expect(svg.querySelector('[data-arrow="lastMove"]')).not.toBeNull();
    // The source hex and the arrow; the target has no halo of its own.
    expect(svg.querySelectorAll('[data-mark="lastMove"]')).toHaveLength(2);
  });

  it("highlights a placement instead of drawing an arrow", () => {
    renderBoard({
      lastMove: { from: null, to: [2, -1] },
      proposedMove: { from: null, to: [0, 1] },
    });
    const svg = screen.getByRole("group", { name: "Board" });

    expect(svg.querySelector("[data-arrow]")).toBeNull();
    expect(svg.querySelector('[data-mark="lastMove"]')).not.toBeNull();
    expect(svg.querySelector('[data-mark="suggestion"]')).not.toBeNull();
  });

  it("draws a suggested move as an arrow to a double ring", () => {
    renderBoard({ proposedMove: { from: [2, -1], to: [3, -2] } });
    const svg = screen.getByRole("group", { name: "Board" });

    expect(svg.querySelector('[data-arrow="suggestion"]')).not.toBeNull();
    // The faint source hex, the arrow and the double ring.
    expect(svg.querySelectorAll('[data-mark="suggestion"]')).toHaveLength(3);
  });

  it("lifts the selected tile", () => {
    renderBoard({ movable: [[0, 0]], selected: [0, 0] });

    expect(
      screen
        .getByRole("button", { name: "White queen at (0, 0)" })
        .querySelector("[data-lifted]"),
    ).not.toBeNull();
    expect(
      screen
        .getByRole("img", { name: "Black ant at (2, -1)" })
        .querySelector("[data-lifted]"),
    ).toBeNull();
  });

  describe("transitions", () => {
    const frames: FrameRequestCallback[] = [];
    const cancelled: number[] = [];

    beforeEach(() => {
      frames.length = 0;
      cancelled.length = 0;
      vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) =>
        frames.push(callback),
      );
      vi.stubGlobal("cancelAnimationFrame", (request: number) => {
        cancelled.push(request);
      });
    });

    const MOVE: BoardTransition = {
      key: "5:3,-1>2,-1",
      kind: "move",
      piece: { piece: "ant", owner: "black" },
      from: [3, -1],
      to: [2, -1],
    };

    function movingTile(): Element | null {
      return screen.getByRole("group", { name: "Board" }).querySelector("[data-moving]");
    }

    function runFrame(now: number) {
      const frame = frames.shift();
      frame?.(now);
    }

    it("travels the moved tile from its source and settles it on its target", () => {
      renderBoard({ transition: MOVE });
      const tile = movingTile();

      // The ant starts one hex to the right, at its source.
      expect(tile?.getAttribute("transform")).toMatch(/^translate\(1\.73\d* /);

      runFrame(0);
      runFrame(MOVE_DURATION_MS / 2);

      expect(tile?.getAttribute("transform")).toMatch(/scale\(1\.\d*[1-9]/);

      runFrame(MOVE_DURATION_MS);

      expect(tile?.hasAttribute("transform")).toBe(false);
      expect(frames).toHaveLength(0);
    });

    it("lets a new transition cancel a running one, and never replays one", () => {
      const props = {
        board: BOARD,
        highlights: [],
        movable: [],
        selected: null,
        lastMove: null,
        proposedMove: null,
        onHexClick: vi.fn(),
      };
      const { rerender } = render(<SvgBoard {...props} transition={{ ...MOVE }} />);

      // A new board with the same transition does not start again.
      rerender(<SvgBoard {...props} board={[...BOARD]} transition={{ ...MOVE }} />);

      expect(cancelled).toHaveLength(0);

      rerender(
        <SvgBoard {...props} transition={{ ...MOVE, key: "6:0,0>2,-1", from: [0, 0] }} />,
      );

      expect(cancelled).toHaveLength(1);
      expect(movingTile()?.getAttribute("transform")).toMatch(
        /^translate\(-2\.598\d* 1\.5\) /,
      );
    });

    it("puts a cancelled tile to rest when another tile moves", () => {
      const props = {
        board: BOARD,
        highlights: [],
        movable: [],
        selected: null,
        lastMove: null,
        proposedMove: null,
        onHexClick: vi.fn(),
      };
      const { rerender } = render(<SvgBoard {...props} transition={MOVE} />);
      const ant = screen.getByRole("img", { name: "Black ant at (2, -1)" });

      expect(ant.querySelector("[transform^='translate(1.73']")).not.toBeNull();

      rerender(
        <SvgBoard
          {...props}
          transition={{
            key: "6:hand>0,0",
            kind: "place",
            piece: { piece: "queen", owner: "white" },
            from: null,
            to: [0, 0],
          }}
        />,
      );

      expect(ant.querySelector("[transform^='translate(1.73']")).toBeNull();
      expect(movingTile()?.getAttribute("transform")).toMatch(/^translate\(0 -0\.35\)/);
    });

    it("cross-fades with reduced motion", () => {
      vi.stubGlobal("matchMedia", (query: string) =>
        Object.assign(new EventTarget(), {
          matches: query === "(prefers-reduced-motion: reduce)",
          media: query,
          onchange: null,
        }),
      );
      renderBoard({ transition: MOVE });
      const ghost = screen
        .getByRole("group", { name: "Board" })
        .querySelector("[data-ghost]");

      expect(movingTile()?.getAttribute("transform")).toBe("translate(0 0) scale(1)");
      expect(movingTile()?.getAttribute("opacity")).toBe("0");
      expect(ghost?.getAttribute("opacity")).toBe("1");

      runFrame(0);
      runFrame(FADE_DURATION_MS);

      expect(movingTile()?.hasAttribute("opacity")).toBe(false);
      expect(ghost?.getAttribute("opacity")).toBe("0");
    });
  });
});
