import { useState } from "react";

import {
  readDismissedTips,
  readTipsSetting,
  recordTipsGame,
  writeDismissedTips,
  writeTipsSetting,
} from "@/lib/tips";
import type { GameScenario } from "@/lib/players";

/** Whether tips show in a game, and the tips dismissed, remembered per device. */
export interface BoardTipsState {
  enabled: boolean;
  dismissed: string[];
  toggle: () => void;
  dismiss: (id: string) => void;
}

/**
 * The board tips of a game, on during the first games of each scenario until the Tips
 * setting is chosen, then as chosen.
 */
export function useBoardTips(scenario: GameScenario, gameId: string): BoardTipsState {
  const [firstGame] = useState(() => recordTipsGame(scenario, gameId));
  const [setting, setSetting] = useState(readTipsSetting);
  const [dismissed, setDismissed] = useState(readDismissedTips);
  const enabled = setting ?? firstGame;

  return {
    enabled,
    dismissed,
    toggle: () => {
      setSetting(!enabled);
      writeTipsSetting(!enabled);
    },
    dismiss: (id) => {
      const next = [...dismissed, id];
      setDismissed(next);
      writeDismissedTips(next);
    },
  };
}
