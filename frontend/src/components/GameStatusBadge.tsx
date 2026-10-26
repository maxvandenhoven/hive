import type { GameSummary } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { describeGameStatus } from "@/lib/players";

const STATUS_VARIANTS = {
  active: "default",
  finished: "secondary",
  abandoned: "outline",
} as const;

export function GameStatusBadge({
  game,
}: {
  game: Pick<GameSummary, "status" | "result">;
}) {
  return <Badge variant={STATUS_VARIANTS[game.status]}>{describeGameStatus(game)}</Badge>;
}
