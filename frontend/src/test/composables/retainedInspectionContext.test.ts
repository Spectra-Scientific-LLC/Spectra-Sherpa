import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { defineComponent, h, reactive, ref } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import PrimeVue from "primevue/config";
import DataTableModal from "@/views/workflow-builder/modals/DataTableModal.vue";
import { useInspectorRetainedEvidence } from "@/views/workflow-builder/composables/useInspectorRetainedEvidence";
import { buildNodeOutput } from "@/utils/nodeOutput";
import type { NodeTypeMetadata, NodePresentationContract } from "@/types";
import type { NodeScientificValueDescriptors } from "@/stores/workflow-types";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/api/client", () => ({ default: { get } }));

const assignments = [..."00012222002200222222222220222110022110111110002000000110000000200100000001202000"].map(Number);
const names = assignments.map((_, i) => `corn-m5-${String(i + 1).padStart(3, "0")}`);
const companion = { type: "HCA", source_labels: names, sample_labels: assignments.map(String) };
const descriptors = Object.fromEntries(["default", "embedding"].map(port => [port, {
  schema_version: "spectrasherpa-scientific-value/1", port_name: port,
  type_ref: "spectrasherpa://types/Array1D/1.0", scientific_kind: "numeric_vector", view_kind: "vector",
  label: port, shape: [80], dimensions: [{ role: "entry", size: 80 }],
  view_modes: ["table"], content_categories: ["unclassified"], shape_valid: true,
}])) as NodeScientificValueDescriptors;
const contract = { digest: "a".repeat(64), payload: {
  schema_version: "spectrasherpa-node-presentation/1", default_presentation: "default",
  presentations: ["default", "embedding"].map(port => ({ presentation_id: port, label: port,
    kind: "numeric_vector", source_ports: [port], modes: ["table"], description: "" })),
} } as NodePresentationContract;
const metadata = { output_ports: [{ name: "default" }, { name: "embedding" }] } as NodeTypeMetadata;
const exact = (value: unknown) => ({ data: { value, evidence: {
  state: "exact", storage: "file", sha256: "b".repeat(64), byte_count: 100, format_version: 1,
} } });

let wrappers: VueWrapper[] = [];
afterEach(() => { wrappers.forEach(w => w.unmount()); wrappers = []; get.mockReset(); });

function fixture(scope = "restored_summary", presentation = "default", config = {
  descriptors, contract, metadata, nodeType: "model.hca",
}) {
  const owner = reactive({ project: 138, run: 694, node: "model_1", scope });
  const output = ref(buildNodeOutput({ default: assignments, embedding: assignments, metadata: companion },
    metadata.output_ports, null, descriptors, contract));
  const unavailable = vi.fn();
  let inspection!: ReturnType<typeof useInspectorRetainedEvidence>;
  const wrapper = mount(defineComponent({ setup() {
    inspection = useInspectorRetainedEvidence({
      identity: () => [owner.project, owner.run, owner.node, owner.scope],
      projectId: () => owner.project, runId: () => owner.run, nodeId: () => owner.node,
      evidenceScope: () => owner.scope, metadata: ref(config.metadata), output,
      presentationId: ref(presentation), inputs: () => [], descriptors: () => config.descriptors,
      unavailable, closeContextDialogs: vi.fn(),
    });
    return () => inspection.showDataTableModal.value && inspection.quickPlotNodeOutput.value
      ? h(DataTableModal, { modelValue: true, nodeType: config.nodeType, nodeLabel: "Retained result",
        nodeOutput: inspection.quickPlotNodeOutput.value }) : h("div");
  } }), { global: { plugins: [PrimeVue], stubs: {
    Dialog: { props: ["visible"], template: '<div v-if="visible"><slot /></div>' },
    MethodHelp: true,
  } } });
  wrappers.push(wrapper);
  get.mockImplementation(async (url: string) => exact(url.endsWith("/metadata") ? companion : assignments));
  return { owner, output, unavailable, wrapper, inspection };
}

