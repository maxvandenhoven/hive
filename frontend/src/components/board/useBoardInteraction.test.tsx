import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { GamePosition, Move } from "@/api/client";
import {
  resolveHexClick,
  useBoardInteraction,
} from "@/components/board/useBoardInteraction";
import { mockApi } from "@/test/api";
import { gamePosition, gameSummary } from "@/test/fixtures";
import { renderQueryHook } from "@/test/render";

const GAME_ID = gameSummary().id;
const TARGETS = `GET /api/games/${GAME_ID}/targets`;
const QUEEN_TARGETS = {
  coord: [0, 0],
  piece: "queen",
  targets: [
    [0, 1],
    [1, -1],
  ],
};

interface InteractionProps {
  position: GamePosition;
  enabled: boolean;
}

function renderInteraction({ position = gamePosition(), enabled = true } = {}) {
  const onMove = vi.fn<(move: Move) => void>();
  const view = renderQueryHook(
    (props: InteractionProps) =>
      useBoardInteraction({ gameId: GAME_ID, onMove, ...props }),
    { initialProps: { position, enabled } },
  );

  return { ...view, onMove };
}

describe("useBoardInteraction", () => {
  it("outlines the movable tiles without a selection", () => {
    const { result } = renderInteraction();

    expect(result.current.movable).toEqual([[0, 0]]);
    expect(result.current.selection).toBeNull();
    expect(result.current.highlights).toEqual([]);
  });

  it("selects a movable tile and highlights its targets", async () => {
    const requests = mockApi({ [TARGETS]: () => ({ body: QUEEN_TARGETS }) });
    const { result } = renderInteraction();

    act(() => {
      result.current.clickHex([0, 0]);
    });

    expect(result.current.selection).toEqual({
      type: "board",
      coord: [0, 0],
      piece: "queen",
    });
    await waitFor(() => {
      expect(result.current.highlights).toEqual(QUEEN_TARGETS.targets);
    });
    expect(requests.map((request) => request.search)).toEqual(["?q=0&r=0"]);
  });

  it("moves the selected tile to a target", async () => {
    mockApi({ [TARGETS]: () => ({ body: QUEEN_TARGETS }) });
    const { result, onMove } = renderInteraction();

    act(() => {
      result.current.clickHex([0, 0]);
    });
    await waitFor(() => {
      expect(result.current.highlights).toHaveLength(2);
    });
    act(() => {
      result.current.clickHex([1, -1]);
    });

    expect(onMove).toHaveBeenCalledExactlyOnceWith({
      piece: "queen",
      from: [0, 0],
      to: [1, -1],
    });
    expect(result.current.selection).toBeNull();
  });

  it("places a piece from the hand on a highlighted hex", () => {
    const { result, onMove } = renderInteraction();

    act(() => {
      result.current.clickHandPiece("ant");
    });

    expect(result.current.selection).toEqual({ type: "hand", piece: "ant" });
    expect(result.current.highlights).toEqual(gamePosition().placeable_coords);

    act(() => {
      result.current.clickHex([-1, 1]);
    });

    expect(onMove).toHaveBeenCalledExactlyOnceWith({
      piece: "ant",
      from: null,
      to: [-1, 1],
    });
  });

  it("switches and clears the selection", () => {
    mockApi({ [TARGETS]: () => ({ body: QUEEN_TARGETS }) });
    const { result, onMove } = renderInteraction();

    act(() => {
      result.current.clickHex([0, 0]);
    });
    act(() => {
      result.current.clickHandPiece("spider");
    });

    expect(result.current.selection).toEqual({ type: "hand", piece: "spider" });

    act(() => {
      result.current.clickHandPiece("spider");
    });

    expect(result.current.selection).toBeNull();

    act(() => {
      result.current.clickHex([0, 0]);
    });
    act(() => {
      result.current.clickHex([0, 0]);
    });

    expect(result.current.selection).toBeNull();

    act(() => {
      result.current.clickHandPiece("ant");
    });
    act(() => {
      result.current.clickHex([4, 4]);
    });

    expect(result.current.selection).toBeNull();
    expect(onMove).not.toHaveBeenCalled();
  });

  it("does not select pieces that cannot be played", () => {
    const { result } = renderInteraction();

    act(() => {
      result.current.clickHandPiece("queen");
    });

    expect(result.current.selection).toBeNull();

    act(() => {
      result.current.clickHex([1, 0]);
    });

    expect(result.current.selection).toBeNull();
  });

  it("ignores clicks while disabled", () => {
    const requests = mockApi({});
    const { result, onMove } = renderInteraction({ enabled: false });

    expect(result.current.movable).toEqual([]);

    act(() => {
      result.current.clickHex([0, 0]);
      result.current.clickHandPiece("ant");
    });

    expect(result.current.selection).toBeNull();
    expect(onMove).not.toHaveBeenCalled();
    expect(requests).toEqual([]);
  });

  it("drops the selection when the position changes", () => {
    const { result, rerender } = renderInteraction();

    act(() => {
      result.current.clickHandPiece("ant");
    });
    rerender({ position: gamePosition({ ply: 3, ply_count: 3 }), enabled: true });

    expect(result.current.selection).toBeNull();
    expect(result.current.highlights).toEqual([]);
  });

  it("reports targets that failed to load", async () => {
    mockApi({
      [TARGETS]: () => ({
        status: 422,
        body: { code: "piece_not_movable", detail: "The queen is pinned." },
      }),
    });
    const { result } = renderInteraction();

    act(() => {
      result.current.clickHex([0, 0]);
    });

    expect(await screen.findByText("The queen is pinned.")).toBeInTheDocument();
    expect(result.current.highlights).toEqual([]);
  });
});

describe("resolveHexClick", () => {
  it("plays to a highlighted hex rather than selecting the tile on it", () => {
    const intent = resolveHexClick(
      {
        selection: { type: "board", coord: [0, 0], piece: "beetle" },
        movablePieces: [
          { coord: [0, 0], piece: "beetle" },
          { coord: [1, 0], piece: "ant" },
        ],
        highlights: [[1, 0]],
      },
      [1, 0],
    );

    expect(intent).toEqual({
      type: "play",
      move: { piece: "beetle", from: [0, 0], to: [1, 0] },
    });
  });
});
