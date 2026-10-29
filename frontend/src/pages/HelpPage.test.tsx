import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HELP_PATH, HELP_SECTIONS, RULES_PATH, RULES_SECTIONS } from "@/lib/help";
import { GamesPage } from "@/pages/GamesPage";
import { HelpPage } from "@/pages/HelpPage";
import { RulesPage } from "@/pages/RulesPage";
import { mockApi } from "@/test/api";
import { renderPage } from "@/test/render";

describe("HelpPage", () => {
  it("has an anchor and a section link for every section", () => {
    renderPage(<HelpPage />, { path: HELP_PATH, route: HELP_PATH });
    const nav = within(screen.getByRole("navigation", { name: "Help sections" }));

    for (const { id, title } of HELP_SECTIONS) {
      expect(document.getElementById(id)).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
      expect(nav.getByRole("link", { name: title })).toHaveAttribute("href", `#${id}`);
    }
  });

  it("explains the colours, closing a game and hints", () => {
    renderPage(<HelpPage />, { path: HELP_PATH, route: HELP_PATH });

    expect(screen.getByRole("list", { name: "The marks" })).toBeInTheDocument();
    expect(
      screen.getByText(/Closing the page while an agent thinks/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Press Hint on your turn/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "rules page" })).toHaveAttribute(
      "href",
      RULES_PATH,
    );
  });
});

describe("RulesPage", () => {
  it("has an anchor and a section link for every rule section", () => {
    renderPage(<RulesPage />, { path: RULES_PATH, route: RULES_PATH });
    const nav = within(screen.getByRole("navigation", { name: "Rule sections" }));

    for (const { id, title } of RULES_SECTIONS) {
      expect(document.getElementById(id)).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
      expect(nav.getByRole("link", { name: title })).toHaveAttribute("href", `#${id}`);
    }
  });
});

describe("GamesPage help cards", () => {
  it("links to the rules and to how the app works", () => {
    mockApi({
      "GET /api/games": () => ({ body: { items: [], total: 0, limit: 20, offset: 0 } }),
    });
    renderPage(<GamesPage />);
    const help = within(screen.getByRole("navigation", { name: "Help" }));

    expect(help.getByRole("link", { name: /Game rules/ })).toHaveAttribute(
      "href",
      RULES_PATH,
    );
    expect(help.getByRole("link", { name: /How the app works/ })).toHaveAttribute(
      "href",
      HELP_PATH,
    );
  });
});
