import { useEffect, useState } from "react";

/** How often the time left is redrawn, in milliseconds. */
const CLOCK_INTERVAL_MS = 100;

/**
 * The seconds an agent has left of its budget, counting down from `startedAt`, or the
 * whole budget while it has not started.
 */
export function useSecondsLeft(startedAt: number | null, budgetS: number): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const interval = setInterval(() => {
      setNow(Date.now());
    }, CLOCK_INTERVAL_MS);

    return () => {
      clearInterval(interval);
    };
  }, []);

  return startedAt === null ? budgetS : Math.max(0, budgetS - (now - startedAt) / 1000);
}
