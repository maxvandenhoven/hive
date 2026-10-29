import { render, renderHook, act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { BoardTips, TipsToggle } from "@/components/BoardTips";
import { useBoardTips } from "@/components/useBoardTips";
import type { BoardTip } from "@/lib/gameHelp";
import { FIRST_GAMES_WITH_TIPS, TIPS_SETTING_KEY } from "@/lib/tips";

const TIPS: BoardTip[] = [
  { id: "tap-movable", text: "Tap a piece with a blue ring to see where it can go." },
  { id: "ask-hint", text: "Press Hint for a suggestion." },
];

function TipsHarness({ gameId }: { gameId: string }) {
  const state = useBoardTips("agent", gameId);

  return (
    <MemoryRouter>
      <TipsToggle state={state} />
      <BoardTips tips={TIPS} state={state} />
    </MemoryRouter>
  );
}

describe("useBoardTips", () => {
  it("shows tips during the first games of a scenario only", () => {
    for (let index = 0; index < FIRST_GAMES_WITH_TIPS; index += 1) {
      const { result } = renderHook(() => useBoardTips("agent", `game-${index}`));
      expect(result.current.enabled).toBe(true);
    }

    expect(renderHook(() => useBoardTips("agent", "late")).result.current.enabled).toBe(
      false,
    );
    expect(renderHook(() => useBoardTips("agent", "game-0")).result.current.enabled).toBe(
      true,
    );
    expect(renderHook(() => useBoardTips("watch", "late")).result.current.enabled).toBe(
      true,
    );
  });

  it("remembers the Tips toggle per device", () => {
    const { result } = renderHook(() => useBoardTips("agent", "game"));

    act(() => {
      result.current.toggle();
    });

    expect(result.current.enabled).toBe(false);
    expect(window.localStorage.getItem(TIPS_SETTING_KEY)).toBe("false");
    expect(renderHook(() => useBoardTips("hints", "other")).result.current.enabled).toBe(
      false,
    );
  });
});

describe("BoardTips", () => {
  it("dismisses a tip for good", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<TipsHarness gameId="game" />);

    await user.click(
      screen.getByRole("button", { name: `Dismiss the tip ${TIPS[1]?.text}` }),
    );

    expect(screen.queryByText("Press Hint for a suggestion.")).not.toBeInTheDocument();

    unmount();
    render(<TipsHarness gameId="game" />);

    expect(screen.getByText(/Tap a piece with a blue ring/)).toBeInTheDocument();
    expect(screen.queryByText("Press Hint for a suggestion.")).not.toBeInTheDocument();
  });

  it("hides every tip when turned off, also after a reload", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<TipsHarness gameId="game" />);

    await user.click(screen.getByRole("button", { name: "Tips" }));

    expect(screen.queryByRole("list", { name: "Tips" })).not.toBeInTheDocument();

    unmount();
    render(<TipsHarness gameId="game" />);

    expect(screen.getByRole("button", { name: "Tips" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.queryByRole("list", { name: "Tips" })).not.toBeInTheDocument();
  });
});
