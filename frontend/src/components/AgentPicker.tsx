import { useId, useMemo } from "react";

import type { AgentRegistration } from "@/api/client";
import { AgentParamInput } from "@/components/AgentParamInput";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { parseAgentParamFields, type AgentParamDrafts } from "@/lib/agentParams";
import { agentDraft, type AgentDraftErrors, type AgentPlayerDraft } from "@/lib/players";

interface AgentPickerProps {
  value: AgentPlayerDraft;
  agentKinds: AgentRegistration[];
  errors: AgentDraftErrors | null;
  onChange: (draft: AgentPlayerDraft) => void;
}

/** Choose an agent kind and its params, label and time budget. */
export function AgentPicker({ value, agentKinds, errors, onChange }: AgentPickerProps) {
  const kindId = useId();
  const labelId = useId();
  const budgetId = useId();
  const registration = agentKinds.find((kind) => kind.kind === value.kind);
  const fields = useMemo(
    () => (registration ? parseAgentParamFields(registration.params_schema) : []),
    [registration],
  );

  const changeKind = (kind: string) => {
    const next = agentKinds.find((candidate) => candidate.kind === kind);

    if (next) {
      onChange({
        ...agentDraft(next),
        label: value.label,
        budget: value.budget,
      });
    }
  };

  const changeParams = (params: AgentParamDrafts) => {
    onChange({ ...value, params });
  };

  return (
    <div className="flex flex-col gap-4">
      <Field data-invalid={errors?.kind !== undefined}>
        <FieldLabel htmlFor={kindId}>Agent</FieldLabel>
        <Select value={value.kind} onValueChange={changeKind}>
          <SelectTrigger id={kindId} className="w-full">
            <SelectValue placeholder="Choose an agent" />
          </SelectTrigger>
          <SelectContent>
            {agentKinds.map((kind) => (
              <SelectItem key={kind.kind} value={kind.kind}>
                {kind.kind}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {registration && <FieldDescription>{registration.description}</FieldDescription>}
        {errors?.kind && <FieldError>{errors.kind}</FieldError>}
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field data-invalid={errors?.budget !== undefined}>
          <FieldLabel htmlFor={budgetId}>Budget (s)</FieldLabel>
          <Input
            id={budgetId}
            value={value.budget}
            inputMode="decimal"
            aria-invalid={errors?.budget !== undefined}
            onChange={(event) => {
              onChange({ ...value, budget: event.target.value });
            }}
          />
          {errors?.budget && <FieldError>{errors.budget}</FieldError>}
        </Field>
        <Field>
          <FieldLabel htmlFor={labelId}>Label</FieldLabel>
          <Input
            id={labelId}
            value={value.label}
            placeholder={value.kind}
            onChange={(event) => {
              onChange({ ...value, label: event.target.value });
            }}
          />
        </Field>
      </div>
      {fields.map((field) => (
        <AgentParamInput
          key={field.name}
          field={field}
          value={value.params[field.name] ?? ""}
          error={errors?.params[field.name]}
          onChange={(param) => {
            changeParams({ ...value.params, [field.name]: param });
          }}
        />
      ))}
    </div>
  );
}
