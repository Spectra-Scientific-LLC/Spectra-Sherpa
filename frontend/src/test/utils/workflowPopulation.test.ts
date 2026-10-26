import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { buildNodeOutput } from "@/utils/nodeOutput";
import { populationPlotOutput, observationTraceContext, type WorkflowPopulation } from "@/utils/workflowPopulation";
import { displayObservationTraces } from "@/utils/workflowPopulationTrace";
import { t2QDiagnosticRows } from "@/utils/scientificPlots";
import { useWorkflowStore } from "@/stores/workflow";
import { displayPlot } from "@/utils/displayPlot";
import { DEFAULT_DISPLAY_PREFERENCES } from "@/composables/useDisplayPreferences";
import { buildMetadataLineTraces, metadataGroupingState, subsetMetadataGrouping } from "@/utils/sampleMetadataGrouping";

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
  it("normalizes defaults on both sides without admitting a changed source", () => {
    const store = useWorkflowStore();
    store.nodeLibrary.set("data.file_load", { parameters: [
      {name: "stage", default: "raw"}, {name: "file_id", default: null},
    ] } as never);
    store.nodes = [{id: "load", type: "data.file_load", x: 0, y: 0, params: {experiment_id: 1}}];
    store.lastExecutionParams = {load: {experiment_id: 1, stage: "raw"}};
    store.lastExecutionResults = {load: {exclusions: state}};
    expect(store.workflowPopulationActions.resolve(refs[1])).not.toBeNull();
    store.nodes[0].params.experiment_id = 2;
    expect(store.workflowPopulationActions.resolve(refs[1])).toBeNull();
  });
  it("binds projected diagnostic labels to display rows rather than active-result positions", () => {
    const output = buildNodeOutput({ T2: [1, 3], Q: [.1, .3], sample_labels: ["Original 1", "Original 3"] });
    output.presentation_contract = { schema_version: "spectrasherpa-node-presentation/1", digest: "test", payload: {
      default_presentation: "diagnostics", presentations: [{ presentation_id: "diagnostics", label: "Diagnostics",
        kind: "t2_q_diagnostics", modes: ["plot", "table"], source_ports: ["T2", "Q"], sample_labels_field: "sample_labels" }],
    } } as typeof output.presentation_contract;
    output.metadata.workflow_population = { outputs: { T2: [1, 2, 3], Q: [.1, .2, .3],
      sample_labels: ["Original 1", "Original 2", "Original 3"] } };
    const display = populationPlotOutput(output)!;
    expect(display.ports?.T2.metadata.sample_labels).toEqual(["Original 1", "Original 2", "Original 3"]);
    expect(t2QDiagnosticRows({ T2: display.ports?.T2.value, Q: display.ports?.Q.value },
      display.ports?.T2.metadata).map(row => row.sample)).toEqual(["Original 1", "Original 2", "Original 3"]);
    expect(output.ports?.T2.metadata.sample_labels).not.toEqual(display.ports?.T2.metadata.sample_labels);
  });
  it("removes the source override after restoring the last selected point or all points", () => {
    const store = useWorkflowStore();
    store.nodes = [{ id: "load", type: "data.file_load", x: 0, y: 0, params: { experiment_id: 1,
      workflow_exclusions: { source_digest: digest, excluded_refs: [refs[1]] } } }];
    store.lastExecutionResults = { load: { exclusions: state } };
    store.workflowPopulationActions.change([refs[1]], false);
    expect(store.nodes[0].params).toEqual({ experiment_id: 1 });
    store.nodes[0].params.workflow_exclusions = null;
    store.restoreWorkflowObservations();
    expect(store.nodes[0].params).toEqual({ experiment_id: 1 });
  });
  it("aligns subset inclusion and navigation with selected source rows, not subset positions", () => {
    const rows = Array.from({ length: 121 }, (_, i) => [i, i + 1]);
    const axis = { count: rows.length, labels: rows.map((_, i) => `source-${i}`),
      include_mask: rows.map((_, i) => i > 2), workflow_observation_refs: rows.map((_, i) => `ref-${i}`),
      sample_table: { Class: rows.map(() => "A") } };
    const grouping = metadataGroupingState(axis, rows.length);
    expect(grouping.kind).toBe("valid");
    if (grouping.kind !== "valid") return;
    const indices = Array.from({ length: 71 }, (_, i) => i + 50);
    const subset = subsetMetadataGrouping(grouping, indices);
    const traces = buildMetadataLineTraces([1, 2], indices.map(i => rows[i]), subset, "Class", "__none__", 1);
    const curves = traces.filter(trace => trace.showlegend === false);
    expect(curves).toHaveLength(1);
    expect(curves[0].y).toEqual([50, 51]);
    expect(curves[0].meta).toEqual({ workflow_observation_refs: ["ref-50", "ref-50"], workflow_included: [true, true] });
  });
  it("keeps numeric color values, bounds, scale and hover intact for excluded points", () => {
    const colors = [1.2, 2.4, 3.6];
    const trace = { type: "scatter", mode: "markers", x: [1, 2, 3], y: [4, 5, 6],
      marker: { color: colors, colorscale: "Viridis", cmin: 0, cmax: 4, showscale: true },
      hovertemplate: "%{marker.color}", meta: observationTraceContext(axis, 3) };
    const displayed = displayObservationTraces([trace])[0];
    expect(displayed.marker).toMatchObject({ color: colors, colorscale: "Viridis", cmin: 0, cmax: 4, showscale: true,
      symbol: ["circle", "x-open", "x-open"] });
    expect(displayed.hovertemplate).toBe(trace.hovertemplate);
    expect(displayed.x).toBe(trace.x);
  });
  it("resolves each source reference only once even across many spectral points", () => {
    const resolve = vi.fn(() => ({ excluded: true, restorable: true }));
    const trace = { mode: "lines", x: Array(2000).fill(1), y: Array(2000).fill(2),
      meta: { workflow_observation_refs: Array(2000).fill(refs[1]) } };
    displayObservationTraces([trace, trace], { resolve, change: vi.fn() });
    expect(resolve).toHaveBeenCalledTimes(1);
  });
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
    expect(plotted.data[0].y).toEqual([0, 0, 0]); // a one-row budget reserves the active spectrum
    expect(plotted.data[1].name).toBe("Excluded / not in fit");
  });
  it("remaps the selected point indexes when the display is sampled", () => {
    const trace = { type: "scatter", mode: "markers", x: [0, 1, 2], y: [4, 5, 6],
      selectedpoints: [2], meta: observationTraceContext(axis, 3) };
    const plotted = displayPlot([trace], {}, { ...DEFAULT_DISPLAY_PREFERENCES, maxRows: 2 }).data[0];
    expect(plotted.selectedpoints).toEqual([(plotted.x as number[]).indexOf(2)]);
  });
});
