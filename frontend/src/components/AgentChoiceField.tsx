import { useId } from "react";

import { AgentPicker } from "@/components/AgentPicker";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  advancedAgentChoice,
  resolveAgentChoice,
  type AgentChoice,
  type NewGameAgents,
} from "@/lib/newGame";

/** The select value of the advanced form, which no preset name can take. */
const ADVANCED_VALUE = "advanced:";

interface AgentChoiceFieldProps {
  label: string;
  value: AgentChoice;
  agents: NewGameAgents;
  onChange: (choice: AgentChoice) => void;
}

/**
 * Pick an agent from the presets as a named strength, or open **Advanced** for the kind,
 * params, label and budget.
 */
export function AgentChoiceField({
  label,
  value,
  agents,
  onChange,
}: AgentChoiceFieldProps) {
  const selectId = useId();
  const preset =
    value.mode === "preset"
      ? agents.presets.find((candidate) => candidate.name === value.preset)
      : undefined;
  const result = resolveAgentChoice(value, agents);

  const choose = (selected: string) => {
    onChange(
      selected === ADVANCED_VALUE
        ? advancedAgentChoice(value, agents)
        : { mode: "preset", preset: selected },
    );
  };

  return (
    <div className="flex flex-col gap-4">
      <Field>
        <FieldLabel htmlFor={selectId}>{label}</FieldLabel>
        <Select
          value={value.mode === "preset" ? value.preset : ADVANCED_VALUE}
          onValueChange={choose}
        >
          <SelectTrigger id={selectId} className="w-full">
            <SelectValue placeholder="Choose an agent" />
          </SelectTrigger>
          <SelectContent>
            {agents.presets.map((candidate) => (
              <SelectItem key={candidate.name} value={candidate.name}>
                {candidate.name}
              </SelectItem>
            ))}
            <SelectItem value={ADVANCED_VALUE} disabled={agents.agentKinds.length === 0}>
              Advanced…
            </SelectItem>
          </SelectContent>
        </Select>
        {preset && <FieldDescription>{preset.description}</FieldDescription>}
        {value.mode === "advanced" && (
          <FieldDescription>Any agent kind with its params and budget.</FieldDescription>
        )}
      </Field>
      {value.mode === "advanced" && (
        <div className="rounded-lg border p-3">
          <AgentPicker
            value={value.draft}
            agentKinds={agents.agentKinds}
            errors={result.ok ? null : result.errors}
            onChange={(draft) => {
              onChange({ mode: "advanced", draft });
            }}
          />
        </div>
      )}
    </div>
  );
}
