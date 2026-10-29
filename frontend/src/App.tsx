import { QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router";

import { createQueryClient } from "@/api/queryClient";
import { AppLayout } from "@/components/AppLayout";
import { GamePage } from "@/pages/GamePage";
import { GamesPage } from "@/pages/GamesPage";
import { HelpPage } from "@/pages/HelpPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { RulesPage } from "@/pages/RulesPage";

const router = createBrowserRouter([
  {
    element: <AppLayout />,
    children: [
      { path: "/", element: <GamesPage /> },
      { path: "/games/:gameId", element: <GamePage /> },
      { path: "/help", element: <HelpPage /> },
      { path: "/rules", element: <RulesPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

const queryClient = createQueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
