import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { createMemoryRouter, RouterProvider, useParams } from "react-router";

import { createQueryClient } from "@/api/queryClient";
import { Toaster } from "@/components/ui/sonner";

function GameRoute() {
  const { gameId } = useParams();

  return <p>Game page {gameId}</p>;
}

/** A fresh query client that does not retry failed queries. */
export function createTestQueryClient(): QueryClient {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });

  return queryClient;
}

/**
 * Render a page with a fresh query client, a router and the toaster.
 *
 * The page is shown at `route` and opened at `path`; other game pages show a stand-in
 * and `/` a heading.
 */
export function renderPage(
  page: ReactElement,
  { path = "/", route = "/" }: { path?: string; route?: string } = {},
) {
  const queryClient = createTestQueryClient();
  const router = createMemoryRouter(
    [
      { path: route, element: page },
      { path: "/games/:gameId", element: <GameRoute /> },
      { path: "/", element: <h1>Games</h1> },
    ],
    { initialEntries: [path] },
  );

  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>,
  );
}

/** Render a hook with a fresh query client and the toaster. */
export function renderQueryHook<Result, Props>(
  hook: (props: Props) => Result,
  { initialProps }: { initialProps: Props },
) {
  const queryClient = createTestQueryClient();

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        {children}
        <Toaster />
      </QueryClientProvider>
    );
  }

  return renderHook(hook, { initialProps, wrapper: Wrapper });
}
