import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { DecisionRecord, GameDetail, GamePosition, Move } from "@/api/client";
import { GamePage } from "@/pages/GamePage";
import {
  controlledEventStream,
  mockApi,
  type RecordedRequest,
  serverSentEvents,
} from "@/test/api";
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

/** The move black's agent answers `AFTER_ANT` with. */
const AGENT_MOVE: Move = { piece: "spider", from: null, to: [2, 0] };

/** The position after the agent's answer, with white to move at ply 4. */
const AFTER_AGENT = gamePosition({
  ply: 4,
  ply_count: 4,
  board: [
    ...AFTER_ANT.board,
    { coord: [2, 0], stack: [{ piece: "spider", owner: "black" }] },
  ],
  hands: {
    white: { queen: 0, beetle: 2, grasshopper: 3, spider: 2, ant: 2 },
    black: { queen: 0, beetle: 2, grasshopper: 3, spider: 1, ant: 3 },
  },
  last_move: moveRead({ ply: 3, move: AGENT_MOVE, source: "agent" }),
});

/** `AFTER_AGENT` in a table game, before the person confirmed making the move. */
const PENDING_AGENT: GamePosition = {
  ...AFTER_AGENT,
  last_move: moveRead({ ply: 3, move: AGENT_MOVE, source: "agent", pending: true }),
  pending_move: true,
};

/** A hints game: both sides are people with nm3 as hint agent. */
const HINTS_GAME = gameDetail({
  white: {
    type: "human",
    hint: { spec: { kind: "negamax", params: {}, label: "nm3" }, budget_s: 5 },
  },
  black: {
    type: "human",
    hint: { spec: { kind: "negamax", params: {}, label: "nm3" }, budget_s: 5 },
  },
});

/** The move the hint agent suggests for white in `gamePosition()`. */
const HINT_MOVE: Move = { piece: "ant", from: null, to: [-1, 0] };

function thinkResponse(events: unknown[]): Response {
  return new Response(serverSentEvents(events), {
    headers: { "Content-Type": "text/event-stream" },
  });
}

function findPrompt(): Promise<HTMLElement> {
  return screen.findByRole("region", { name: "Turn prompt" });
}

