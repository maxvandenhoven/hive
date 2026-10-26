import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ReplayControls } from "@/components/ReplayControls";

/** Render the controls with the shown ply in state, reporting every change. */
function renderControls(initial: number | null, plyCount = 5) {
  const onChange = vi.fn<(ply: number | null) => void>();

  function Harness() {
    const [ply, setPly] = useState(initial);

    return (
      <ReplayControls
        ply={ply}
        plyCount={plyCount}
        onChange={(next) => {
          onChange(next);
          setPly(next);
        }}
      />
    );
  }

  render(<Harness />);

  return { onChange, user: userEvent.setup() };
}

function button(name: string): HTMLElement {
  return screen.getByRole("button", { name });
}

describe("ReplayControls", () => {
  it("shows the live position with only the way back open", () => {
    renderControls(null);

    expect(screen.getByText("Live · ply 5")).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Ply" })).toHaveAttribute(
      "aria-valuenow",
      "5",
    );
    expect(button("Next position")).toBeDisabled();
    expect(button("Live position")).toBeDisabled();
    expect(button("Previous position")).toBeEnabled();
  });

  it("steps back to the start and forward to the live position", async () => {
    const { onChange, user } = renderControls(null, 2);

    await user.click(button("Previous position"));

    expect(screen.getByText("Replay · ply 1 of 2")).toBeInTheDocument();

    await user.click(button("First position"));

    expect(button("Previous position")).toBeDisabled();

    await user.click(button("Next position"));
    await user.click(button("Next position"));

    expect(onChange.mock.calls).toEqual([[1], [0], [1], [null]]);
    expect(screen.getByText("Live · ply 2")).toBeInTheDocument();
  });

  it("jumps to the live position", async () => {
    const { onChange, user } = renderControls(2);

    await user.click(button("Live position"));

    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("scrubs with the slider keys", async () => {
    const { onChange, user } = renderControls(3);
    screen.getByRole("slider", { name: "Ply" }).focus();

    await user.keyboard("{ArrowLeft}");
    await user.keyboard("{End}");

    expect(onChange.mock.calls).toEqual([[2], [null]]);
  });

  it("has nothing to replay without moves", () => {
    renderControls(null, 0);

    expect(button("Previous position")).toBeDisabled();
    expect(button("First position")).toBeDisabled();
  });
});
