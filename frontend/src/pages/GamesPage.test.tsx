import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { GamePage, GameSummary } from "@/api/client";
import { GAMES_PAGE_SIZE, GamesPage } from "@/pages/GamesPage";
import { mockApi, type RecordedRequest } from "@/test/api";
import { AGENT_KINDS, AGENT_PRESETS, gameSummary } from "@/test/fixtures";
import { renderPage } from "@/test/render";

const GAME = gameSummary();
const GAME_PATH = `/api/games/${GAME.id}`;

function page(
  items: GameSummary[],
  total = items.length,
  offset = 0,
): { body: GamePage } {
  return { body: { items, total, limit: GAMES_PAGE_SIZE, offset } };
}

function row(name: string): HTMLElement {
  const link = screen.getByRole("link", { name });
  const element = link.closest("tr");

  if (element === null) {
    throw new Error(`The game ${name} has no row.`);
  }

  return element;
}

const NM2_SPEC = AGENT_PRESETS[0]?.spec;
const NM3_SPEC = AGENT_PRESETS[1]?.spec;

/** Mock the API of the new game flow; created games echo the request. */
function mockNewGame(): RecordedRequest[] {
  return mockApi({
    "GET /api/games": () => page([]),
    "GET /api/agents": () => ({ body: AGENT_KINDS }),
    "GET /api/agents/presets": () => ({ body: AGENT_PRESETS }),
    "POST /api/games": ({ body }) => ({
      status: 201,
      body: { ...GAME, ...(body as object), rules: {}, setup: null, moves: [] },
    }),
  });
}

/** The body of the last game created. */
function postedGame(requests: RecordedRequest[]): unknown {
  return requests.filter((request) => request.method === "POST").at(-1)?.body;
}

async function openNewGame(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "New game" }));

  return screen.findByRole("dialog");
}

async function choose(
  user: ReturnType<typeof userEvent.setup>,
  combobox: HTMLElement,
  option: string,
): Promise<void> {
  await user.click(combobox);
  await user.click(screen.getByRole("option", { name: option }));
}

async function openActions(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(screen.getByRole("button", { name: `Actions for ${name}` }));
}

