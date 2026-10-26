import { useId } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AgentParamDraft, AgentParamField } from "@/lib/agentParams";

/** Leaves a nullable enum param empty; Radix selects cannot use an empty value. */
const EMPTY_OPTION = "__none__";

interface AgentParamInputProps {
  field: AgentParamField;
  value: AgentParamDraft;
  error: string | undefined;
  onChange: (value: AgentParamDraft) => void;
}

/** The input of one agent param, chosen by the type in its schema. */
export function AgentParamInput({ field, value, error, onChange }: AgentParamInputProps) {
  const id = useId();
  const description = [field.description, field.nullable ? "Leave empty for none." : null]
    .filter(Boolean)
    .join(" ");

  if (field.input === "boolean") {
    return (
      <Field orientation="horizontal">
        <Checkbox
          id={id}
          checked={value === true}
          onCheckedChange={(checked) => {
            onChange(checked === true);
          }}
        />
        <FieldLabel htmlFor={id}>{field.title}</FieldLabel>
        {field.description && <FieldDescription>{field.description}</FieldDescription>}
      </Field>
    );
  }

  const text = typeof value === "string" ? value : "";

  return (
    <Field data-invalid={error !== undefined}>
      <FieldLabel htmlFor={id}>{field.title}</FieldLabel>
      {field.input === "enum" ? (
        <Select
          value={text === "" ? EMPTY_OPTION : text}
          onValueChange={(option) => {
            onChange(option === EMPTY_OPTION ? "" : option);
          }}
        >
          <SelectTrigger id={id} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {field.nullable && <SelectItem value={EMPTY_OPTION}>None</SelectItem>}
            {field.options.map((option) => (
              <SelectItem key={option} value={option}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <Input
          id={id}
          value={text}
          inputMode={
            field.input === "integer" || field.input === "number" ? "decimal" : "text"
          }
          placeholder={field.nullable ? "None" : undefined}
          aria-invalid={error !== undefined}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      )}
      {description && <FieldDescription>{description}</FieldDescription>}
      {error && <FieldError>{error}</FieldError>}
    </Field>
  );
}
