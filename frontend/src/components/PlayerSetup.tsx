import { useId } from "react";

import type { AgentRegistration } from "@/api/client";
import { AgentPicker } from "@/components/AgentPicker";
import {
  Field,
  FieldDescription,
  FieldLabel,
  FieldSet,
  FieldLegend,
} from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  agentDraft,
  HUMAN_DRAFT,
  parsePlayerDraft,
  type PlayerDraft,
  type PlayerSide,
} from "@/lib/players";

const SIDE_TITLES: Record<PlayerSide, string> = { white: "White", black: "Black" };

interface PlayerSetupProps {
  side: PlayerSide;
  value: PlayerDraft;
  agentKinds: AgentRegistration[];
  /** Whether a person may play this side; false while the other side is human. */
  allowHuman: boolean;
  onChange: (draft: PlayerDraft) => void;
}

/** Set up who plays one side: a person at the table, or an agent with its settings. */
export function PlayerSetup({
  side,
  value,
  agentKinds,
  allowHuman,
  onChange,
}: PlayerSetupProps) {
  const typeId = useId();
  const result = parsePlayerDraft(value, agentKinds);
  const [firstKind] = agentKinds;

  const changeType = (type: string) => {
    if (type === "human") {
      onChange(HUMAN_DRAFT);
    } else if (firstKind) {
      onChange(agentDraft(firstKind));
    }
  };

  return (
    <FieldSet>
      <FieldLegend>{SIDE_TITLES[side]}</FieldLegend>
      <Field>
        <FieldLabel htmlFor={typeId}>Player</FieldLabel>
        <Select value={value.type} onValueChange={changeType}>
          <SelectTrigger id={typeId} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="human" disabled={!allowHuman}>
              Human
            </SelectItem>
            <SelectItem value="agent" disabled={firstKind === undefined}>
              Agent
            </SelectItem>
          </SelectContent>
        </Select>
        {!allowHuman && value.type === "agent" && (
          <FieldDescription>
            The other side is human, so this side is an agent.
          </FieldDescription>
        )}
      </Field>
      {value.type === "agent" && (
        <AgentPicker
          value={value}
          agentKinds={agentKinds}
          errors={result.ok ? null : result.errors}
          onChange={onChange}
        />
      )}
    </FieldSet>
  );
}
