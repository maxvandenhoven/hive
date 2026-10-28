import { BotIcon, EyeIcon, LightbulbIcon, type LucideIcon } from "lucide-react";

import type { GameScenario } from "@/lib/players";

/** The icon of each scenario, shared by the new game flow and the game list. */
export const GAME_SCENARIO_ICONS: Record<GameScenario, LucideIcon> = {
  agent: BotIcon,
  hints: LightbulbIcon,
  watch: EyeIcon,
};
