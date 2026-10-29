import { CircleHelpIcon, HexagonIcon } from "lucide-react";
import { Link, Outlet } from "react-router";

import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/sonner";

/** The width of the header and page content: a desktop screen, one column on a phone. */
const FRAME_CLASSES = "mx-auto w-full max-w-7xl xl:max-w-[96rem] px-4 sm:px-6";

/** The header and page frame shared by every page. */
export function AppLayout() {
  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="bg-header text-header-foreground shadow-sm">
        <div className={`${FRAME_CLASSES} flex h-14 items-center justify-between gap-4`}>
          <Link
            to="/"
            className="flex items-center gap-2 rounded-md font-heading text-lg font-semibold tracking-tight"
          >
            <HexagonIcon className="size-6 fill-primary text-primary" />
            Hive
          </Link>
          <div className="flex items-center gap-2" data-slot="header-actions">
            <Button
              variant="ghost"
              asChild
              className="text-header-foreground hover:bg-header-foreground/10 hover:text-header-foreground"
            >
              <Link to="/help">
                <CircleHelpIcon />
                Help
              </Link>
            </Button>
          </div>
        </div>
      </header>
      <main className={`${FRAME_CLASSES} py-6`}>
        <Outlet />
      </main>
      <Toaster position="top-center" />
    </div>
  );
}
