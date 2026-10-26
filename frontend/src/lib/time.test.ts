import { describe, expect, it } from "vitest";

import { formatRelativeTime } from "@/lib/time";

const NOW = new Date("2026-10-26T12:00:00Z");

describe("formatRelativeTime", () => {
  it.each([
    ["2026-10-26T11:59:30Z", "just now"],
    ["2026-10-26T11:55:00Z", "5 minutes ago"],
    ["2026-10-26T09:00:00Z", "3 hours ago"],
    ["2026-10-25T12:00:00Z", "yesterday"],
    ["2026-09-26T12:00:00Z", "last month"],
  ])("describes %s as %s", (iso, expected) => {
    expect(formatRelativeTime(iso, NOW)).toBe(expected);
  });
});
