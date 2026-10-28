import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { BoardLegend, LEGEND_STORAGE_KEY } from "@/components/board/BoardLegend";
import { BOARD_MARKS } from "@/components/board/boardMarks";

function labels(list: string): string[] {
  return within(screen.getByRole("list", { name: list }))
    .getAllByRole("listitem")
    .map((item) => item.querySelector(".font-medium")?.textContent ?? "");
}

describe("BoardLegend", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("starts closed and opens with the Key button", async () => {
    const user = userEvent.setup();
    render(<BoardLegend shown={[]} />);

    expect(screen.queryByRole("region", { name: "Board key" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Key" }));

    expect(screen.getByRole("region", { name: "Board key" })).toBeInTheDocument();
    expect(labels("Marks")).toEqual(BOARD_MARKS.map(({ label }) => label));
  });

  it("lists the marks on the board first, then the rest", () => {
    window.localStorage.setItem(LEGEND_STORAGE_KEY, "true");
    render(<BoardLegend shown={["target", "lastMove"]} />);

    expect(labels("On the board")).toEqual(["Can go here", "Last move"]);
    expect(labels("Other marks")).toEqual([
      "Can move",
      "Selected",
      "Can climb on top",
      "Agent suggestion",
      "Not allowed",
    ]);
  });

  it("draws a swatch for every mark", () => {
    window.localStorage.setItem(LEGEND_STORAGE_KEY, "true");
    const { container } = render(<BoardLegend shown={[]} />);

    for (const { kind } of BOARD_MARKS) {
      expect(container.querySelector(`svg [data-mark="${kind}"]`)).not.toBeNull();
    }
  });

  it("remembers whether it is open", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<BoardLegend shown={[]} />);

    await user.click(screen.getByRole("button", { name: "Key" }));
    unmount();
    render(<BoardLegend shown={[]} />);

    expect(screen.getByRole("button", { name: "Key" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "Key" }));

    expect(window.localStorage.getItem(LEGEND_STORAGE_KEY)).toBe("false");
  });
});
