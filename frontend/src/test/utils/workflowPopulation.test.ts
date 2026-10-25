import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { buildNodeOutput } from "@/utils/nodeOutput";
import { populationPlotOutput, observationTraceContext, type WorkflowPopulation } from "@/utils/workflowPopulation";
import { displayObservationTraces } from "@/utils/workflowPopulationTrace";
import { useWorkflowStore } from "@/stores/workflow";
import { displayPlot } from "@/utils/displayPlot";
import { DEFAULT_DISPLAY_PREFERENCES } from "@/composables/useDisplayPreferences";
import { metadataGroupingState } from "@/utils/sampleMetadataGrouping";

vi.mock("@/api/client", () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
const digest = "a".repeat(64);
const refs = [0, 1, 2].map(i => `load:${digest}:${i}`);
const axis = { count: 3, labels: ["Repeated", "Repeated", "Third"], include_mask: [true, false, false],
  workflow_observation_refs: refs, sample_table: { Class: ["a", "b", "b"] } };
const state: WorkflowPopulation = { schema_version: "spectrasherpa-workflow-population/1", source_node_id: "load",
  source_digest: digest, source_count: 3, active_count: 1, workflow_excluded_count: 2, identity_basis: "source_bound_row",
  rows: refs.map((ref, i) => ({ observation_ref: ref, source_row: i + 1, sample_id: null, sample_label: axis.labels[i],
    included: i === 0, source_included: true, workflow_excluded: i > 0, result_row: i === 0 ? 1 : null })) };

describe("source-owned workflow observation curation", () => {
  beforeEach(() => setActivePinia(createPinia()));
  it("uses exact source refs, permits subset restoration, and never changes a branch filter", () => {
    const store = useWorkflowStore();
    store.nodes = [{ id: "load", type: "data.collection_load", x: 0, y: 0, params: { workflow_exclusions: {
      source_digest: digest, excluded_refs: refs.slice(1) } } },
      { id: "branch", type: "data.filter_samples", x: 0, y: 0, params: { field: "source_inclusion" } }];
    store.lastExecutionResults = { load: { exclusions: state } };
    expect(store.workflowExcludedCount).toBe(2);
    store.workflowPopulationActions.change([refs[1]], false);
    expect(store.workflowExcludedCount).toBe(1);
    expect(store.workflowPopulationActions.resolve(refs[1])?.excluded).toBe(false);
    expect(store.workflowPopulationActions.resolve(refs[2])?.excluded).toBe(true);
    expect(store.nodes[1].params).toEqual({ field: "source_inclusion" });
    expect(() => store.workflowPopulationActions.change(["foreign"], true)).toThrow(/current workflow/);
    store.restoreWorkflowObservations();
    expect(store.workflowExcludedCount).toBe(0);
    expect(state.rows[1].included).toBe(false); // retained evidence is immutable
  });
  it("refuses a source change and does not mutate any source on a partial invalid selection", () => {
    const store = useWorkflowStore();
    store.nodes = [{ id: "load", type: "data.collection_load", x: 0, y: 0, params: {} }];
    store.lastExecutionResults = { load: { exclusions: state } };
    expect(() => store.workflowPopulationActions.change([refs[0], "foreign"], true)).toThrow();
    expect(store.nodes[0].params.workflow_exclusions).toBeUndefined();
    store.nodes[0].params.workflow_exclusions = { source_digest: "b".repeat(64), excluded_refs: [] };
    expect(store.workflowPopulationActions.resolve(refs[0])).toBeNull();
    expect(() => store.workflowPopulationActions.change([refs[0]], true)).toThrow(/Source changed/);
  });
  it("a changed first source cannot disable restoration for an unchanged second source", () => {
    const store = useWorkflowStore();
    const otherRefs = refs.map(ref => ref.replace(/^load:/, "other:"));
    store.nodes = [
      { id: "load", type: "data.collection_load", x: 0, y: 0, params: { experiment_id: 2 } },
      { id: "other", type: "data.collection_load", x: 0, y: 0, params: { workflow_exclusions: {
        source_digest: digest, excluded_refs: otherRefs.slice(1) } } },
    ];
    store.lastExecutionParams = { load: { experiment_id: 1 }, other: {} };
    store.lastExecutionResults = { load: { exclusions: state }, other: { exclusions: { ...state, source_node_id: "other",
      rows: state.rows.map((row, i) => ({ ...row, observation_ref: otherRefs[i] })) } } };
    expect(store.workflowPopulationActions.resolve(refs[0])).toBeNull();
    expect(store.workflowPopulationActions.resolve(otherRefs[1])?.excluded).toBe(true);
    store.workflowPopulationActions.change([otherRefs[1]], false);
    expect(store.workflowPopulationActions.resolve(otherRefs[1])?.excluded).toBe(false);
    expect(store.nodes[0].params).toEqual({ experiment_id: 2 });
  });
  it("expands only plot values; tables and numerical data remain active", () => {
    const full = { type: "SherpaDataset", data: [[1, 2], [3, 4], [5, 6]], sample_axis: axis, metadata: {} };
    const output = buildNodeOutput({ default: { ...full, data: [[1, 2]] },
      __workflow_population: { availability: "available", sources: {}, outputs: { default: full } } });
    expect(output.data).toEqual([[1, 2]]);
    const display = populationPlotOutput(output)!;
    expect(display.data).toHaveLength(3);
    expect(output.data).toHaveLength(1);
    expect(output.ports?.__workflow_population).toBeUndefined();
  });
  it("does not mistake navigation refs for verified sample IDs or grouping fields", () => {
    const grouping = metadataGroupingState(axis, 3);
    expect(grouping.kind).toBe("valid");
    if (grouping.kind !== "valid") return;
    expect(grouping.sampleIds).toBeNull();
    expect(grouping.colorOptions.map(option => option.value)).not.toContain("workflow_source_row");
    expect(grouping.colorOptions.map(option => option.value)).not.toContain("workflow_observation_ref");
    expect(observationTraceContext(axis, 3, [2, 0])).toEqual({ workflow_observation_refs: [refs[2], refs[0]], workflow_included: [false, true] });
  });
  it("preserves color/symbol grouping and marks excluded rows without changing values", () => {
    const trace = { type: "scatter", mode: "markers", x: [1, 2, 3], y: [4, 5, 6],
      marker: { color: ["red", "blue", "green"], symbol: ["diamond", "square", "circle"] },
      meta: observationTraceContext(axis, 3) };
    const displayed = displayObservationTraces([trace]);
    expect(displayed[0].x).toBe(trace.x);
    expect(displayed[0].marker).toMatchObject({ symbol: ["diamond", "x-open", "x-open"] });
    expect(displayed).toHaveLength(2);
    expect(trace.marker.symbol).toEqual(["diamond", "square", "circle"]);
  });
  it("samples source references with the exact same indices as plotted values", () => {
    const trace = { type: "scatter", mode: "markers", x: [0, 1, 2], y: [4, 5, 6], meta: observationTraceContext(axis, 3) };
    const plotted = displayPlot([trace], {}, { ...DEFAULT_DISPLAY_PREFERENCES, maxRows: 2 }).data[0];
    const displayedRefs = (plotted.meta as Record<string, unknown>).workflow_observation_refs as string[];
    (plotted.x as number[]).forEach((x, i) => expect(displayedRefs[i]).toBe(refs[x]));
  });
  it("keeps the curve limit with excluded symbols and their legend, including a one-row limit", () => {
    const curves = refs.map((ref, i) => ({ type: "scatter", mode: "lines", x: [1, 2, 3], y: [i, i, i],
      meta: { workflow_observation_refs: [ref, ref, ref], workflow_included: [i === 0, i === 0, i === 0] } }));
    const plotted = displayPlot(displayObservationTraces(curves), {}, { ...DEFAULT_DISPLAY_PREFERENCES, maxRows: 1 });
    expect(plotted.omitted).toBe(2);
    expect(plotted.data).toHaveLength(2); // one spectrum, one non-data legend marker
    expect(plotted.data[0].y).toEqual([1, 1, 1]);
    expect(plotted.data[1].name).toBe("Excluded / not in fit");
  });
  it("remaps the selected point indexes when the display is sampled", () => {
    const trace = { type: "scatter", mode: "markers", x: [0, 1, 2], y: [4, 5, 6],
      selectedpoints: [2], meta: observationTraceContext(axis, 3) };
    const plotted = displayPlot([trace], {}, { ...DEFAULT_DISPLAY_PREFERENCES, maxRows: 2 }).data[0];
    expect(plotted.selectedpoints).toEqual([(plotted.x as number[]).indexOf(2)]);
  });
});
