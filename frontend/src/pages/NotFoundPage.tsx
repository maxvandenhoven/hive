import { Link } from "react-router";

import { Button } from "@/components/ui/button";

export function NotFoundPage() {
  return (
    <div className="flex flex-col items-start gap-4">
      <h1 className="font-heading text-2xl font-semibold">Page not found</h1>
      <Button variant="outline" asChild>
        <Link to="/">Back to the games</Link>
      </Button>
    </div>
  );
}