describe("GamesPage", () => {
  it("lists the games with players, ply and export link", async () => {
    const finished = gameSummary({
      id: "0c4a3b5e-0000-4000-8000-000000000002",
      name: "Agent match",
      status: "finished",
      result: "white",
      white: { type: "agent", spec: { kind: "random", label: "rnd" }, budget_s: 1 },
      board_location: "screen",
      ply_count: 40,
    });
    mockApi({ "GET /api/games": () => page([GAME, finished]) });
    const user = userEvent.setup();
    renderPage(<GamesPage />);

    expect(await screen.findByRole("link", { name: "Evening game" })).toHaveAttribute(
      "href",
      `/games/${GAME.id}`,
    );
    const cells = within(row("Agent match")).getAllByRole("cell");
    expect(cells.map((cell) => cell.textContent)).toEqual(
      expect.arrayContaining(["rnd (1 s) vs negamax (5 s)", "White won", "40"]),
    );

    await openActions(user, "Evening game");

    expect(screen.getByRole("menuitem", { name: "Export" })).toHaveAttribute(
      "href",
      `${GAME_PATH}/export`,
    );
  });

  it("shows the scenario and the next action of each game", async () => {
    const nm3 = { type: "agent", spec: { kind: "negamax", label: "nm3" }, budget_s: 5 };
    const hinted = { type: "human", hint: { spec: nm3.spec, budget_s: 5 } };
    const games = [
      gameSummary({ name: "On screen", board_location: "screen" }),
      gameSummary({ name: "Pending", pending_move: true }),
      gameSummary({
        name: "Agent thinks",
        black: nm3 as GameSummary["black"],
        current_player: "black",
        current_player_type: "agent",
      }),
      gameSummary({
        name: "Hints",
        white: hinted as GameSummary["white"],
        black: { type: "human" },
        current_player: "black",
      }),
      gameSummary({
        name: "Watching",
        white: nm3 as GameSummary["white"],
        board_location: "screen",
        current_player_type: "agent",
      }),
      gameSummary({ name: "Over", status: "finished", result: "black" }),
    ].map((game, index) => ({ ...game, id: `game-${index}` }));
    mockApi({ "GET /api/games": () => page(games) });
    renderPage(<GamesPage />);
    await screen.findByRole("link", { name: "On screen" });

    const expected = [
      ["On screen", "vs agent", "Your turn"],
      ["Pending", "vs agent", "Agent's move to make"],
      ["Agent thinks", "vs agent", "nm3 to move"],
      ["Hints", "hints game", "Black to move"],
      ["Watching", "watching", "nm3 to move"],
      ["Over", "vs agent", "Black won"],
    ];

    for (const [name, scenario, next] of expected) {
      const cells = within(row(name ?? "")).getAllByRole("cell");
      expect(cells[0]).toHaveTextContent(`${name}${scenario}`);
      expect(cells[1]).toHaveTextContent(next ?? "");
    }
  });

  it("shows an empty list", async () => {
    mockApi({ "GET /api/games": () => page([]) });
    renderPage(<GamesPage />);

    expect(await screen.findByText(/No games yet/)).toBeInTheDocument();
  });

  it("pages through the games", async () => {
    const requests = mockApi({
      "GET /api/games": ({ search }) =>
        page([GAME], GAMES_PAGE_SIZE + 1, search.includes("offset=20") ? 20 : 0),
    });
    const user = userEvent.setup();
    renderPage(<GamesPage />);

    expect(await screen.findByText(`1–1 of ${GAMES_PAGE_SIZE + 1}`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(
      await screen.findByText(`21–21 of ${GAMES_PAGE_SIZE + 1}`),
    ).toBeInTheDocument();
    expect(requests.at(-1)?.search).toBe(`?limit=${GAMES_PAGE_SIZE}&offset=20`);
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("renames a game", async () => {
    let games = [GAME];
    const requests = mockApi({
      "GET /api/games": () => page(games),
      [`PATCH ${GAME_PATH}`]: () => {
        games = [{ ...GAME, name: "Rematch" }];

        return { body: { ...games[0], rules: {}, setup: null, moves: [] } };
      },
    });
    const user = userEvent.setup();
    renderPage(<GamesPage />);
    await screen.findByRole("link", { name: "Evening game" });

    await openActions(user, "Evening game");
    await user.click(screen.getByRole("menuitem", { name: "Rename" }));
    const dialog = screen.getByRole("dialog", { name: "Rename game" });
    const name = within(dialog).getByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "Rematch");
    await user.click(within(dialog).getByRole("button", { name: "Rename" }));

    expect(await screen.findByRole("link", { name: "Rematch" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(requests.find((request) => request.method === "PATCH")?.body).toEqual({
      name: "Rematch",
    });
  });

  it("deletes a game after confirming", async () => {
    let games = [GAME];
    const requests = mockApi({
      "GET /api/games": () => page(games),
      [`DELETE ${GAME_PATH}`]: () => {
        games = [];

        return { status: 204 };
      },
    });
    const user = userEvent.setup();
    renderPage(<GamesPage />);
    await screen.findByRole("link", { name: "Evening game" });

    await openActions(user, "Evening game");
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete game?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(await screen.findByText(/No games yet/)).toBeInTheDocument();
    expect(requests.map((request) => request.method)).toContain("DELETE");
  });

  it("reports failed changes", async () => {
    mockApi({
      "GET /api/games": () => page([GAME]),
      [`DELETE ${GAME_PATH}`]: () => ({
        status: 404,
        body: { code: "game_not_found", detail: "Game not found." },
      }),
    });
    const user = userEvent.setup();
    renderPage(<GamesPage />);
    await screen.findByRole("link", { name: "Evening game" });

    await openActions(user, "Evening game");
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }),
    );

    expect(await screen.findByText("Game not found.")).toBeInTheDocument();
  });

  it("plays against an agent by default and opens the game", async () => {
    const requests = mockNewGame();
    const user = userEvent.setup();
    renderPage(<GamesPage />);

    const dialog = await openNewGame(user);
    await user.click(
      within(dialog).getByRole("button", { name: /Play against an agent/ }),
    );

    expect(within(dialog).getByRole("radio", { name: "White" })).toBeChecked();
    expect(within(dialog).getByRole("combobox", { name: "Opponent" })).toHaveTextContent(
      "nm3",
    );
    expect(
      within(dialog).getByRole("textbox", { name: "Name (optional)" }),
    ).toHaveAttribute("placeholder", "You vs nm3");

    await user.click(within(dialog).getByRole("button", { name: "Start game" }));

    expect(await screen.findByText(`Game page ${GAME.id}`)).toBeInTheDocument();
    expect(postedGame(requests)).toEqual({
      name: "You vs nm3",
      white: { type: "human" },
      black: { type: "agent", spec: NM3_SPEC, budget_s: 5 },
      board_location: "screen",
    });
  });

  it("plays against an agent as black with hints", async () => {
    const requests = mockNewGame();
    const user = userEvent.setup();
    renderPage(<GamesPage />);

    const dialog = await openNewGame(user);
    await user.click(
      within(dialog).getByRole("button", { name: /Play against an agent/ }),
    );
    await user.click(within(dialog).getByRole("radio", { name: "Black" }));
    await choose(user, within(dialog).getByRole("combobox", { name: "Opponent" }), "nm2");
    await user.click(within(dialog).getByRole("checkbox", { name: /Hints for you/ }));
    await user.click(within(dialog).getByRole("button", { name: "Start game" }));

    await waitFor(() => {
      expect(postedGame(requests)).toEqual({
        name: "You vs nm2",
        white: { type: "agent", spec: NM2_SPEC, budget_s: 5 },
        black: { type: "human", hint: { spec: NM3_SPEC, budget_s: 5 } },
        board_location: "screen",
      });
    });
  });

  it("plays a friend with hints only for the person", async () => {
    const requests = mockNewGame();
    const user = userEvent.setup();
    renderPage(<GamesPage />);

    const dialog = await openNewGame(user);
    await user.click(
      within(dialog).getByRole("button", { name: /Play a friend with hints/ }),
    );
    await user.click(within(dialog).getByRole("radio", { name: "Black" }));
    await user.type(
      within(dialog).getByRole("textbox", { name: "Opponent's name" }),
      "Sam",
    );
    await choose(
      user,
      within(dialog).getByRole("combobox", { name: "Hint strength" }),
      "nm2",
    );
    await user.click(within(dialog).getByRole("button", { name: "Start game" }));

    await waitFor(() => {
      expect(postedGame(requests)).toEqual({
        name: "You vs Sam",
        white: { type: "human", name: "Sam" },
        black: { type: "human", hint: { spec: NM2_SPEC, budget_s: 5 } },
        board_location: "table",
      });
    });
  });

  it("watches two agents, one of them set up in advanced", async () => {
    const requests = mockNewGame();
    const user = userEvent.setup();
    renderPage(<GamesPage />);

    const dialog = await openNewGame(user);
    await user.click(within(dialog).getByRole("button", { name: /Watch two agents/ }));
    await choose(
      user,
      within(dialog).getByRole("combobox", { name: "Black agent" }),
      "Advanced…",
    );
    const depth = within(dialog).getByRole("textbox", { name: "Depth" });
    await user.clear(depth);
    await user.type(depth, "1");
    await user.type(
      within(dialog).getByRole("textbox", { name: "Name (optional)" }),
      "Bots",
    );
    await user.click(within(dialog).getByRole("button", { name: "Start game" }));

    await waitFor(() => {
      expect(postedGame(requests)).toEqual({
        name: "Bots",
        white: { type: "agent", spec: NM3_SPEC, budget_s: 5 },
        black: {
          type: "agent",
          spec: { kind: "negamax", params: { depth: 1 }, label: null },
          budget_s: 5,
        },
        board_location: "screen",
      });
    });
  });

  it("goes back from the setup to the scenarios", async () => {
    mockNewGame();
    const user = userEvent.setup();
    renderPage(<GamesPage />);

    const dialog = await openNewGame(user);
    await user.click(within(dialog).getByRole("button", { name: /Watch two agents/ }));

    expect(
      within(dialog).getByRole("heading", { name: "Watch two agents" }),
    ).toBeVisible();

    await user.click(
      within(dialog).getByRole("button", { name: "Back to the scenarios" }),
    );

    expect(
      within(dialog).getByRole("button", { name: /Play a friend with hints/ }),
    ).toBeInTheDocument();
  });

  it("remembers the last choices and opens at their setup", async () => {
    const requests = mockNewGame();
    const user = userEvent.setup();
    renderPage(<GamesPage />);

    let dialog = await openNewGame(user);
    await user.click(
      within(dialog).getByRole("button", { name: /Play a friend with hints/ }),
    );
    await user.click(within(dialog).getByRole("radio", { name: "Black" }));
    await user.click(within(dialog).getByRole("button", { name: "Start game" }));
    await screen.findByText(`Game page ${GAME.id}`);

    renderPage(<GamesPage />);
    dialog = await openNewGame(user);

    expect(
      within(dialog).getByRole("heading", { name: "Play a friend with hints" }),
    ).toBeVisible();
    expect(within(dialog).getByRole("radio", { name: "Black" })).toBeChecked();

    await user.click(within(dialog).getByRole("button", { name: "Start game" }));

    await waitFor(() => {
      expect(requests.filter((request) => request.method === "POST")).toHaveLength(2);
    });
    expect(postedGame(requests)).toMatchObject({
      white: { type: "human" },
      black: { type: "human", hint: { spec: NM3_SPEC } },
    });
  });
});
