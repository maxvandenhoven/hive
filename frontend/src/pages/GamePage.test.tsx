import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { GameDetail, GamePosition } from "@/api/client";
import { GamePage } from "@/pages/GamePage";
import { mockApi } from "@/test/api";
import { gameDetail, gamePosition, moveRead } from "@/test/fixtures";
import { renderPage } from "@/test/render";

const GAME = gameDetail();
const GAME_PATH = `/api/games/${GAME.id}`;

/** The position after white placed an ant at (-1, 0), with black (an agent) to move. */
const AFTER_ANT = gamePosition({
  ply: 3,
  ply_count: 3,
  board: [
    { coord: [-1, 0], stack: [{ piece: "ant", owner: "white" }] },
    ...gamePosition().board,
  ],
  hands: {
    white: { queen: 0, beetle: 2, grasshopper: 3, spider: 2, ant: 2 },
    black: { queen: 0, beetle: 2, grasshopper: 3, spider: 2, ant: 3 },
  },
  current_player: "black",
  last_move: moveRead({ ply: 2, move: { piece: "ant", from: null, to: [-1, 0] } }),
  movable_pieces: [],
  placeable_coords: [[2, 0]],
});

interface GameApiOptions {
  game?: GameDetail;
  position?: GamePosition;
}

/** Serve a game and its position; the handlers given replace the defaults. */
function mockGameApi(
  { game = GAME, position = gamePosition() }: GameApiOptions = {},
  handlers: Parameters<typeof mockApi>[0] = {},
) {
  return mockApi({
    [`GET ${GAME_PATH}`]: () => ({ body: game }),
    [`GET ${GAME_PATH}/state`]: () => ({ body: position }),
    ...handlers,
  });
}

function renderGamePage() {
  renderPage(<GamePage />, { path: `/games/${GAME.id}`, route: "/games/:gameId" });

  return userEvent.setup();
}

