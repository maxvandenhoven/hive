import { describe, expect, it } from "vitest";

import type { Move } from "@/api/client";
import type { BoardView } from "@/components/board/types";
import { toBoardView } from "@/lib/moves";
import {
  describeCandidate,
  describePhoto,
  formatProbability,
  photoSetup,
} from "@/lib/photos";
import {
  boardEstimate,
  gamePosition,
  photoCandidate,
  photoMatch,
  photoRead,
} from "@/test/fixtures";

const BOARD: BoardView = toBoardView(gamePosition().board);
const ANT: Move = { piece: "ant", from: null, to: [-1, 0] };
const SPIDER: Move = { piece: "spider", from: null, to: [2, 0] };

describe("formatProbability", () => {
  it("rounds to a percentage and never claims certainty", () => {
    expect(formatProbability(0.624)).toBe("62%");
    expect(formatProbability(0.996)).toBe(">99%");
    expect(formatProbability(1)).toBe(">99%");
  });
});

describe("describeCandidate", () => {
  it("describes one move by the pieces it touches", () => {
    expect(describeCandidate({ moves: [ANT] }, BOARD, "white")).toBe(
      "place ant next to the white queen",
    );
  });

  it("describes two moves on the board between them", () => {
    expect(describeCandidate({ moves: [ANT, SPIDER] }, BOARD, "white")).toBe(
      "place ant next to the white queen, then place spider next to the black queen " +
        "(two moves: a photo was skipped)",
    );
  });
});

describe("describePhoto", () => {
  it("proposes a clear move with how sure it is", () => {
    const view = describePhoto({ photo: photoRead(), board: BOARD, side: "white" });

    expect(view.outcome).toBe("proposal");
    expect(view.title).toBe("The photo shows: place ant next to the white queen");
    expect(view.detail).toBe("98% sure. Check the move before you play it.");
    expect(view.notes).toEqual([]);
  });

  it("lists the candidates of an unclear photo, with notes", () => {
    const photo = photoRead({
      match: photoMatch({
        resolution: {
          status: "ambiguous",
          candidates: [photoCandidate([ANT], 0.6), photoCandidate([SPIDER], 0.4)],
          reason: "The photo fits several moves.",
        },
        photo_ids: ["a", "b"],
        previous_photo_id: "c",
        edge: true,
      }),
    });
    const view = describePhoto({ photo, board: BOARD, side: "white" });

    expect(view.outcome).toBe("candidates");
    expect(view.title).toBe("Not sure which move the photo shows");
    expect(view.candidates.map((candidate) => candidate.probability)).toEqual([0.6, 0.4]);
    expect(view.notes).toEqual([
      "The hive touches the edge of the photo, so some tiles may be cut off.",
      "Read together with 1 earlier photo of this position.",
      "The previous photo helped to recognise the tiles.",
    ]);
  });

  it("says why a photo could not be read", () => {
    const photo = photoRead({
      match: photoMatch({
        resolution: { status: "failed", candidates: [], reason: "No tiles were found." },
      }),
    });
    const view = describePhoto({ photo, board: BOARD, side: "white" });

    expect(view.outcome).toBe("failed");
    expect(view.detail).toBe("No tiles were found.");
  });

  it("says a photo without a reader is only stored", () => {
    const view = describePhoto({
      photo: photoRead({ match: null, reader: null }),
      board: BOARD,
      side: "white",
    });

    expect(view.outcome).toBe("unread");
    expect(view.candidates).toEqual([]);
  });

  it("checks a pending agent move", () => {
    const matched = photoRead({
      match: photoMatch({
        purpose: "verification",
        verification: { status: "matched", probability: 0.97, reason: null },
      }),
    });
    const mismatched = photoRead({
      match: photoMatch({
        purpose: "verification",
        verification: {
          status: "mismatched",
          probability: 0.01,
          reason: "The photo shows place ant at (-1, 0) instead of place spider.",
        },
      }),
    });
    const unclear = photoRead({
      match: photoMatch({
        purpose: "verification",
        resolution: { status: "ambiguous", candidates: [], reason: null },
        verification: { status: "unclear", probability: 0.5, reason: "Take another." },
      }),
    });

    expect(describePhoto({ photo: matched, board: BOARD, side: "white" })).toMatchObject({
      outcome: "matched",
      detail: "97% sure.",
    });
    expect(
      describePhoto({ photo: mismatched, board: BOARD, side: "white" }),
    ).toMatchObject({
      outcome: "mismatched",
      title: "The photo shows another move: place ant next to the white queen",
    });
    expect(describePhoto({ photo: unclear, board: BOARD, side: "white" })).toMatchObject({
      outcome: "unclear",
      detail: "Take another.",
    });
  });
});

describe("photoSetup", () => {
  it("starts from a usable board with a side the rules allow", () => {
    const estimate = boardEstimate({ players: ["black"] });

    expect(photoSetup(estimate, "white")).toEqual({
      board: estimate.board,
      current_player: "black",
    });
    expect(photoSetup(boardEstimate(), "white")?.current_player).toBe("white");
  });

  it("has no setup without a usable board", () => {
    expect(photoSetup(null, "white")).toBeNull();
    expect(photoSetup(boardEstimate({ status: "failed" }), "white")).toBeNull();
    expect(photoSetup(boardEstimate({ players: [] }), "white")).toBeNull();
  });
});
