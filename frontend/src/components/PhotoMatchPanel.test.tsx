import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { GameDetail, GamePosition, Move, PhotoRead } from "@/api/client";
import { GamePage } from "@/pages/GamePage";
import { mockApi, type ApiHandler } from "@/test/api";
import {
  gameDetail,
  gamePosition,
  moveRead,
  photoCandidate,
  photoMatch,
  photoRead,
} from "@/test/fixtures";
import { renderPage } from "@/test/render";

const GAME = gameDetail();
const GAME_PATH = `/api/games/${GAME.id}`;
const PHOTO_ID = photoRead().id;

const ANT: Move = { piece: "ant", from: null, to: [-1, 0] };
const SPIDER: Move = { piece: "spider", from: null, to: [-1, 1] };
const AGENT_MOVE: Move = { piece: "spider", from: null, to: [2, 0] };

/** The position after white placed the ant, with black, the agent, to move. */
const AFTER_ANT = gamePosition({
  ply: 3,
  ply_count: 3,
  current_player: "black",
  last_move: moveRead({ ply: 2, move: ANT, source: "photo", photo_id: PHOTO_ID }),
});

/** A table game whose agent move waits to be made at ply 3. */
const PENDING = gamePosition({
  ply: 4,
  ply_count: 4,
  board: [
    ...gamePosition().board,
    { coord: [-1, 0], stack: [{ piece: "ant", owner: "white" }] },
    { coord: [2, 0], stack: [{ piece: "spider", owner: "black" }] },
  ],
  last_move: moveRead({ ply: 3, move: AGENT_MOVE, source: "agent", pending: true }),
  pending_move: true,
});

function mockGame(
  {
    game = GAME,
    position = gamePosition(),
  }: { game?: GameDetail; position?: GamePosition },
  handlers: Record<string, ApiHandler> = {},
) {
  return mockApi({
    [`GET ${GAME_PATH}`]: () => ({ body: game }),
    [`GET ${GAME_PATH}/state`]: () => ({ body: position }),
    ...handlers,
  });
}

function photoHandler(photo: PhotoRead): ApiHandler {
  return () => ({ status: 201, body: photo });
}

async function takePhoto(user: ReturnType<typeof userEvent.setup>, label = "Photo") {
  const file = new File(["jpeg"], "board.jpg", { type: "image/jpeg" });
  await user.upload(await screen.findByLabelText(`${label} of the board`), file);
}

function renderGamePage() {
  renderPage(<GamePage />, { path: `/games/${GAME.id}`, route: "/games/:gameId" });

  return userEvent.setup();
}

