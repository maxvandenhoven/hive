import { useId } from "react";

import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
  FieldLegend,
  FieldSet,
  FieldTitle,
} from "@/components/ui/field";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { cn } from "@/lib/utils";

export interface ChoiceCardOption<Value extends string> {
  value: Value;
  title: string;
  /** One line on what the option means; compact options leave it out. */
  description?: string;
}

interface ChoiceCardsProps<Value extends string> {
  legend: string;
  options: ChoiceCardOption<Value>[];
  value: Value;
  onChange: (value: Value) => void;
  /** Columns on a phone: `stack` puts every option on a row of its own. */
  layout?: "stack" | "row";
}

/** A choice between a few options as cards, large enough to tap on a phone. */
export function ChoiceCards<Value extends string>({
  legend,
  options,
  value,
  onChange,
  layout = "stack",
}: ChoiceCardsProps<Value>) {
  const id = useId();

  return (
    <FieldSet>
      <FieldLegend variant="label">{legend}</FieldLegend>
      <RadioGroup
        value={value}
        onValueChange={(next) => {
          const option = options.find((candidate) => candidate.value === next);

          if (option) {
            onChange(option.value);
          }
        }}
        className={cn(
          layout === "row"
            ? "grid-cols-3"
            : options.length > 2
              ? "sm:grid-cols-3"
              : "sm:grid-cols-2",
        )}
      >
        {options.map((option) => (
          <FieldLabel key={option.value} htmlFor={`${id}-${option.value}`}>
            <Field orientation="horizontal" className="min-h-11">
              <RadioGroupItem value={option.value} id={`${id}-${option.value}`} />
              <FieldContent>
                <FieldTitle>{option.title}</FieldTitle>
                {option.description && (
                  <FieldDescription>{option.description}</FieldDescription>
                )}
              </FieldContent>
            </Field>
          </FieldLabel>
        ))}
      </RadioGroup>
    </FieldSet>
  );
}
