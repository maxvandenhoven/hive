/**
 * What a photo of the physical board showed, in words for the person at the table.
 *
 * After a person's move the API proposes the legal moves the photo shows, best first,
 * and says whether one is clear; while an agent move is pending it checks that move.
 * Nothing is played until the person confirms, so these descriptions also say how sure
 * the reading is and why it is not sure.
 */

import type {
  BoardEstimate,
  BoardSetup,
  Move,
  MoveCandidate,
  PhotoRead,
} from "@/api/client";
import type { BoardView } from "@/components/board/types";
import { boardAfterMove, capitalize, describeMoveOnBoard } from "@/lib/moves";
import { otherSide, type PlayerSide } from "@/lib/players";

/**
 * What a photo leads to, which decides the actions offered with it.
 *
 * - `proposal`: one move is clear; the person confirms it or picks another.
 * - `candidates`: several moves fit; the person picks one or takes another photo.
 * - `failed`: no legal move fits, for example without tiles in view.
 * - `matched`: the pending agent move was made, which confirms it.
 * - `mismatched`: another move was made at the table than the pending one.
 * - `unclear`: the photo does not clearly show whether the pending move was made.
 * - `unread`: the photo is stored, but the app has no board reader.
 */
export type PhotoOutcome =
  "proposal" | "candidates" | "failed" | "matched" | "mismatched" | "unclear" | "unread";

/** A candidate move of a photo, described on the board. */
export interface PhotoCandidateView {
  /** The moves, one, or two when a photo was skipped. */
  moves: (Move | null)[];
  /** The moves by the pieces they touch, such as `ant moves next to the white queen`. */
  text: string;
  probability: number;
}

/** A photo result for the photo panel. */
export interface PhotoView {
  outcome: PhotoOutcome;
  /** One sentence on what the photo shows. */
  title: string;
  /** How sure the reading is, or why it is not, or `null`. */
  detail: string | null;
  /** The candidate moves, best first; empty for `unread`. */
  candidates: PhotoCandidateView[];
  /** What else to know: a cut-off hive, earlier photos and the previous photo. */
  notes: string[];
}

interface DescribePhotoOptions {
  photo: PhotoRead;
  /** The board before the moves the photo resolves, top piece first. */
  board: BoardView;
  /** The side to move on that board, whose piece a placement puts down. */
  side: PlayerSide;
}

/**
 * A probability as a percentage that never claims certainty: `62%`, or `>99%` for
 * readings that round to a hundred.
 */
export function formatProbability(probability: number): string {
  return probability >= 0.995 ? ">99%" : `${Math.round(probability * 100)}%`;
}

/** Describe the moves of a candidate on the board before them. */
export function describeCandidate(
  candidate: Pick<MoveCandidate, "moves">,
  board: BoardView,
  side: PlayerSide,
): string {
  let shown = board;
  let mover = side;
  const parts: string[] = [];

  for (const move of candidate.moves) {
    parts.push(describeMoveOnBoard(move, shown));
    shown = boardAfterMove(shown, move, mover);
    mover = otherSide(mover);
  }

  return parts.length > 1
    ? `${parts.join(", then ")} (two moves: a photo was skipped)`
    : (parts[0] ?? "");
}

/** The notes of a read photo: a cut-off hive, earlier photos and the previous photo. */
function photoNotes(photo: PhotoRead): string[] {
  const match = photo.match;

  if (match === null) {
    return [];
  }

  const notes: string[] = [];

  if (match.edge) {
    notes.push("The hive touches the edge of the photo, so some tiles may be cut off.");
  }

  const earlier = match.photo_ids.length - 1;

  if (earlier > 0) {
    notes.push(
      `Read together with ${earlier} earlier ${earlier === 1 ? "photo" : "photos"} of this position.`,
    );
  }

  if (match.previous_photo_id !== null) {
    notes.push("The previous photo helped to recognise the tiles.");
  }

  return notes;
}

/** Describe what a photo shows, and how sure the app is, for the photo panel. */
export function describePhoto({ photo, board, side }: DescribePhotoOptions): PhotoView {
  const match = photo.match;

  if (match === null) {
    return {
      outcome: "unread",
      title: "Photo saved: enter the move by hand",
      detail: "This app has no board reader set up, so it cannot read photos yet.",
      candidates: [],
      notes: [],
    };
  }

  const { resolution, verification } = match;
  const candidates = resolution.candidates.map((candidate) => ({
    moves: candidate.moves,
    text: describeCandidate(candidate, board, side),
    probability: candidate.probability,
  }));
  const notes = photoNotes(photo);
  const best = candidates[0];

  if (verification !== null) {
    switch (verification.status) {
      case "matched":
        return {
          outcome: "matched",
          title: "The photo shows the move was made",
          detail: `${formatProbability(verification.probability)} sure.`,
          candidates,
          notes,
        };
      case "mismatched":
        return {
          outcome: "mismatched",
          title: `The photo shows another move: ${best?.text ?? "unknown"}`,
          detail:
            "Make the agent's move on the table and take another photo, or keep the " +
            "move made at the table.",
          candidates,
          notes,
        };
      case "unclear":
        return {
          outcome: "unclear",
          title: "Not sure the move was made",
          detail: verification.reason ?? null,
          candidates,
          notes,
        };
    }
  }

  switch (resolution.status) {
    case "resolved":
      return {
        outcome: "proposal",
        title: `The photo shows: ${best?.text ?? "unknown"}`,
        detail: `${capitalize(formatProbability(best?.probability ?? 0))} sure. Check the move before you play it.`,
        candidates,
        notes,
      };
    case "ambiguous":
      return {
        outcome: "candidates",
        title: "Not sure which move the photo shows",
        detail:
          "Pick the move that was made, or take another photo from a different angle " +
          "with the changed tiles in view.",
        candidates,
        notes,
      };
    case "failed":
      return {
        outcome: "failed",
        title: "Could not read a move from the photo",
        detail: resolution.reason ?? null,
        candidates,
        notes,
      };
  }
}

/**
 * The setup a board read from one photo starts a game with, or `null` while there is no
 * usable reading. The side to move must be one the rules allow on the board.
 */
export function photoSetup(
  estimate: BoardEstimate | null,
  nextPlayer: PlayerSide,
): BoardSetup | null {
  const [firstPlayer] = estimate?.players ?? [];

  if (estimate === null || estimate.status === "failed" || firstPlayer === undefined) {
    return null;
  }

  return {
    board: estimate.board,
    current_player: estimate.players.includes(nextPlayer) ? nextPlayer : firstPlayer,
  };
}