describe("photos at the table", () => {
  it("proposes the move a photo shows and plays it with the photo", async () => {
    const requests = mockGame(
      {},
      {
        [`POST ${GAME_PATH}/photos`]: photoHandler(photoRead()),
        [`POST ${GAME_PATH}/moves`]: () => ({ status: 201, body: AFTER_ANT }),
      },
    );
    const user = renderGamePage();

    await takePhoto(user);
    const panel = within(
      await screen.findByRole("region", { name: "Photo of the board" }),
    );

    expect(
      await panel.findByText("The photo shows: place ant next to the white queen"),
    ).toBeInTheDocument();
    expect(panel.getByText(/98% sure/)).toBeInTheDocument();
    expect(requests.find((request) => request.path.endsWith("/photos"))?.body).toEqual({
      image: "file:board.jpg",
      expected_ply: "2",
    });

    await user.click(panel.getByRole("button", { name: "Play this move" }));

    await waitFor(() => {
      expect(requests.find((request) => request.path.endsWith("/moves"))?.body).toEqual({
        move: ANT,
        source: "photo",
        photo_id: PHOTO_ID,
        expected_ply: 2,
        allow_agent_side: false,
      });
    });
    await waitFor(() => {
      expect(
        screen.queryByRole("region", { name: "Photo of the board" }),
      ).not.toBeInTheDocument();
    });
  });

  it("lets the person pick among the moves of an unclear photo", async () => {
    const unclear = photoRead({
      match: photoMatch({
        resolution: {
          status: "ambiguous",
          candidates: [photoCandidate([ANT], 0.55), photoCandidate([SPIDER], 0.45)],
          reason: "The photo fits several moves.",
        },
      }),
    });
    const requests = mockGame(
      {},
      {
        [`POST ${GAME_PATH}/photos`]: photoHandler(unclear),
        [`POST ${GAME_PATH}/moves`]: () => ({ status: 201, body: AFTER_ANT }),
      },
    );
    const user = renderGamePage();

    await takePhoto(user);
    const panel = within(
      await screen.findByRole("region", { name: "Photo of the board" }),
    );
    await panel.findByText("Not sure which move the photo shows");
    const candidates = within(
      panel.getByRole("list", { name: "Moves the photo may show" }),
    );

    expect(candidates.getAllByRole("button").map((button) => button.textContent)).toEqual(
      ["place ant next to the white queen55%", "place spider next to the white queen45%"],
    );
    expect(panel.getByLabelText("Another photo of the board")).toBeInTheDocument();

    const [, second] = candidates.getAllByRole("button");
    await user.click(second ?? panel.getByRole("list"));
    await user.click(panel.getByRole("button", { name: "Play the picked move" }));

    await waitFor(() => {
      expect(requests.find((request) => request.path.endsWith("/moves"))?.body).toEqual(
        expect.objectContaining({ move: SPIDER, source: "photo", photo_id: PHOTO_ID }),
      );
    });
  });

  it("says why a photo could not be read and goes back to entering by hand", async () => {
    const failed = photoRead({
      match: photoMatch({
        resolution: {
          status: "failed",
          candidates: [],
          reason:
            "No tiles were found. Take a photo with every tile of the hive in view.",
        },
        edge: true,
      }),
    });
    mockGame({}, { [`POST ${GAME_PATH}/photos`]: photoHandler(failed) });
    const user = renderGamePage();

    await takePhoto(user);
    const panel = within(
      await screen.findByRole("region", { name: "Photo of the board" }),
    );

    expect(await panel.findByText(/No tiles were found/)).toBeInTheDocument();
    expect(panel.getByText(/touches the edge of the photo/)).toBeInTheDocument();
    expect(panel.queryByRole("button", { name: /Play/ })).not.toBeInTheDocument();

    await user.click(panel.getByRole("button", { name: "Enter by hand" }));

    expect(
      screen.queryByRole("region", { name: "Photo of the board" }),
    ).not.toBeInTheDocument();
  });

  it("confirms a pending agent move that a photo shows", async () => {
    let position = PENDING;
    const matched = photoRead({
      ply: 3,
      match: photoMatch({
        purpose: "verification",
        resolution: {
          status: "resolved",
          candidates: [photoCandidate([AGENT_MOVE], 0.97)],
          reason: null,
        },
        verification: { status: "matched", probability: 0.97, reason: null },
      }),
    });
    const requests = mockGame(
      { position },
      {
        [`GET ${GAME_PATH}/state`]: () => ({ body: position }),
        [`POST ${GAME_PATH}/photos`]: photoHandler(matched),
        [`POST ${GAME_PATH}/moves/last/confirm`]: () => {
          position = { ...PENDING, pending_move: false };

          return { body: position };
        },
      },
    );
    const user = renderGamePage();

    await takePhoto(user);

    await waitFor(() => {
      expect(requests.find((request) => request.path.endsWith("/confirm"))?.body).toEqual(
        {
          expected_ply: 4,
          photo_id: PHOTO_ID,
        },
      );
    });
    expect(
      await screen.findByText("The photo shows the move was made."),
    ).toBeInTheDocument();
  });

  it("replaces a pending agent move with the move made at the table", async () => {
    const mismatched = photoRead({
      ply: 3,
      match: photoMatch({
        purpose: "verification",
        resolution: {
          status: "resolved",
          candidates: [photoCandidate([{ piece: "ant", from: null, to: [2, 0] }], 0.96)],
          reason: null,
        },
        verification: {
          status: "mismatched",
          probability: 0.01,
          reason:
            "The photo shows place ant at (2, 0) instead of place spider at (2, 0).",
        },
      }),
    });
    const requests = mockGame(
      { position: PENDING },
      {
        [`POST ${GAME_PATH}/photos`]: photoHandler(mismatched),
        [`DELETE ${GAME_PATH}/moves/last`]: () => ({ body: AFTER_ANT }),
        [`POST ${GAME_PATH}/moves`]: () => ({
          status: 201,
          body: gamePosition({ ply: 4, ply_count: 4 }),
        }),
      },
    );
    const user = renderGamePage();

    await takePhoto(user);
    const panel = within(
      await screen.findByRole("region", { name: "Photo of the board" }),
    );
    await panel.findByText(
      "The photo shows another move: place ant next to the black queen",
    );
    await user.click(
      panel.getByRole("button", { name: "Keep the move made at the table" }),
    );

    await waitFor(() => {
      expect(requests.find((request) => request.path.endsWith("/moves"))?.body).toEqual({
        move: { piece: "ant", from: null, to: [2, 0] },
        source: "photo",
        photo_id: PHOTO_ID,
        expected_ply: 3,
        allow_agent_side: true,
      });
    });
    expect(requests.find((request) => request.method === "DELETE")?.search).toBe(
      "?expected_ply=4",
    );
  });

  it("offers no camera on the screen", async () => {
    mockGame({ game: gameDetail({ board_location: "screen" }) });
    renderGamePage();

    await screen.findByRole("region", { name: "Turn prompt" });

    expect(screen.queryByLabelText("Photo of the board")).not.toBeInTheDocument();
  });

  it("shows the photo of a move in the move list", async () => {
    const game = gameDetail({
      moves: [moveRead({ source: "photo", photo_id: PHOTO_ID })],
    });
    mockGame({ game });
    renderGamePage();

    const link = await screen.findByRole("link", { name: "Photo of move 1" });

    expect(link).toHaveAttribute("href", `/api/photos/${PHOTO_ID}/image`);
  });
});