function decisionRecord(move: Move = AGENT_MOVE): DecisionRecord {
  return {
    ply: 3,
    player: "black",
    agent_label: "negamax",
    seed: 1,
    budget_s: 5,
    elapsed_s: 1.2,
    overrun_s: 0,
    close_reason: "final",
    candidates: 2,
    illegal_submissions: 0,
    move,
    worker_restarted: false,
  };
}

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
    // Agents think until the page closes the stream.
    [`POST ${GAME_PATH}/think`]: ({ signal }) => controlledEventStream(signal).response,
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
    expect(
      screen.queryByRole("button", { name: /^(White|Black) queen at/ }),
    ).not.toBeInTheDocument();
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

  it("shows the result of a finished game with undo and a new game", async () => {
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

    const prompt = within(await findPrompt());
    expect(prompt.getByText("You won after 2 moves")).toBeInTheDocument();
    expect(prompt.getByRole("button", { name: "New game" })).toBeInTheDocument();
    // Undo is offered once, in the prompt.
    expect(screen.getByRole("button", { name: "Undo" })).toBeEnabled();
    expect(prompt.getByRole("button", { name: "Undo" })).toBeEnabled();
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

  it("lets the agent think and waits until its move is made on the table", async () => {
    let position = AFTER_ANT;
    const requests = mockGameApi(
      {},
      {
        [`GET ${GAME_PATH}/state`]: () => ({ body: position }),
        [`POST ${GAME_PATH}/think`]: () => {
          position = PENDING_AGENT;

          return thinkResponse([
            { type: "info", info: { depth: 2, score: 1.5, nps: 12000 } },
            { type: "candidate", move: AGENT_MOVE, final: true },
            { type: "decision", decision: decisionRecord(), position: PENDING_AGENT },
          ]);
        },
        [`POST ${GAME_PATH}/moves/last/confirm`]: () => {
          position = AFTER_AGENT;

          return { body: AFTER_AGENT };
        },
      },
    );
    const user = renderGamePage();

    const prompt = await findPrompt();
    expect(
      await within(prompt).findByText(
        "Make this move on the table: place spider next to the black queen",
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("img", { name: "Black spider at (2, 0)" }),
    ).toBeInTheDocument();
    expect(document.querySelector('[data-mark="suggestion"]')).not.toBeNull();
    // The person plays only once the move is made on the table.
    expect(
      screen.getByRole("button", { name: "Place white ant, 2 left" }),
    ).toBeDisabled();
    expect(requests.find((request) => request.path.endsWith("/think"))?.body).toEqual({
      commit: true,
    });

    await user.click(within(prompt).getByRole("button", { name: "Done" }));

    expect(
      await within(prompt).findByText(
        "Your turn: make your move on the table, then enter it here",
      ),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Place white ant, 2 left" })).toBeEnabled();
    expect(requests.find((request) => request.path.endsWith("/confirm"))?.body).toEqual({
      expected_ply: 4,
    });
  });

  it("asks for the pending move again after a reload", async () => {
    const requests = mockGameApi(
      { game: gameDetail({ ply_count: 4 }), position: PENDING_AGENT },
      { [`POST ${GAME_PATH}/moves/last/confirm`]: () => ({ body: AFTER_AGENT }) },
    );
    const user = renderGamePage();

    const prompt = await findPrompt();
    expect(prompt).toHaveTextContent(
      "Make this move on the table: place spider next to the black queen",
    );
    expect(document.querySelector('[data-mark="suggestion"]')).not.toBeNull();

    await user.click(within(prompt).getByRole("button", { name: "Done" }));

    expect(
      await within(prompt).findByText(
        "Your turn: make your move on the table, then enter it here",
      ),
    ).toBeVisible();
    expect(requests.some((request) => request.path.endsWith("/think"))).toBe(false);
  });

  it("applies agent moves on the screen without Done", async () => {
    let position = AFTER_ANT;
    const requests = mockGameApi(
      { game: gameDetail({ board_location: "screen" }) },
      {
        [`GET ${GAME_PATH}/state`]: () => ({ body: position }),
        [`POST ${GAME_PATH}/think`]: () => {
          position = AFTER_AGENT;

          return thinkResponse([
            { type: "decision", decision: decisionRecord(), position: AFTER_AGENT },
          ]);
        },
      },
    );
    renderGamePage();

    const prompt = await findPrompt();
    expect(
      await within(prompt).findByText(
        "Your turn: tap a piece on the board or in your hand",
      ),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Done" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Place white ant, 2 left" })).toBeEnabled();
    expect(requests.some((request) => request.path.endsWith("/confirm"))).toBe(false);
  });

  it("offers to try again when the agent could not think", async () => {
    let attempts = 0;
    mockGameApi(
      { position: AFTER_ANT },
      {
        [`POST ${GAME_PATH}/think`]: () => {
          attempts++;

          return {
            status: 503,
            body: { code: "pool_busy", detail: "Every agent is busy." },
          };
        },
      },
    );
    const user = renderGamePage();

    const panel = await screen.findByRole("region", { name: "Agent thinking" });
    await user.click(await within(panel).findByRole("button", { name: "Try again" }));

    await waitFor(() => {
      expect(attempts).toBe(2);
    });
  });

  it("takes back a pending agent move together with the person's move", async () => {
    let position = PENDING_AGENT;
    const requests = mockGameApi(
      { game: gameDetail({ ply_count: 4 }) },
      {
        [`GET ${GAME_PATH}/state`]: () => ({ body: position }),
        [`DELETE ${GAME_PATH}/moves/last`]: ({ search }) => {
          position = search === "?expected_ply=4" ? AFTER_ANT : gamePosition();

          return { body: position };
        },
      },
    );
    const user = renderGamePage();

    await user.click(await screen.findByRole("button", { name: "Undo" }));

    expect(await screen.findByText("Undid the last 2 moves.")).toBeInTheDocument();
    expect(
      requests.filter((request) => request.method === "DELETE").map((r) => r.search),
    ).toEqual(["?expected_ply=4", "?expected_ply=3"]);
    expect(screen.getByRole("status")).toHaveTextContent("White to move");
  });

  it("replays earlier positions and returns to the live one", async () => {
    const requests = mockGameApi(
      {},
      {
        [`GET ${GAME_PATH}/state`]: ({ search }) => ({
          body:
            search === "?ply=1"
              ? gamePosition({
                  ply: 1,
                  board: gamePosition().board.slice(0, 1),
                  current_player: "black",
                })
              : gamePosition(),
        }),
      },
    );
    const user = renderGamePage();

    await user.click(await screen.findByRole("button", { name: "Previous position" }));

    expect(await screen.findByText("Replay · ply 1")).toBeInTheDocument();
    expect(
      screen.queryByRole("img", { name: "Black queen at (1, 0)" }),
    ).not.toBeInTheDocument();
    expect(requests.map((request) => request.search)).toContain("?ply=1");
    // Replayed positions cannot be played.
    expect(
      screen.getByRole("button", { name: "Place white ant, 3 left" }),
    ).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Live position" }));

    expect(screen.queryByText("Replay · ply 1")).not.toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Black queen at (1, 0)" }),
    ).toBeInTheDocument();

    await user.click(
      within(screen.getByRole("list", { name: "Moves" })).getByRole("button", {
        name: /Place queen at \(0, 0\)/,
      }),
    );

    expect(await screen.findByText("Replay · ply 1")).toBeInTheDocument();
  });

  it("plays an agent vs agent match until paused", async () => {
    const match = gameDetail({
      white: { type: "agent", spec: { kind: "random", params: {} }, budget_s: 1 },
    });
    const streams: ReturnType<typeof controlledEventStream>[] = [];
    mockGameApi(
      { game: match, position: AFTER_ANT },
      {
        [`POST ${GAME_PATH}/think`]: ({ signal }) => {
          const stream = controlledEventStream(signal);
          streams.push(stream);

          return stream.response;
        },
      },
    );
    const user = renderGamePage();

    await user.click(await screen.findByRole("button", { name: "Play" }));
    await waitFor(() => {
      expect(streams).toHaveLength(1);
    });
    expect(await screen.findByText("Black is thinking")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Pause" }));

    expect(screen.queryByText("Black is thinking")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Step" })).toBeEnabled();
  });

  it("watches a match with the match controls in the prompt", async () => {
    const match = gameDetail({
      white: { type: "agent", spec: { kind: "random", params: {} }, budget_s: 1 },
    });
    mockGameApi({ game: match, position: AFTER_ANT });
    renderGamePage();

    const prompt = within(await findPrompt());
    expect(prompt.getByText("Watching random vs negamax")).toBeInTheDocument();
    expect(prompt.getByRole("button", { name: "Play" })).toBeInTheDocument();
  });

  it("puts the person's side at the bottom against an agent", async () => {
    const handOrder = () =>
      screen
        .getAllByRole("region", { name: /hand$/ })
        .map((region) => region.getAttribute("aria-label"));
    mockGameApi({
      game: gameDetail({
        white: { type: "agent", spec: { kind: "negamax", params: {} }, budget_s: 5 },
        black: { type: "human" },
      }),
    });
    renderGamePage();

    await findPrompt();
    expect(handOrder()).toEqual(["White hand", "Black hand"]);
  });

  it("draws white at the bottom in a hints game", async () => {
    mockGameApi({ game: HINTS_GAME });
    renderGamePage();

    const prompt = await findPrompt();
    expect(prompt).toHaveTextContent(
      "White's turn: make the move on the table and enter it",
    );
    expect(
      screen
        .getAllByRole("region", { name: /hand$/ })
        .map((region) => region.getAttribute("aria-label")),
    ).toEqual(["Black hand", "White hand"]);
  });
});

describe("GamePage hints", () => {
  /** Serve the hints game, with a hint stream per request that the test writes to. */
  function mockHints(handlers: Parameters<typeof mockApi>[0] = {}) {
    const streams: ReturnType<typeof controlledEventStream>[] = [];
    const requests = mockGameApi(
      { game: HINTS_GAME },
      {
        [`POST ${GAME_PATH}/think`]: ({ signal }) => {
          const stream = controlledEventStream(signal);
          streams.push(stream);

          return stream.response;
        },
        ...handlers,
      },
    );

    return { streams, requests };
  }

  function thinkRequests(requests: RecordedRequest[]): RecordedRequest[] {
    return requests.filter((request) => request.path.endsWith("/think"));
  }

  function suggestionShown(): boolean {
    return document.querySelector('[data-mark="suggestion"]') !== null;
  }

  it("asks for a hint, shows it and hides it again", async () => {
    const { streams, requests } = mockHints();
    const user = renderGamePage();
    const prompt = within(await findPrompt());

    // Hints stay hidden until asked for.
    expect(thinkRequests(requests)).toEqual([]);
    expect(
      within(screen.getByRole("region", { name: "White hand" })).getByRole("button", {
        name: "Hint",
      }),
    ).toBeInTheDocument();

    await user.click(prompt.getByRole("button", { name: "Hint" }));

    expect(await prompt.findByText("Hint: thinking…")).toBeInTheDocument();
    expect(prompt.getByText(/s left$/)).toBeInTheDocument();
    await waitFor(() => {
      expect(streams).toHaveLength(1);
    });
    expect(thinkRequests(requests)[0]?.body).toEqual({ commit: false });

    act(() => {
      streams[0]?.send({ type: "candidate", move: HINT_MOVE, final: true });
      streams[0]?.send({
        type: "decision",
        decision: decisionRecord(HINT_MOVE),
        position: null,
      });
    });

    expect(
      await prompt.findByText("Hint: place ant next to the white queen"),
    ).toBeInTheDocument();
    expect(suggestionShown()).toBe(true);

    await user.click(prompt.getByRole("button", { name: "Hint" }));

    expect(prompt.queryByText(/^Hint:/)).not.toBeInTheDocument();
    expect(suggestionShown()).toBe(false);

    // Asking again shows the same hint without thinking again.
    await user.click(prompt.getByRole("button", { name: "Hint" }));

    expect(
      prompt.getByText("Hint: place ant next to the white queen"),
    ).toBeInTheDocument();
    expect(thinkRequests(requests)).toHaveLength(1);
  });

  it("selects the hinted piece, and a move clears the hint", async () => {
    let position = gamePosition();
    const { streams } = mockHints({
      [`GET ${GAME_PATH}/state`]: () => ({ body: position }),
      [`POST ${GAME_PATH}/moves`]: () => {
        position = gamePosition({ ply: 3, ply_count: 3, current_player: "black" });

        return { status: 201, body: position };
      },
    });
    const user = renderGamePage();
    const prompt = within(await findPrompt());

    await user.click(prompt.getByRole("button", { name: "Hint" }));
    await waitFor(() => {
      expect(streams).toHaveLength(1);
    });
    act(() => {
      streams[0]?.send({
        type: "decision",
        decision: decisionRecord(HINT_MOVE),
        position: null,
      });
    });
    await prompt.findByText("Hint: place ant next to the white queen");

    await user.click(screen.getByRole("button", { name: "Place white ant, 3 left" }));

    expect(
      screen.getByRole("button", { name: "Place white ant, 3 left" }),
    ).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Play to (-1, 0)" }));

    expect(
      await prompt.findByText("Black's turn: make the move on the table and enter it"),
    ).toBeInTheDocument();
    expect(prompt.queryByText(/^Hint:/)).not.toBeInTheDocument();
    expect(suggestionShown()).toBe(false);
  });

  it("stops the hint search when hidden, after a move or when leaving", async () => {
    let position = gamePosition();
    const { streams, requests } = mockHints({
      [`GET ${GAME_PATH}/state`]: () => ({ body: position }),
      [`POST ${GAME_PATH}/moves`]: () => {
        position = gamePosition({ ply: 3, ply_count: 3, current_player: "black" });

        return { status: 201, body: position };
      },
    });
    const user = renderGamePage();
    const prompt = within(await findPrompt());
    const hintButton = () => prompt.getByRole("button", { name: "Hint" });

    await user.click(hintButton());
    await waitFor(() => {
      expect(streams).toHaveLength(1);
    });
    await user.click(hintButton());

    expect(thinkRequests(requests)[0]?.signal?.aborted).toBe(true);
    expect(prompt.queryByText(/^Hint:/)).not.toBeInTheDocument();

    await user.click(hintButton());
    await waitFor(() => {
      expect(streams).toHaveLength(2);
    });
    await user.click(screen.getByRole("button", { name: "Place white spider, 2 left" }));
    await user.click(screen.getByRole("button", { name: "Play to (0, -1)" }));

    await prompt.findByText("Black's turn: make the move on the table and enter it");
    expect(thinkRequests(requests)[1]?.signal?.aborted).toBe(true);

    await user.click(hintButton());
    await waitFor(() => {
      expect(streams).toHaveLength(3);
    });
    await user.click(screen.getByRole("link", { name: "Games" }));

    expect(await screen.findByRole("heading", { name: "Games" })).toBeInTheDocument();
    expect(thinkRequests(requests)[2]?.signal?.aborted).toBe(true);
  });
});
