import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type GameCreate, type GameUpdate } from "@/api/client";

/** The query keys, so related queries are refreshed together. */
export const queryKeys = {
  agentKinds: ["agents"] as const,
  games: ["games"] as const,
  gamePage: (limit: number, offset: number) => ["games", "page", limit, offset] as const,
  game: (gameId: string) => ["games", "detail", gameId] as const,
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
      ),
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
