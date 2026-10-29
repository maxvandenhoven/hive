import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { boardTips, describeGameHelp } from "@/lib/gameHelp";
import { HELP_SECTIONS, RULES_PATH, RULES_SECTIONS } from "@/lib/help";
import type { TurnPromptKind } from "@/lib/turnPrompt";
import { HelpPage } from "@/pages/HelpPage";
import { RulesPage } from "@/pages/RulesPage";
import { gameDetail, gamePosition } from "@/test/fixtures";
import { renderPage } from "@/test/render";

const PROMPT_KINDS: TurnPromptKind[] = [
  "replay",
  "pending",
  "over",
  "abandoned",
  "watching",
  "thinking",
  "failed",
  "turn",
];

/** The id of the section a help link points to on its page, such as `controls`. */
function anchorOf(link: string, page: string): string | null {
  const [path, hash] = link.split("#");

  return path === page && hash !== undefined ? hash : null;
}

describe("HelpPage", () => {
  it("has an anchor for every help section", () => {
    renderPage(<HelpPage />, { path: "/help", route: "/help" });

    for (const { id, title } of HELP_SECTIONS) {
      expect(document.getElementById(id)).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    }
  });

  it("explains the colours, closing a game and hints", () => {
    renderPage(<HelpPage />, { path: "/help", route: "/help" });

    expect(screen.getByRole("list", { name: "The marks" })).toBeInTheDocument();
    expect(
      screen.getByText(/Closing the page while an agent thinks/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Press Hint on your turn/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Read the rules" })).toHaveAttribute(
      "href",
      RULES_PATH,
    );
  });

  it("links from contextual help to existing anchors", () => {
    const game = gameDetail({ board_location: "screen" });
    const links = PROMPT_KINDS.flatMap((kind) => {
      const options = { game, position: gamePosition(), kind };

      return [
        describeGameHelp(options).to,
        ...boardTips({ ...options, hintAvailable: true }).flatMap((tip) =>
          tip.link ? [tip.link.to] : [],
        ),
      ];
    });
    const helpIds = new Set(HELP_SECTIONS.map(({ id }) => id as string));
    const rulesIds = new Set(RULES_SECTIONS.map(({ id }) => id as string));

    for (const link of links) {
      const helpAnchor = anchorOf(link, "/help");
      const rulesAnchor = anchorOf(link, RULES_PATH);

      expect(
        (helpAnchor !== null && helpIds.has(helpAnchor)) ||
          (rulesAnchor !== null && rulesIds.has(rulesAnchor)),
      ).toBe(true);
    }
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
