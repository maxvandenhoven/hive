import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { HandTray } from "@/components/HandTray";

function marksOf(name: string): string[] {
  return [...screen.getByRole("button", { name }).querySelectorAll("[data-mark]")].map(
    (mark) => mark.getAttribute("data-mark") ?? "",
  );
}

describe("HandTray", () => {
  it("marks placeable, selected and suggested pieces as the board does", () => {
    render(
      <HandTray
        side="white"
        player={{ type: "human" }}
        hand={{ queen: 1, ant: 3, beetle: 2 }}
        placeable={["queen", "ant"]}
        selected="ant"
        suggested="queen"
        suggestionShown={false}
        toMove
        onSelect={vi.fn()}
      />,
    );

    expect(marksOf("Place white queen, 1 left")).toEqual([
      "movable",
      "movable",
      "suggestion",
    ]);
    expect(marksOf("Place white ant, 3 left")).toEqual([
      "selected",
      "movable",
      "movable",
    ]);
    expect(marksOf("Place white beetle, 2 left")).toEqual([]);
    expect(
      screen.getByRole("button", { name: "Place white ant, 3 left" }),
    ).toHaveAttribute("aria-pressed", "true");
  });
});
