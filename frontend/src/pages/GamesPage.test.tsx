import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { GamePage, GameSummary } from "@/api/client";
import { GAMES_PAGE_SIZE, GamesPage } from "@/pages/GamesPage";
import { mockApi } from "@/test/api";
import { AGENT_KINDS, gameSummary } from "@/test/fixtures";
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

async function openActions(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(screen.getByRole("button", { name: `Actions for ${name}` }));
}

describe("GamesPage", () => {
  it("lists the games with players, status, ply and export link", async () => {
    const finished = gameSummary({
      id: "0c4a3b5e-0000-4000-8000-000000000002",
      name: "Agent match",
      status: "finished",
      result: "white",
      white: { type: "agent", spec: { kind: "random", label: "rnd" }, budget_s: 1 },
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
    expect(within(row("Evening game")).getByText("Active")).toBeInTheDocument();

    await openActions(user, "Evening game");

    expect(screen.getByRole("menuitem", { name: "Export" })).toHaveAttribute(
      "href",
      `${GAME_PATH}/export`,
    );
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

  it("creates a human vs agent game and opens it", async () => {
    const requests = mockApi({
      "GET /api/games": () => page([]),
      "GET /api/agents": () => ({ body: AGENT_KINDS }),
      "POST /api/games": ({ body }) => ({
        status: 201,
        body: { ...GAME, ...(body as object), rules: {}, setup: null, moves: [] },
      }),
    });
    const user = userEvent.setup();
    renderPage(<GamesPage />);

    await user.click(await screen.findByRole("button", { name: "New game" }));
    const dialog = await screen.findByRole("dialog", { name: "New game" });
    await within(dialog).findByRole("group", { name: "Black" });
    await user.type(within(dialog).getByRole("textbox", { name: "Depth" }), "2");
    await user.click(within(dialog).getByRole("button", { name: "Create game" }));

    expect(await screen.findByText(`Game page ${GAME.id}`)).toBeInTheDocument();
    expect(requests.find((request) => request.method === "POST")?.body).toEqual({
      name: "Human vs negamax (5 s)",
      white: { type: "human" },
      black: {
        type: "agent",
        spec: { kind: "negamax", params: { depth: 2 }, label: null },
        budget_s: 5,
      },
    });
  });

  it("creates an agent vs agent game", async () => {
    const requests = mockApi({
      "GET /api/games": () => page([]),
      "GET /api/agents": () => ({ body: AGENT_KINDS }),
      "POST /api/games": ({ body }) => ({
        status: 201,
        body: { ...GAME, ...(body as object), rules: {}, setup: null, moves: [] },
      }),
    });
    const user = userEvent.setup();
    renderPage(<GamesPage />);

    await user.click(await screen.findByRole("button", { name: "New game" }));
    const dialog = await screen.findByRole("dialog", { name: "New game" });
    const white = await within(dialog).findByRole("group", { name: "White" });
    await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "Bots");
    await user.click(within(white).getByRole("combobox", { name: "Player" }));
    await user.click(screen.getByRole("option", { name: "Agent" }));
    await user.click(within(dialog).getByRole("button", { name: "Create game" }));

    await waitFor(() => {
      expect(requests.find((request) => request.method === "POST")?.body).toMatchObject({
        name: "Bots",
        white: { type: "agent", spec: { kind: "negamax" } },
        black: { type: "agent", spec: { kind: "negamax" } },
      });
    });
  });
});
