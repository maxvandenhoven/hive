import { HexagonIcon } from "lucide-react";
import { Link, Outlet } from "react-router";

import { Toaster } from "@/components/ui/sonner";

/** The header and page frame shared by every page. */
export function AppLayout() {
  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="border-b">
        <div className="mx-auto flex h-14 max-w-5xl items-center px-4">
          <Link
            to="/"
            className="flex items-center gap-2 font-heading text-lg font-semibold"
          >
            <HexagonIcon className="size-5" />
            Hive
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">
        <Outlet />
      </main>
      <Toaster position="top-center" />
    </div>
  );
}
