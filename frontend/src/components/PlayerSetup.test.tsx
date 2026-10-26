import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { PlayerSetup } from "@/components/PlayerSetup";
import { agentDraft, HUMAN_DRAFT, type PlayerDraft } from "@/lib/players";
import { AGENT_KINDS } from "@/test/fixtures";

const [negamax] = AGENT_KINDS;

if (negamax === undefined) {
  throw new Error("The fixtures have no agent kinds.");
}

/** Render the setup of white with its draft in state, reporting every change. */
function renderSetup(initial: PlayerDraft, { allowHuman = true } = {}) {
  const onChange = vi.fn<(draft: PlayerDraft) => void>();

  function Harness() {
    const [draft, setDraft] = useState(initial);

    return (
      <PlayerSetup
        side="white"
        value={draft}
        agentKinds={AGENT_KINDS}
        allowHuman={allowHuman}
        onChange={(next) => {
          onChange(next);
          setDraft(next);
        }}
      />
    );
  }

  render(<Harness />);

  return { onChange, user: userEvent.setup() };
}

async function choose(
  user: ReturnType<typeof userEvent.setup>,
  label: string,
  option: string,
): Promise<void> {
  await user.click(screen.getByRole("combobox", { name: label }));
  await user.click(screen.getByRole("option", { name: option }));
}

describe("PlayerSetup", () => {
  it("shows a human side without agent settings", () => {
    renderSetup(HUMAN_DRAFT);

    expect(screen.getByRole("group", { name: "White" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Player" })).toHaveTextContent("Human");
    expect(screen.queryByRole("combobox", { name: "Agent" })).not.toBeInTheDocument();
  });

  it("switches to the first agent with its default params", async () => {
    const { onChange, user } = renderSetup(HUMAN_DRAFT);

    await choose(user, "Player", "Agent");

    expect(onChange).toHaveBeenLastCalledWith(agentDraft(negamax));
    expect(screen.getByRole("combobox", { name: "Agent" })).toHaveTextContent("negamax");
    expect(screen.getByRole("textbox", { name: "Budget (s)" })).toHaveValue("5");
    expect(screen.getByRole("textbox", { name: "Depth" })).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "Queen Safety" })).toHaveValue("1");
    expect(screen.getByText(/search until stopped/)).toBeInTheDocument();
  });

  it("does not offer a human when the other side is human", async () => {
    const { user } = renderSetup(agentDraft(negamax), { allowHuman: false });

    await user.click(screen.getByRole("combobox", { name: "Player" }));

    expect(screen.getByRole("option", { name: "Human" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("edits params and shows invalid values", async () => {
    const { onChange, user } = renderSetup(agentDraft(negamax));
    const depth = screen.getByRole("textbox", { name: "Depth" });

    await user.type(depth, "0");

    expect(depth).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Must be at least 1.")).toBeInTheDocument();

    await user.clear(depth);
    await user.type(depth, "3");

    expect(screen.queryByText("Must be at least 1.")).not.toBeInTheDocument();
    expect(onChange.mock.lastCall?.[0]).toMatchObject({
      params: { depth: "3", queen_safety: "1" },
    });
  });

  it("checks the budget", async () => {
    const { user } = renderSetup(agentDraft(negamax));
    const budget = screen.getByRole("textbox", { name: "Budget (s)" });

    await user.clear(budget);

    expect(screen.getByText("Must be a positive number of seconds.")).toBeInTheDocument();
  });

  it("resets the params when the kind changes, keeping budget and label", async () => {
    const { onChange, user } = renderSetup(agentDraft(negamax));

    await user.type(screen.getByRole("textbox", { name: "Label" }), "quick");
    await choose(user, "Agent", "random");

    expect(onChange).toHaveBeenLastCalledWith({
      type: "agent",
      kind: "random",
      label: "quick",
      budget: "5",
      params: {},
    });
    expect(screen.queryByRole("textbox", { name: "Depth" })).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("group", { name: "White" })).getByText(
        /uniformly at random/,
      ),
    ).toBeInTheDocument();
  });
});
