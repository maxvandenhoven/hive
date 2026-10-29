import { within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { formatHex } from "@/components/board/hex";
import { RULES_PATH } from "@/lib/help";
import {
  describeDiagram,
  diagramSteps,
  RULES_DIAGRAMS,
  rulesDiagram,
} from "@/lib/rulesDiagrams";
import { toBoardView } from "@/lib/moves";
import { RulesPage } from "@/pages/RulesPage";
import { renderPage } from "@/test/render";

describe("RulesDiagram", () => {
  it("renders every diagram once on the rules page", () => {
    const { container } = renderPage(<RulesPage />, {
      path: RULES_PATH,
      route: RULES_PATH,
    });
    const rendered = [...container.querySelectorAll("[data-diagram]")].map((element) =>
      element.getAttribute("data-diagram"),
    );

    expect(rendered.toSorted()).toEqual(RULES_DIAGRAMS.map(({ id }) => id).toSorted());
  });

  it("draws the allowed and forbidden targets", () => {
    const { container } = renderPage(<RulesPage />, {
      path: RULES_PATH,
      route: RULES_PATH,
    });
    const gate = rulesDiagram("freedom-gate");
    const figure = container.querySelector('[data-diagram="freedom-gate"]');

    expect(figure).not.toBeNull();

    const board = within(figure as HTMLElement).getByRole("group", { name: "Board" });

    for (const coord of gate.allowed) {
      expect(
        within(board).getByRole("button", { name: `Play to ${formatHex(coord)}` }),
      ).toBeInTheDocument();
    }

    expect(board.querySelectorAll('[data-mark="forbidden"]')).toHaveLength(
      gate.forbidden.length,
    );
  });

  it("steps through the move of a diagram with a path", async () => {
    const user = userEvent.setup();
    const { container } = renderPage(<RulesPage />, {
      path: RULES_PATH,
      route: RULES_PATH,
    });
    const figure = container.querySelector('[data-diagram="spider"]') as HTMLElement;

    expect(within(figure).getByText("Step 0 of 3")).toBeInTheDocument();

    await user.click(within(figure).getByRole("button", { name: "Next step" }));

    expect(within(figure).getByText("Step 1 of 3")).toBeInTheDocument();
    expect(
      within(figure).getByRole("img", { name: "White spider at (0, -1)" }),
    ).toBeInTheDocument();
  });
});

describe("diagramSteps", () => {
  it("moves the top piece along the path, onto stacks too", () => {
    const climb = rulesDiagram("beetle-climb");
    const steps = diagramSteps(toBoardView(climb.board), climb.path);

    expect(steps).toHaveLength(1);
    expect(steps[0]?.lastMove).toEqual({ from: [0, 0], to: [1, 0] });
    expect(
      steps[0]?.board.find((stack) => stack.coord[0] === 1 && stack.coord[1] === 0)
        ?.pieces,
    ).toEqual([
      { piece: "beetle", owner: "white" },
      { piece: "queen", owner: "black" },
    ]);
  });
});

describe("describeDiagram", () => {
  it("names the move, a pass and the result", () => {
    expect(describeDiagram(rulesDiagram("placement-own-colour"))).toBe(
      "White places a spider",
    );
    expect(describeDiagram(rulesDiagram("spider"))).toBe("White moves the spider");
    expect(describeDiagram(rulesDiagram("pass"))).toBe("White must pass");
    expect(describeDiagram(rulesDiagram("goal"))).toBe("White wins");
    expect(describeDiagram(rulesDiagram("draw"))).toBe("Draw");
  });
});
