import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import {
  api,
  unwrap,
  type Coordinate,
  type GameCreate,
  type GameDetail,
  type GamePosition,
  type GameUpdate,
  type MoveCreate,
  type PieceTargets,
} from "@/api/client";

// openapi-fetch reads tuples such as `Coordinate` as plain arrays. The API always sends
// them whole, so responses with coordinates are typed with their schema types.

/**
 * The query keys, so related queries are refreshed together.
 *
 * The positions and targets of a game are under its key, so refreshing the game
 * refreshes them too.
 */
export const queryKeys = {
  agentKinds: ["agents"] as const,
  games: ["games"] as const,
  gamePages: ["games", "page"] as const,
  gamePage: (limit: number, offset: number) => ["games", "page", limit, offset] as const,
  game: (gameId: string) => ["games", "detail", gameId] as const,
  gamePositions: (gameId: string) => ["games", "detail", gameId, "position"] as const,
  gamePosition: (gameId: string, ply: number | null) =>
    ["games", "detail", gameId, "position", ply ?? "latest"] as const,
  gameTargets: (gameId: string) => ["games", "detail", gameId, "targets"] as const,
  pieceTargets: (gameId: string, ply: number, coord: Coordinate | null) =>
    ["games", "detail", gameId, "targets", ply, coord] as const,
};

/** The registered agent kinds with their param schemas; they only change on deploy. */
export function useAgentKinds() {
  return useQuery({
    queryKey: queryKeys.agentKinds,
    queryFn: async () => unwrap(await api.GET("/api/agents")),
    staleTime: Infinity,
  });
}

/** One page of the game list, newest first. */
export function useGamePage(limit: number, offset: number) {
  return useQuery({
    queryKey: queryKeys.gamePage(limit, offset),
    queryFn: async () =>
      unwrap(await api.GET("/api/games", { params: { query: { limit, offset } } })),
    placeholderData: (previous) => previous,
  });
}

/** A game with its rules, setup and moves. */
export function useGame(gameId: string) {
  return useQuery({
    queryKey: queryKeys.game(gameId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/games/{game_id}", { params: { path: { game_id: gameId } } }),
      ) as GameDetail,
  });
}

export function useCreateGame() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (body: GameCreate) =>
      unwrap(await api.POST("/api/games", { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.games }),
  });
}

export function useUpdateGame() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ gameId, body }: { gameId: string; body: GameUpdate }) =>
      unwrap(
        await api.PATCH("/api/games/{game_id}", {
          params: { path: { game_id: gameId } },
          body,
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.games }),
  });
}

export function useDeleteGame() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (gameId: string) => {
      unwrap(
        await api.DELETE("/api/games/{game_id}", {
          params: { path: { game_id: gameId } },
        }),
      );
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.games }),
  });
}

/**
 * The position of a game after `ply` moves, or the latest position for `null`.
 *
 * While another ply of the same game loads, the position shown before stays, so
 * scrubbing through a replay does not flash.
 */
export function useGamePosition(gameId: string, ply: number | null = null) {
  return useQuery({
    queryKey: queryKeys.gamePosition(gameId, ply),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/games/{game_id}/state", {
          params: { path: { game_id: gameId }, query: ply === null ? {} : { ply } },
        }),
      ) as GamePosition,
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[2] === gameId ? previous : undefined,
  });
}

/**
 * The legal targets of the piece at `coord` in the latest position, at ply `ply`.
 *
 * Nothing is fetched while `coord` is `null`. Failures are reported in a toast.
 */
export function usePieceTargets(gameId: string, ply: number, coord: Coordinate | null) {
  return useQuery({
    queryKey: queryKeys.pieceTargets(gameId, ply, coord),
    queryFn:
      coord === null
        ? skipToken
        : async () =>
            unwrap(
              await api.GET("/api/games/{game_id}/targets", {
                params: {
                  path: { game_id: gameId },
                  query: { q: coord[0], r: coord[1] },
                },
              }),
            ) as PieceTargets,
    staleTime: Infinity,
    meta: { toastErrors: true },
  });
}

/**
 * Keep a position the API returned after a write (a move, an undo or a committed agent
 * decision) as the latest one.
 *
 * Targets and stored positions from this ply on are dropped, since the position at a
 * ply changes when a move is undone and another one played. The game and the game list
 * are refreshed for the moves, status and ply count.
 */
export function useStoreLatestPosition(gameId: string) {
  const queryClient = useQueryClient();

  return useCallback(
    async (position: GamePosition) => {
      queryClient.setQueryData(queryKeys.gamePosition(gameId, null), position);
      queryClient.removeQueries({ queryKey: queryKeys.gameTargets(gameId) });
      queryClient.removeQueries({
        queryKey: queryKeys.gamePositions(gameId),
        predicate: ({ queryKey }) => {
          const ply = queryKey[4];

          return typeof ply === "number" && ply >= position.ply_count;
        },
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.game(gameId), exact: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.gamePages }),
      ]);
    },
    [queryClient, gameId],
  );
}

/** Refresh everything about a game, after a write failed because it changed. */
export function useRefreshGame(gameId: string) {
  const queryClient = useQueryClient();

  return useCallback(
    () => queryClient.invalidateQueries({ queryKey: queryKeys.game(gameId) }),
    [queryClient, gameId],
  );
}

/** Play a move entered by hand at the expected ply, returning the new position. */
export function usePlayMove(gameId: string) {
  const storeLatestPosition = useStoreLatestPosition(gameId);
  const refreshGame = useRefreshGame(gameId);

  return useMutation({
    mutationFn: async (body: MoveCreate) =>
      unwrap(
        await api.POST("/api/games/{game_id}/moves", {
          params: { path: { game_id: gameId } },
          body,
        }),
      ) as GamePosition,
    onSuccess: storeLatestPosition,
    onError: refreshGame,
  });
}

/**
 * Confirm that the pending agent move, the last move at `expectedPly`, was made on the
 * physical board, returning the new position.
 */
export function useConfirmMove(gameId: string) {
  const storeLatestPosition = useStoreLatestPosition(gameId);
  const refreshGame = useRefreshGame(gameId);

  return useMutation({
    mutationFn: async (expectedPly: number) =>
      unwrap(
        await api.POST("/api/games/{game_id}/moves/last/confirm", {
          params: { path: { game_id: gameId } },
          body: { expected_ply: expectedPly },
        }),
      ) as GamePosition,
    onSuccess: storeLatestPosition,
    onError: refreshGame,
  });
}

interface UndoRequest {
  /** The ply the game must be at, which is the `ply_count` of the position shown. */
  expectedPly: number;
  /** How many moves to take back, one after another. */
  plies: number;
}

/**
 * Undo the last moves if the game is at the expected ply, returning the new position.
 *
 * Several plies are undone in one mutation, so nothing reacts to the positions between.
 */
export function useUndoMove(gameId: string) {
  const storeLatestPosition = useStoreLatestPosition(gameId);
  const refreshGame = useRefreshGame(gameId);

  return useMutation({
    mutationFn: async ({ expectedPly, plies }: UndoRequest) => {
      let position: GamePosition | null = null;

      for (let ply = expectedPly; ply > expectedPly - plies; ply--) {
        position = unwrap(
          await api.DELETE("/api/games/{game_id}/moves/last", {
            params: { path: { game_id: gameId }, query: { expected_ply: ply } },
          }),
        ) as GamePosition;
      }

      if (position === null) {
        throw new Error("There is no move to undo.");
      }

      return position;
    },
    onSuccess: storeLatestPosition,
    onError: refreshGame,
  });
}
