import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { AgentChoiceField } from "@/components/AgentChoiceField";
import type { AgentChoice, NewGameAgents } from "@/lib/newGame";
import { agentDraft } from "@/lib/players";
import { AGENT_KINDS, AGENT_PRESETS } from "@/test/fixtures";

const AGENTS: NewGameAgents = { presets: AGENT_PRESETS, agentKinds: AGENT_KINDS };
const [negamax] = AGENT_KINDS;

if (negamax === undefined) {
  throw new Error("The fixtures have no agent kinds.");
}

/** Render the field with its choice in state, reporting every change. */
function renderField(initial: AgentChoice) {
  const onChange = vi.fn<(choice: AgentChoice) => void>();

  function Harness() {
    const [choice, setChoice] = useState(initial);

    return (
      <AgentChoiceField
        label="Opponent"
        value={choice}
        agents={AGENTS}
        onChange={(next) => {
          onChange(next);
          setChoice(next);
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

describe("AgentChoiceField", () => {
  it("offers the presets as named strengths", async () => {
    const { onChange, user } = renderField({ mode: "preset", preset: "nm3" });

    expect(screen.getByRole("combobox", { name: "Opponent" })).toHaveTextContent("nm3");
    expect(screen.getByText(/slower and stronger/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Agent" })).not.toBeInTheDocument();

    await choose(user, "Opponent", "nm2");

    expect(onChange).toHaveBeenLastCalledWith({ mode: "preset", preset: "nm2" });
    expect(screen.getByText(/easy to beat/)).toBeInTheDocument();
  });

  it("opens the advanced form from the preset", async () => {
    const { onChange, user } = renderField({ mode: "preset", preset: "nm2" });

    await choose(user, "Opponent", "Advanced…");

    expect(onChange).toHaveBeenLastCalledWith({
      mode: "advanced",
      draft: agentDraft(negamax, { params: { depth: 2 } }),
    });
    expect(screen.getByRole("combobox", { name: "Agent" })).toHaveTextContent("negamax");
    expect(screen.getByRole("textbox", { name: "Budget (s)" })).toHaveValue("5");
    expect(screen.getByRole("textbox", { name: "Depth" })).toHaveValue("2");
    expect(screen.getByRole("textbox", { name: "Queen Safety" })).toHaveValue("1");
  });

  it("edits params and the budget and shows invalid values", async () => {
    const { onChange, user } = renderField({
      mode: "advanced",
      draft: agentDraft(negamax),
    });
    const depth = screen.getByRole("textbox", { name: "Depth" });

    await user.type(depth, "0");

    expect(depth).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Must be at least 1.")).toBeInTheDocument();

    await user.clear(depth);
    await user.type(depth, "3");
    await user.clear(screen.getByRole("textbox", { name: "Budget (s)" }));

    expect(screen.queryByText("Must be at least 1.")).not.toBeInTheDocument();
    expect(screen.getByText("Must be a positive number of seconds.")).toBeInTheDocument();
    expect(onChange.mock.lastCall?.[0]).toMatchObject({
      mode: "advanced",
      draft: { params: { depth: "3", queen_safety: "1" }, budget: "" },
    });
  });

  it("resets the params when the kind changes, keeping budget and label", async () => {
    const { onChange, user } = renderField({
      mode: "advanced",
      draft: agentDraft(negamax),
    });

    await user.type(screen.getByRole("textbox", { name: "Label" }), "quick");
    await choose(user, "Agent", "random");

    expect(onChange).toHaveBeenLastCalledWith({
      mode: "advanced",
      draft: { type: "agent", kind: "random", label: "quick", budget: "5", params: {} },
    });
    expect(screen.queryByRole("textbox", { name: "Depth" })).not.toBeInTheDocument();
    expect(screen.getByText(/uniformly at random/)).toBeInTheDocument();
  });

  it("goes back to a preset", async () => {
    const { onChange, user } = renderField({
      mode: "advanced",
      draft: agentDraft(negamax),
    });

    await choose(user, "Opponent", "nm3");

    expect(onChange).toHaveBeenLastCalledWith({ mode: "preset", preset: "nm3" });
    expect(screen.queryByRole("combobox", { name: "Agent" })).not.toBeInTheDocument();
  });
});
