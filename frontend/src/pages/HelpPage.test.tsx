import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  HELP_PATH,
  HELP_SECTIONS,
  helpTextMatches,
  RULES_PATH,
  RULES_SECTIONS,
} from "@/lib/help";
import { GamesPage } from "@/pages/GamesPage";
import { HelpPage } from "@/pages/HelpPage";
import { RulesPage } from "@/pages/RulesPage";
import { mockApi } from "@/test/api";
import { renderPage } from "@/test/render";

describe("HelpPage", () => {
  it("has an anchor for every section", () => {
    renderPage(<HelpPage />, { path: HELP_PATH, route: HELP_PATH });

    for (const { id, title } of HELP_SECTIONS) {
      expect(document.getElementById(id)).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
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
  it("has an anchor for every rule section", () => {
    renderPage(<RulesPage />, { path: RULES_PATH, route: RULES_PATH });

    for (const { id, title } of RULES_SECTIONS) {
      expect(document.getElementById(id)).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    }
  });
});

describe("help search", () => {
  it("shows only the sections with every word searched for", async () => {
    const user = userEvent.setup();
    renderPage(<RulesPage />, { path: RULES_PATH, route: RULES_PATH });

    await user.type(screen.getByRole("searchbox", { name: "Search the rules" }), "Climb");

    expect(screen.getByRole("heading", { name: "Beetle" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Spider" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Nothing matches/)).not.toBeVisible();

    await user.type(screen.getByRole("searchbox"), " pins");

    expect(screen.getByRole("heading", { name: "Beetle" })).toBeVisible();

    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "mosquito");

    expect(screen.queryByRole("heading", { name: "Beetle" })).not.toBeInTheDocument();
    expect(screen.getByText("Nothing matches “mosquito”.")).toBeVisible();

    await user.clear(screen.getByRole("searchbox"));

    expect(
      RULES_SECTIONS.map(({ title }) => screen.getByRole("heading", { name: title })),
    ).toHaveLength(RULES_SECTIONS.length);
  });
});

describe("helpTextMatches", () => {
  it("needs every word, in any case and order", () => {
    expect(helpTextMatches("The beetle climbs onto the hive", "HIVE beetle")).toBe(true);
    expect(helpTextMatches("The beetle climbs onto the hive", "beetle ant")).toBe(false);
    expect(helpTextMatches("Anything", "  ")).toBe(true);
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
