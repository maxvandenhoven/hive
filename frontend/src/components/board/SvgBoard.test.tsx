import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SvgBoard } from "@/components/board/SvgBoard";
import type { BoardRendererProps, HexCoord } from "@/components/board/types";

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

  it("draws each mark but movable with a suggestion, and lists it in the key", async () => {
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

    expect(svg.querySelector('[data-mark="movable"]')).toBeNull();

    for (const kind of [
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
});
