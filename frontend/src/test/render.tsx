import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider, useParams } from "react-router";

import { createQueryClient } from "@/api/queryClient";
import { Toaster } from "@/components/ui/sonner";

function GameRoute() {
  const { gameId } = useParams();

  return <p>Game page {gameId}</p>;
}

/** Render a page at `/` with a fresh query client, a router and the toaster. */
export function renderPage(page: ReactElement, { path = "/" }: { path?: string } = {}) {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false } });
  const router = createMemoryRouter(
    [
      { path: "/", element: page },
      { path: "/games/:gameId", element: <GameRoute /> },
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