describe("GamePage", () => {
  it("shows the board, the hands, the moves and whose turn it is", async () => {
    mockGameApi();
    renderGamePage();

    expect(await screen.findByRole("status")).toHaveTextContent("White to move");
    expect(screen.getByRole("heading", { name: /Evening game/ })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "White queen at (0, 0)" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Black queen at (1, 0)" }),
    ).toBeInTheDocument();
    const whiteHand = within(screen.getByRole("region", { name: "White hand" }));
    expect(
      whiteHand.getByRole("button", { name: "Place white ant, 3 left" }),
    ).toBeEnabled();
    expect(
      within(screen.getByRole("region", { name: "Black hand" })).getByRole("button", {
        name: "Place black ant, 3 left",
      }),
    ).toBeDisabled();
    const moves = within(screen.getByRole("list", { name: "Moves" }));
    expect(moves.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "1.White:Place queen at (0, 0)",
      "2.Black:Place queen at (1, 0)agent",
    ]);
  });

  it("places a piece from the hand", async () => {
    let position = gamePosition();
    const requests = mockGameApi(
      {},
      {
        [`GET ${GAME_PATH}/state`]: () => ({ body: position }),
        [`POST ${GAME_PATH}/moves`]: () => {
          position = AFTER_ANT;

          return { status: 201, body: AFTER_ANT };
        },
      },
    );
    const user = renderGamePage();

    await user.click(
      await screen.findByRole("button", { name: "Place white ant, 3 left" }),
    );
    expect(screen.getAllByRole("button", { name: /^Play to/ })).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: "Play to (-1, 0)" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Black to move · negamax (5 s)",
    );
    expect(screen.getByRole("img", { name: "White ant at (-1, 0)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Play to/ })).not.toBeInTheDocument();
    expect(requests.find((request) => request.method === "POST")?.body).toEqual({
      move: { piece: "ant", from: null, to: [-1, 0] },
      source: "manual",
      expected_ply: 2,
      allow_agent_side: false,
    });
  });

  it("moves a tile to one of its targets", async () => {
    const requests = mockGameApi(
      {},
      {
        [`GET ${GAME_PATH}/targets`]: () => ({
          body: {
            coord: [0, 0],
            piece: "queen",
            targets: [
              [0, 1],
              [1, -1],
            ],
          },
        }),
        [`POST ${GAME_PATH}/moves`]: () => ({ status: 201, body: AFTER_ANT }),
      },
    );
    const user = renderGamePage();

    await user.click(
      await screen.findByRole("button", { name: "White queen at (0, 0)" }),
    );
    await user.click(await screen.findByRole("button", { name: "Play to (1, -1)" }));

    await waitFor(() => {
      expect(requests.find((request) => request.method === "POST")?.body).toMatchObject({
        move: { piece: "queen", from: [0, 0], to: [1, -1] },
        expected_ply: 2,
      });
    });
    expect(requests.find((request) => request.path.endsWith("/targets"))?.search).toBe(
      "?q=0&r=0",
    );
  });

  it("undoes the last move", async () => {
    let position = AFTER_ANT;
    const requests = mockGameApi(
      {},
      {
        [`GET ${GAME_PATH}/state`]: () => ({ body: position }),
        [`DELETE ${GAME_PATH}/moves/last`]: () => {
          position = gamePosition();

          return { body: position };
        },
      },
    );
    const user = renderGamePage();

    await user.click(await screen.findByRole("button", { name: "Undo" }));

    expect(await screen.findByText("Undid the last move.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("White to move");
    expect(requests.find((request) => request.method === "DELETE")?.search).toBe(
      "?expected_ply=3",
    );
  });

  it("reports a move that another one beat and shows the game as it is", async () => {
    let position = gamePosition();
    mockGameApi(
      {},
      {
        [`GET ${GAME_PATH}/state`]: () => ({ body: position }),
        [`POST ${GAME_PATH}/moves`]: () => {
          position = AFTER_ANT;

          return {
            status: 409,
            body: { code: "ply_conflict", detail: "The game is at ply 3, not 2." },
          };
        },
      },
    );
    const user = renderGamePage();

    await user.click(
      await screen.findByRole("button", { name: "Place white spider, 2 left" }),
    );
    await user.click(screen.getByRole("button", { name: "Play to (0, -1)" }));

    expect(await screen.findByText("The game is at ply 3, not 2.")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Black to move");
    });
  });

  it("does not let a person play the side of an agent", async () => {
    mockGameApi({ position: AFTER_ANT });
    const user = renderGamePage();

    await screen.findByRole("status");
    await user.click(screen.getByRole("img", { name: "Black queen at (1, 0)" }));

    expect(screen.queryByRole("button", { name: /^Play to/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /queen at/ })).not.toBeInTheDocument();
    for (const button of within(
      screen.getByRole("region", { name: "Black hand" }),
    ).getAllByRole("button")) {
      expect(button).toBeDisabled();
    }
  });

  it("passes when no move is legal", async () => {
    const requests = mockGameApi(
      {
        position: gamePosition({
          movable_pieces: [],
          placeable_coords: [],
          placeable_piece_types: [],
          must_pass: true,
        }),
      },
      { [`POST ${GAME_PATH}/moves`]: () => ({ status: 201, body: AFTER_ANT }) },
    );
    const user = renderGamePage();

    await user.click(await screen.findByRole("button", { name: "Pass" }));

    await waitFor(() => {
      expect(requests.find((request) => request.method === "POST")?.body).toMatchObject({
        move: null,
        expected_ply: 2,
      });
    });
  });

  it("shows the result of a finished game", async () => {
    mockGameApi({
      game: gameDetail({ status: "finished", result: "white" }),
      position: gamePosition({
        result: "white",
        movable_pieces: [],
        placeable_coords: [],
        placeable_piece_types: [],
      }),
    });
    renderGamePage();

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("White won");
    expect(banner).toHaveTextContent("The game ended after 2 moves.");
    expect(screen.getByRole("button", { name: "Undo" })).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Place white ant, 3 left" }),
    ).toBeDisabled();
  });

  it("shows an empty game", async () => {
    mockGameApi({
      game: gameDetail({ ply_count: 0, moves: [] }),
      position: gamePosition({
        ply: 0,
        ply_count: 0,
        board: [],
        last_move: null,
        movable_pieces: [],
        placeable_coords: [[0, 0]],
        placeable_piece_types: ["queen", "beetle", "grasshopper", "spider", "ant"],
        hands: {
          white: { queen: 1, beetle: 2, grasshopper: 3, spider: 2, ant: 3 },
          black: { queen: 1, beetle: 2, grasshopper: 3, spider: 2, ant: 3 },
        },
      }),
    });
    renderGamePage();

    expect(await screen.findByText("No moves yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Place white queen, 1 left" }),
    ).toBeEnabled();
  });

  it("reports a game that does not exist", async () => {
    mockApi({
      [`GET ${GAME_PATH}`]: () => ({
        status: 404,
        body: { code: "game_not_found", detail: "Game not found." },
      }),
      [`GET ${GAME_PATH}/state`]: () => ({
        status: 404,
        body: { code: "game_not_found", detail: "Game not found." },
      }),
    });
    renderGamePage();

    expect(
      await screen.findByText("Could not load the game: Game not found."),
    ).toBeInTheDocument();
  });
});