function cells(wrapper: VueWrapper) {
  return wrapper.findAll("tbody tr").map(row => row.findAll("td").map(cell => cell.text()));
}

describe("retained primary metadata context", () => {
  it("keeps the producer's self-contained Library Comparison table when duplicate metadata was not retained", async () => {
    // library_compare_node.py returns {default: {data: report_rows, metadata}, metadata}.
    const rows = [{ sample: "Query A", library: "Reference A", hqi: 960 },
      { sample: "Query A", library: "Reference B", hqi: 820 }];
    const context = { type: "LibraryComparison", n_query_spectra: 1, n_library_spectra: 2,
      ranked_by: "HQI", hqi_mode: "whole_spectrum", n_report_rows: 2,
      overlap_sufficient: true, alignment_grid: { mode: "linear", n_points: 700 } };
    const primary = { data: rows, metadata: context };
    const ownDescriptors = { default: { ...descriptors.default, type_ref: "spectrasherpa://types/Comparison/1.0",
      scientific_kind: "comparison", shape: [2], dimensions: [{ role: "entry", size: 2 }] } } as NodeScientificValueDescriptors;
    const ownContract = { ...contract, payload: { ...contract.payload,
      presentations: [{ ...contract.payload.presentations[0], kind: "comparison", label: "Library Ranking" }] } } as NodePresentationContract;
    const ownMetadata = { output_ports: [{ name: "default" }, { name: "metadata" }] } as NodeTypeMetadata;
    const f = fixture("live", "default", { descriptors: ownDescriptors, contract: ownContract,
      metadata: ownMetadata, nodeType: "analysis.compare_library" });
    f.output.value = buildNodeOutput({ default: primary, metadata: context }, ownMetadata.output_ports,
      null, ownDescriptors, ownContract);
    await f.inspection.openDataTable(); await flushPromises();
    const liveCells = cells(f.wrapper);
    expect(liveCells).toHaveLength(2);
    expect(liveCells[0]).toContain("Query A");
    expect(liveCells[0]).toContain("Reference A");
    expect(liveCells[0]).toContain("960");
    f.owner.scope = "restored_summary";
    get.mockImplementation(async (url: string) => {
      if (url.endsWith("/metadata")) throw new Error("410 duplicate metadata omitted by retention budget");
      return exact(primary);
    });
    await f.inspection.openDataTable(); await flushPromises();
    expect(f.inspection.quickPlotEvidenceError.value).toBe("");
    expect(cells(f.wrapper)).toEqual(liveCells);
    expect(f.inspection.exactQuickPlotOutput.value?.metadata.alignment_grid).toEqual(context.alignment_grid);
    expect(f.unavailable).not.toHaveBeenCalled();
  });

  it.each(["partial inline context", "unqualified primary"])("does not skip a missing HCA companion for %s", async failure => {
    const f = fixture();
    const primary = { data: assignments, metadata: failure === "partial inline context" ? { type: "HCA" } : companion };
    f.output.value = buildNodeOutput({ default: primary, metadata: companion }, metadata.output_ports, null, descriptors, contract);
    get.mockImplementation(async (url: string) => {
      if (url.endsWith("/metadata")) throw new Error("410 missing required context");
      return failure === "unqualified primary" ? { data: { value: primary, evidence: { state: "reduced" } } } : exact(primary);
    });
    await f.inspection.openDataTable(); await flushPromises();
    expect(f.inspection.quickPlotNodeOutput.value).toBeNull();
    expect(f.wrapper.find("table").exists()).toBe(false);
    expect(f.unavailable).toHaveBeenCalled();
  });

  it("keeps all 80 reference labels and scalar values in the mounted live then restored table", async () => {
    const f = fixture("live");
    await f.inspection.openDataTable(); await flushPromises();
    expect(get).not.toHaveBeenCalled();
    const expected = assignments.map((value, i) => [String(i + 1), names[i], String(value)]);
    expect(cells(f.wrapper)).toEqual(expected);
    f.owner.scope = "restored_summary";
    await f.inspection.openDataTable(); await flushPromises();
    expect(f.wrapper.findAll("thead th").map(cell => cell.text())).toEqual(["#", "Label", "Value"]);
    expect(cells(f.wrapper)).toEqual(expected);
    expect(get.mock.calls.map(call => call[0])).toEqual([
      "/runs/694/outputs/model_1/default", "/runs/694/outputs/model_1/metadata",
    ]);
    for (const call of get.mock.calls) expect(call[1]).toEqual({ params: { project_id: 138 }, signal: expect.any(AbortSignal) });
    expect(f.output.value.metadata.source_labels).toEqual(names);
  });

  it.each(["missing", "unqualified", "wrong payload"])("refuses %s companion without using summary labels", async failure => {
    const f = fixture();
    get.mockImplementation(async (url: string) => {
      if (!url.endsWith("/metadata")) return exact(assignments);
      if (failure === "missing") throw new Error("410 missing");
      if (failure === "wrong payload") return exact(assignments);
      return { data: { value: companion, evidence: { state: "reduced" } } };
    });
    await f.inspection.openDataTable(); await flushPromises();
    expect(f.inspection.quickPlotNodeOutput.value).toBeNull();
    expect(f.inspection.showDataTableModal.value).toBe(false);
    expect(f.wrapper.find("table").exists()).toBe(false);
    expect(f.unavailable).toHaveBeenCalled();
  });

  it("does not request or inherit primary specimen metadata for a secondary port", async () => {
    const f = fixture("restored_summary", "embedding");
    await f.inspection.openDataTable(); await flushPromises();
    expect(get.mock.calls.map(call => call[0])).toEqual(["/runs/694/outputs/model_1/embedding"]);
    expect(f.inspection.quickPlotNodeOutput.value?.metadata.source_labels).toBeUndefined();
    expect(f.wrapper.findAll("thead th").map(cell => cell.text())).toEqual(["#", "Value"]);
    expect(cells(f.wrapper)).toEqual(assignments.map((value, i) => [String(i + 1), String(value)]));
  });

  it("does not invent a retained companion from top-level summary metadata", async () => {
    const f = fixture();
    delete f.output.value.ports!.metadata;
    await f.inspection.openDataTable(); await flushPromises();
    expect(get.mock.calls.map(call => call[0])).toEqual(["/runs/694/outputs/model_1/default"]);
    expect(f.inspection.quickPlotNodeOutput.value?.metadata.source_labels).toBeUndefined();
    expect(f.wrapper.findAll("thead th").map(cell => cell.text())).toEqual(["#", "Value"]);
  });

  it.each(["project", "run", "node"] as const)("ignores delayed companion after %s A→B→A and keeps new context usable", async key => {
    const f = fixture();
    let release!: (value: ReturnType<typeof exact>) => void;
    const delayed = new Promise<ReturnType<typeof exact>>(resolve => { release = resolve; });
    get.mockImplementation((url: string) => url.endsWith("/metadata") ? delayed : Promise.resolve(exact(assignments)));
    const old = f.inspection.openDataTable(); await flushPromises();
    expect(get.mock.calls.some(call => call[0].endsWith("/metadata"))).toBe(true);
    const previous = f.owner[key];
    Object.assign(f.owner, { [key]: key === "node" ? "other" : 999 });
    Object.assign(f.owner, { [key]: previous });
    get.mockImplementation(async (url: string) => exact(url.endsWith("/metadata") ? companion : assignments));
    await f.inspection.openDataTable(); await flushPromises();
    release(exact({ ...companion, source_labels: names.map(() => "stale") }));
    await old; await flushPromises();
    expect(cells(f.wrapper)).toEqual(assignments.map((value, i) => [String(i + 1), names[i], String(value)]));
    expect(f.unavailable).not.toHaveBeenCalled();
    expect(f.inspection.quickPlotLoading.value).toBe(false);
  });
});
