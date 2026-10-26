/**
 * Agent param forms, generated from the JSON schema the API lists for each agent kind.
 *
 * Simple params (numbers, integers, booleans, strings and enums, each optionally
 * nullable) get a typed input; anything else is edited as JSON. Inputs hold drafts
 * (the text typed so far), which are parsed and checked when the form is submitted.
 */

export type AgentParamInput =
  "integer" | "number" | "boolean" | "string" | "enum" | "json";

/** One param of an agent kind, as the form shows it. */
export interface AgentParamField {
  name: string;
  title: string;
  description: string | null;
  input: AgentParamInput;
  /** Whether `null` is valid, entered by leaving the input empty. */
  nullable: boolean;
  /** Whether the param has a default, so leaving it unchanged sends nothing. */
  hasDefault: boolean;
  defaultValue: unknown;
  options: string[];
  minimum: number | null;
  maximum: number | null;
  exclusiveMinimum: number | null;
  exclusiveMaximum: number | null;
}

/** The draft of a param: the text of an input, or the state of a checkbox. */
export type AgentParamDraft = string | boolean;

export type AgentParamDrafts = Record<string, AgentParamDraft>;

export type AgentParamErrors = Record<string, string>;

type JsonSchema = Record<string, unknown>;

function isSchema(value: unknown): value is JsonSchema {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

/** Split `anyOf: [X, {type: "null"}]` into `X` and whether `null` is allowed. */
function unwrapNullable(schema: JsonSchema): { schema: JsonSchema; nullable: boolean } {
  const variants = Array.isArray(schema.anyOf) ? schema.anyOf.filter(isSchema) : null;

  if (variants === null) {
    return { schema, nullable: false };
  }

  const nonNull = variants.filter((variant) => variant.type !== "null");
  const [single] = nonNull;

  if (nonNull.length === 1 && single !== undefined) {
    return { schema: single, nullable: nonNull.length < variants.length };
  }

  return { schema, nullable: false };
}

function inputOf(schema: JsonSchema): AgentParamInput {
  if (Array.isArray(schema.enum) && schema.enum.every((v) => typeof v === "string")) {
    return "enum";
  }

  switch (schema.type) {
    case "integer":
    case "number":
    case "boolean":
    case "string":
      return schema.type;
    default:
      return "json";
  }
}

/** Read the form fields from the params schema of an agent kind. */
export function parseAgentParamFields(paramsSchema: unknown): AgentParamField[] {
  if (!isSchema(paramsSchema) || !isSchema(paramsSchema.properties)) {
    return [];
  }

  return Object.entries(paramsSchema.properties).flatMap(([name, property]) => {
    if (!isSchema(property)) {
      return [];
    }

    const { schema, nullable } = unwrapNullable(property);
    const input = inputOf(schema);

    return [
      {
        name,
        title: typeof property.title === "string" ? property.title : name,
        description:
          typeof property.description === "string" ? property.description : null,
        input,
        nullable,
        hasDefault: "default" in property,
        defaultValue: property.default,
        options: input === "enum" ? (schema.enum as string[]) : [],
        minimum: numberOrNull(schema.minimum),
        maximum: numberOrNull(schema.maximum),
        exclusiveMinimum: numberOrNull(schema.exclusiveMinimum),
        exclusiveMaximum: numberOrNull(schema.exclusiveMaximum),
      },
    ];
  });
}

/** The draft of a value: empty for `null` or no value, JSON text for `json` inputs. */
function draftOf(field: AgentParamField, value: unknown): AgentParamDraft {
  if (field.input === "boolean") {
    return value === true;
  }

  if (value === undefined || value === null) {
    return "";
  }

  if (field.input !== "json" && typeof value === "string") {
    return value;
  }

  if (field.input !== "json" && typeof value === "number") {
    return String(value);
  }

  return JSON.stringify(value);
}

/** The drafts of a form with every param at its default. */
export function defaultAgentParamDrafts(fields: AgentParamField[]): AgentParamDrafts {
  return Object.fromEntries(
    fields.map((field) => [field.name, draftOf(field, field.defaultValue)]),
  );
}

function checkBounds(field: AgentParamField, value: number): string | null {
  if (field.minimum !== null && value < field.minimum) {
    return `Must be at least ${field.minimum}.`;
  }

  if (field.maximum !== null && value > field.maximum) {
    return `Must be at most ${field.maximum}.`;
  }

  if (field.exclusiveMinimum !== null && value <= field.exclusiveMinimum) {
    return `Must be greater than ${field.exclusiveMinimum}.`;
  }

  if (field.exclusiveMaximum !== null && value >= field.exclusiveMaximum) {
    return `Must be less than ${field.exclusiveMaximum}.`;
  }

  return null;
}

type ParsedParam = { value: unknown } | { error: string };

function parseDraft(field: AgentParamField, draft: AgentParamDraft): ParsedParam {
  if (typeof draft === "boolean") {
    return { value: draft };
  }

  const text = draft.trim();

  if (text === "") {
    if (field.nullable) {
      return { value: null };
    }

    return field.hasDefault ? { value: field.defaultValue } : { error: "Required." };
  }

  switch (field.input) {
    case "integer":
    case "number": {
      const value = Number(text);

      if (!Number.isFinite(value)) {
        return { error: "Must be a number." };
      }

      if (field.input === "integer" && !Number.isInteger(value)) {
        return { error: "Must be a whole number." };
      }

      const error = checkBounds(field, value);

      return error === null ? { value } : { error };
    }
    case "json":
      try {
        return { value: JSON.parse(text) as unknown };
      } catch {
        return { error: "Must be valid JSON." };
      }
    default:
      return { value: text };
  }
}

export type AgentParamsResult =
  { ok: true; params: Record<string, unknown> } | { ok: false; errors: AgentParamErrors };

/**
 * Parse and check the drafts of a param form.
 *
 * Params left at their default are left out, so specs stay short and keep following
 * the defaults of the agent.
 */
export function parseAgentParams(
  fields: AgentParamField[],
  drafts: AgentParamDrafts,
): AgentParamsResult {
  const params: Record<string, unknown> = {};
  const errors: AgentParamErrors = {};

  for (const field of fields) {
    const parsed = parseDraft(field, drafts[field.name] ?? draftOf(field, undefined));

    if ("error" in parsed) {
      errors[field.name] = parsed.error;
    } else if (
      !field.hasDefault ||
      JSON.stringify(parsed.value) !== JSON.stringify(field.defaultValue)
    ) {
      params[field.name] = parsed.value;
    }
  }

  return Object.keys(errors).length > 0 ? { ok: false, errors } : { ok: true, params };
}
