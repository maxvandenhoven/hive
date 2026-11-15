import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import type { GameDetail, GamePosition, Move, PhotoRead } from "@/api/client";
import { useAddPhoto, useConfirmMove, usePlayPhotoMoves } from "@/api/queries";
import type { BoardView } from "@/components/board/types";
import { boardBeforeMove, toBoardView } from "@/lib/moves";
import { describePhoto, type PhotoView } from "@/lib/photos";
import { otherSide } from "@/lib/players";

/**
 * Where the photo of the latest position stands: `idle` until one is taken, `reading`
 * while the API stores and reads it, then `shown` with what it showed.
 */
export type PhotoState =
  | { type: "idle" }
  | { type: "reading"; previewUrl: string }
  | {
      type: "shown";
      photo: PhotoRead;
      view: PhotoView;
      previewUrl: string;
      /** The candidate the person picked, which the board shows; 0 is the best. */
      selected: number;
    };

interface PhotoMovesOptions {
  game: GameDetail;
  /** The latest position. */
  position: GamePosition;
  /** Whether photos can be taken now: a live, human or pending turn at the table. */
  enabled: boolean;
}

export interface PhotoMoves {
  /** Whether the camera is offered: the game is at the table and waits for a person. */
  available: boolean;
  state: PhotoState;
  /** Whether a photo is being read or its move played or confirmed. */
  busy: boolean;
  /** The first move of the picked candidate, for the board, or `null`. */
  proposedMove: Move | null;
  /** The board the candidates of the shown photo are described on. */
  board: BoardView;
  /** Send a photo of the board. */
  take: (image: File) => void;
  /** Pick a candidate of the shown photo. */
  select: (index: number) => void;
  /** Play the picked candidate, with the photo linked to it. */
  play: () => void;
  /** Hide the photo, for example to enter the move by hand. */
  dismiss: () => void;
}

/**
 * Photos of the physical board in a game at the table (WP 16, WP 19).
 *
 * After a person's move, a photo proposes the move it shows; the person plays it,
 * picks another candidate or takes another photo, which the API reads together with
 * the unclear one. While an agent move is pending, a photo checks it: a match confirms
 * the move like **Done**; another move can replace the agent's. Nothing is played
 * without the person's tap, and a new position clears the photo.
 */
export function usePhotoMoves({
  game,
  position,
  enabled,
}: PhotoMovesOptions): PhotoMoves {
  const ply = position.ply_count;
  const addPhoto = useAddPhoto(game.id);
  const playMoves = usePlayPhotoMoves(game.id);
  const confirmMove = useConfirmMove(game.id);
  const [state, setState] = useState<PhotoState>({ type: "idle" });
  // The position a photo belongs to: a confirmation changes it without a new ply.
  const positionKey = `${ply}:${position.pending_move}`;
  const [seenKey, setSeenKey] = useState(positionKey);
  const verifying = position.pending_move;
  const liveBoard = useMemo(() => toBoardView(position.board), [position.board]);
  // A verification resolves from the position before the pending move.
  const board = useMemo(
    () =>
      verifying
        ? boardBeforeMove(liveBoard, position.last_move?.move ?? null)
        : liveBoard,
    [verifying, liveBoard, position.last_move],
  );
  const side = verifying ? otherSide(position.current_player) : position.current_player;
  const previewUrl = state.type === "idle" ? null : state.previewUrl;

  // Any move, undo or confirmation makes the photo stale.
  if (seenKey !== positionKey) {
    setSeenKey(positionKey);
    setState({ type: "idle" });
  }

  useEffect(() => {
    if (previewUrl === null) {
      return;
    }

    return () => {
      URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const confirmWithPhoto = (photo: PhotoRead) => {
    confirmMove.mutate(
      { expectedPly: ply, photoId: photo.id },
      {
        onSuccess: () => {
          toast.success("The photo shows the move was made.");
        },
      },
    );
  };

  const take = (image: File) => {
    const url = URL.createObjectURL(image);
    setState({ type: "reading", previewUrl: url });
    addPhoto.mutate(
      { image, expectedPly: ply },
      {
        onSuccess: (photo) => {
          const view = describePhoto({ photo, board, side });

          if (view.outcome === "matched") {
            setState({ type: "idle" });
            confirmWithPhoto(photo);

            return;
          }

          setState({ type: "shown", photo, view, previewUrl: url, selected: 0 });
        },
        onError: () => {
          setState({ type: "idle" });
        },
      },
    );
  };

  const shown = state.type === "shown" ? state : null;
  const candidate = shown?.view.candidates[shown.selected];
  const showsMove =
    shown !== null &&
    ["proposal", "candidates", "mismatched"].includes(shown.view.outcome);

  return {
    available: enabled && game.board_location === "table",
    state,
    busy: addPhoto.isPending || playMoves.isPending || confirmMove.isPending,
    proposedMove:
      showsMove && candidate !== undefined ? (candidate.moves[0] ?? null) : null,
    board,
    take,
    select: (index) => {
      if (shown !== null) {
        setState({ ...shown, selected: index });
      }
    },
    play: () => {
      if (shown === null || candidate === undefined) {
        return;
      }

      playMoves.mutate(
        {
          moves: candidate.moves,
          expectedPly: ply,
          photoId: shown.photo.id,
          replacePending: verifying,
        },
        {
          onSuccess: () => {
            toast.success("Played the move from the photo.");
          },
        },
      );
    },
    dismiss: () => {
      setState({ type: "idle" });
    },
  };
}
