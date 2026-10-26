import { describe, expect, it } from "vitest";

import {
  defaultAgentParamDrafts,
  parseAgentParamFields,
  parseAgentParams,
} from "@/lib/agentParams";
import { AGENT_KINDS } from "@/test/fixtures";

const [negamax] = AGENT_KINDS;
const searchFields = parseAgentParamFields(negamax?.params_schema);

describe("parseAgentParamFields", () => {
  it("reads nullable and plain params with their constraints", () => {
    expect(searchFields).toMatchObject([
      { name: "depth", title: "Depth", input: "integer", nullable: true, minimum: 1 },
      { name: "queen_safety", input: "number", nullable: false, defaultValue: 1 },
    ]);
  });

  it("reads enums, booleans and other values", () => {
    const fields = parseAgentParamFields({
      properties: {
        mode: { enum: ["fast", "slow"], type: "string" },
        verbose: { type: "boolean", default: false },
        weights: { type: "array", items: { type: "number" } },
      },
    });

    expect(fields.map((field) => [field.name, field.input, field.hasDefault])).toEqual([
      ["mode", "enum", false],
      ["verbose", "boolean", true],
      ["weights", "json", false],
    ]);
    expect(fields[0]?.options).toEqual(["fast", "slow"]);
  });

  it("returns no fields for a schema without properties", () => {
    expect(parseAgentParamFields(null)).toEqual([]);
    expect(parseAgentParamFields({ type: "object" })).toEqual([]);
  });
});

describe("parseAgentParams", () => {
  it("starts from the defaults and leaves them out", () => {
    const drafts = defaultAgentParamDrafts(searchFields);

    expect(drafts).toEqual({ depth: "", queen_safety: "1" });
    expect(parseAgentParams(searchFields, drafts)).toEqual({ ok: true, params: {} });
  });

  it("parses changed values", () => {
    expect(parseAgentParams(searchFields, { depth: "3", queen_safety: "0.5" })).toEqual({
      ok: true,
      params: { depth: 3, queen_safety: 0.5 },
    });
  });

  it("reports invalid values per param", () => {
    expect(parseAgentParams(searchFields, { depth: "0", queen_safety: "x" })).toEqual({
      ok: false,
      errors: { depth: "Must be at least 1.", queen_safety: "Must be a number." },
    });
    expect(parseAgentParams(searchFields, { depth: "2.5", queen_safety: "" })).toEqual({
      ok: false,
      errors: { depth: "Must be a whole number." },
    });
  });

  it("requires params without a default and parses JSON", () => {
    const fields = parseAgentParamFields({
      properties: { weights: { type: "array" }, name: { type: "string" } },
    });

    expect(parseAgentParams(fields, { weights: "[1, 2]", name: "" })).toEqual({
      ok: false,
      errors: { name: "Required." },
    });
    expect(parseAgentParams(fields, { weights: "[1, 2]", name: "a" })).toEqual({
      ok: true,
      params: { weights: [1, 2], name: "a" },
    });
    expect(parseAgentParams(fields, { weights: "[1,", name: "a" })).toEqual({
      ok: false,
      errors: { weights: "Must be valid JSON." },
    });
  });

  it("checks exclusive bounds", () => {
    const fields = parseAgentParamFields({
      properties: { rate: { type: "number", exclusiveMinimum: 0, exclusiveMaximum: 1 } },
    });

    expect(parseAgentParams(fields, { rate: "0" })).toMatchObject({ ok: false });
    expect(parseAgentParams(fields, { rate: "1" })).toMatchObject({ ok: false });
    expect(parseAgentParams(fields, { rate: "0.5" })).toEqual({
      ok: true,
      params: { rate: 0.5 },
    });
  });
});
