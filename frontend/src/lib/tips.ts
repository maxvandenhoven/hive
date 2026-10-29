/*
 * What the board tips remember per device (`localStorage`), namely the Tips setting, the
 * first games of each scenario, which show tips until the setting is chosen, and the
 * tips dismissed. Without storage tips show and are forgotten.
 */
import type { GameScenario } from "@/lib/players";

/** Where the Tips setting is remembered, `true` or `false`, absent before it is chosen. */
export const TIPS_SETTING_KEY = "hive.tips.setting";

/** Where the ids of the first games of each scenario are remembered. */
export const TIPS_GAMES_KEY = "hive.tips.games";

/** Where the ids of dismissed tips are remembered. */
export const TIPS_DISMISSED_KEY = "hive.tips.dismissed";

/** The number of games in each scenario that show tips until the setting is chosen. */
export const FIRST_GAMES_WITH_TIPS = 3;

function readJson<Value>(key: string, fallback: Value): Value {
  try {
    const value = window.localStorage.getItem(key);

    return value === null ? fallback : (JSON.parse(value) as Value);
  } catch {
    return fallback;
  }
}

function write(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Without storage the tips just forget.
  }
}

/** The Tips setting chosen on this device, or `null` before it is chosen. */
export function readTipsSetting(): boolean | null {
  const setting = readJson<unknown>(TIPS_SETTING_KEY, null);

  return typeof setting === "boolean" ? setting : null;
}

/** Remember the Tips setting on this device. */
export function writeTipsSetting(enabled: boolean) {
  write(TIPS_SETTING_KEY, JSON.stringify(enabled));
}

/**
 * Whether a game is one of the first games of its scenario on this device, remembering
 * it when there is still room. Asking again for the same game gives the same answer.
 */
export function recordTipsGame(scenario: GameScenario, gameId: string): boolean {
  const games = readJson<Partial<Record<GameScenario, string[]>>>(TIPS_GAMES_KEY, {});
  const ids = Array.isArray(games[scenario]) ? games[scenario] : [];

  if (ids.includes(gameId)) {
    return true;
  }

  if (ids.length >= FIRST_GAMES_WITH_TIPS) {
    return false;
  }

  write(TIPS_GAMES_KEY, JSON.stringify({ ...games, [scenario]: [...ids, gameId] }));

  return true;
}

/** The ids of the tips dismissed on this device. */
export function readDismissedTips(): string[] {
  const ids = readJson<unknown>(TIPS_DISMISSED_KEY, []);

  return Array.isArray(ids) ? ids.filter((id) => typeof id === "string") : [];
}

/** Remember that a tip was dismissed on this device. */
export function writeDismissedTips(ids: string[]) {
  write(TIPS_DISMISSED_KEY, JSON.stringify(ids));
}
