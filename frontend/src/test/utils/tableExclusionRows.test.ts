import { describe, expect, it } from "vitest";
import { tableExclusionRows } from "@/utils/tableExclusionRows";
import { buildNodeOutput } from "@/utils/nodeOutput";
import { projectScientificPresentation, resolveScientificPresentation } from "@/utils/scientificPresentation";
import type { WorkflowPopulation } from "@/utils/workflowPopulation";

const refs = ["one", "two", "three"];
const population: WorkflowPopulation = { schema_version: "spectrasherpa-workflow-population/1", source_node_id: "load", source_digest: "a".repeat(64),
  source_count: 3, active_count: 2, workflow_excluded_count: 1, identity_basis: "typed_sample_id",
  rows: refs.map((reference, index) => ({ observation_ref: reference, sample_id: `id-${index}`, source_row: index + 1,
    sample_label: "Repeated", included: index !== 0, source_included: true, workflow_excluded: index === 0, result_row: index || null })) };

function output(displayRefs = refs) {
  const dataset = { type: "SherpaDataset", data: [[2], [3]], sample_axis: { labels: ["Repeated", "Repeated"], workflow_observation_refs: refs.slice(1) } };
  const raw = buildNodeOutput({ default: dataset });
  raw.presentation_contract = { schema_version: "spectrasherpa-node-presentation/1", digest: "test", payload: {
    default_presentation: "data", presentations: [{ presentation_id: "data", label: "Data", kind: "spectral_dataset", source_ports: ["default"],
      modes: ["plot", "table"], output_binding: ["default", "sample_axis"] }],
  } } as typeof raw.presentation_contract;
  raw.metadata.workflow_population = { outputs: { default: { ...dataset, data: displayRefs.map(() => [999]), sample_axis: {
    labels: displayRefs.map(() => "Repeated"), workflow_observation_refs: displayRefs,
    include_mask: displayRefs.map(reference => reference !== "one"),
  } } } };
  return projectScientificPresentation(raw, resolveScientificPresentation(null, raw))!;
}
const computedRows = [{ _index: 1, _label: "Repeated", col_0: 2 }, { _index: 2, _label: "Repeated", col_0: 3 }];

describe("excluded identities in the original data table", () => {
  it("inserts an excluded identity with empty computed cells and preserves actual values", () => {
    const before = JSON.stringify(computedRows);
    const rows = tableExclusionRows(output(), computedRows, refs.slice(1), new Map([["two", true], ["three", true]]), [population], 100);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toMatchObject({ _observation_ref: "one", _source_row: 1, _usedInResult: false, col_0: null, _index: null });
    expect(rows[1]).toMatchObject({ _observation_ref: "two", _usedInResult: true, col_0: 2 });
    expect(rows[2]).toMatchObject({ _observation_ref: "three", _usedInResult: true, col_0: 3 });
    expect(JSON.stringify(computedRows)).toBe(before);
  });
  it("does not insert another branch's exclusions or use an incomplete display projection", () => {
    const membership = new Map([["two", true], ["three", true]]);
    expect(tableExclusionRows(output(refs.slice(1)), computedRows, refs.slice(1), membership, [population], 100)).toHaveLength(2);
    expect(tableExclusionRows(output(["one", "two"]), computedRows, refs.slice(1), membership, [population], 100)).toHaveLength(2);
  });
  it("keeps later preview pages aligned without repeating an excluded identity", () => {
    const rows = tableExclusionRows(output(), [computedRows[1]], refs.slice(1), new Map([["two", true], ["three", true]]), [population], 100, 1);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ _observation_ref: "three", _source_row: 3, col_0: 3 });
  });
  it.each(["source excluded", "undeclared eligibility", "not workflow excluded"])("does not reintroduce %s rows", reason => {
    const source = structuredClone(population);
    if (reason === "source excluded") source.rows[0].source_included = false;
    if (reason === "undeclared eligibility") delete (source.rows[0] as Partial<typeof source.rows[0]>).source_included;
    if (reason === "not workflow excluded") source.rows[0].workflow_excluded = false;
    const rows = tableExclusionRows(output(), computedRows, refs.slice(1), new Map([["two", true], ["three", true]]), [source], 100);
    expect(rows.map(row => row._observation_ref)).toEqual(["two", "three"]);
  });

  it("refuses a whole-node display containing another cohort's active and excluded identities", () => {
    const whole = output(["one", "two", "three", "other-active", "other-excluded"]);
    const companion = (whole.metadata.workflow_population as { outputs: { default: { sample_axis: { include_mask: boolean[] } } } }).outputs.default;
    companion.sample_axis.include_mask = [false, true, true, true, false];
    const other = structuredClone(population);
    other.rows = [{ ...population.rows[0], observation_ref: "other-excluded" }];
    const rows = tableExclusionRows(whole, computedRows, refs.slice(1), new Map([["two", true], ["three", true]]), [population, other], 100);
    expect(rows.map(row => row._observation_ref)).toEqual(["two", "three"]);
    expect(rows.map(row => row.col_0)).toEqual([2, 3]);
  });

  it.each([[["two", "foreign"]], [["three", "two"]]])("does not certify caller refs %j using another output's axis", supplied => {
    const rows = tableExclusionRows(output(), computedRows, supplied, new Map(supplied.map(reference => [reference, true])), [population], 100);
    expect(rows).toEqual(computedRows);
    expect(rows.every(row => !("_observation_ref" in row))).toBe(true);
  });

  it.each([{ mask: undefined }, { mask: [false, true] }, { mask: [false, true, "true"] }])("does not qualify omitted rows with malformed display mask %j", ({ mask }) => {
    const result = output();
    const companion = (result.metadata.workflow_population as { outputs: { default: { sample_axis: { include_mask?: unknown } } } }).outputs.default;
    companion.sample_axis.include_mask = mask;
    const rows = tableExclusionRows(result, computedRows, refs.slice(1), new Map([["two", true], ["three", true]]), [population], 100);
    expect(rows.map(row => row._observation_ref)).toEqual(["two", "three"]);
  });

});
