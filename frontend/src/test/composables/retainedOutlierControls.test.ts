import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h, nextTick, ref } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PrimeVue from "primevue/config";
import QuickPlotModal from "@/views/workflow-builder/modals/QuickPlotModal.vue";
import DataTableModal from "@/views/workflow-builder/modals/DataTableModal.vue";
import ObservationExclusionButton from "@/components/ObservationExclusionButton.vue";
import { useInspectorRetainedEvidence } from "@/views/workflow-builder/composables/useInspectorRetainedEvidence";
import { buildNodeOutput } from "@/utils/nodeOutput";
import { WORKFLOW_POPULATION_ACTIONS } from "@/utils/workflowPopulation";
import type { NodeTypeMetadata, NodePresentationContract } from "@/types";
const { get, react, on } = vi.hoisted(() => ({ get: vi.fn(), react: vi.fn(), on: vi.fn() }));
vi.mock("@/api/client", () => ({ default: { get } }));
vi.mock("plotly.js-cartesian-dist-min", () => ({ default: { react, relayout: vi.fn(), restyle: vi.fn(), purge: vi.fn(), Plots: { resize: vi.fn() } } }));
const refs = [0, 1, 2].map(i => `data:${"a".repeat(64)}:${i}`);
const metadata = { output_ports: [{ name: "default" }, { name: "T2" }, { name: "Q" }, { name: "flags" }] } as NodeTypeMetadata;
const contract = { digest: "b".repeat(64), payload: { schema_version: "spectrasherpa-node-presentation/1", default_presentation: "diagnostics",
  presentations: [{ presentation_id: "diagnostics", kind: "t2_q_diagnostics", label: "T²/Q", source_ports: ["T2", "Q", "flags"],
    sample_labels_field: "sample_labels", modes: ["plot", "table"] }] } } as NodePresentationContract;
function fixture(view: "plot" | "table", bad = false) {
  const values: Record<string, unknown> = { default: { type: "PCA" }, T2: [1, 20, 3], Q: [2, 3, 4], flags: [false, true, false],
    sample_labels: ["Duplicate", "Duplicate", "Third"], metadata: { observation_axis: { labels: ["Duplicate", "Duplicate", "Third"],
      workflow_observation_refs: refs, include_mask: [true, true, true] } } };
  const output = ref(buildNodeOutput(values, metadata.output_ports, null, null, contract));
  get.mockImplementation(async (url: string) => ({ data: { value: values[url.split("/").at(-1)!],
    evidence: { state: bad && url.endsWith("/metadata") ? "reduced" : "exact", storage: "file" } } }));
  const change = vi.fn(), unavailable = vi.fn();
  let inspection!: ReturnType<typeof useInspectorRetainedEvidence>;
  const wrapper = mount(defineComponent({ setup() {
    inspection = useInspectorRetainedEvidence({ identity: () => [1, 52], nodeId: () => "outliers", projectId: () => 1, runId: () => 52,
      evidenceScope: () => "restored_summary", metadata: ref(metadata), output, presentationId: ref("diagnostics"), inputs: () => [],
      descriptors: () => null, unavailable, closeContextDialogs: vi.fn() });
    return () => (view === "plot" ? inspection.showQuickPlotModal.value : inspection.showDataTableModal.value)
      ? h(view === "plot" ? QuickPlotModal : DataTableModal, { modelValue: true, nodeOutput: inspection.quickPlotNodeOutput.value,
        nodeType: "diagnostics.outliers", nodeLabel: "Outliers" }) : h("div");
  } }), { global: { plugins: [PrimeVue], stubs: { Dialog: { template: "<div><slot /></div>" }, MethodHelp: true, Dropdown: true, Paginator: true },
    provide: { [WORKFLOW_POPULATION_ACTIONS]: { scope: () => "workflow:1", resolve: (r: string) => refs.includes(r)
      ? { excluded: false, restorable: true } : null, change, populations: () => [] } } } });
  return { wrapper, inspection, change, unavailable };
}
beforeEach(() => {
  on.mockClear(); react.mockReset(); get.mockReset();
  react.mockImplementation(async (element: HTMLElement & { on: unknown }) => { element.on = on; });
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
});
afterEach(() => vi.unstubAllGlobals());
describe("reopened outlier curation", () => {
  it.each(["plot", "table"] as const)("hydrates exact references for %s, including duplicate labels", async view => {
    const f = fixture(view);
    try {
      await (view === "plot" ? f.inspection.openQuickPlot() : f.inspection.openDataTable()); await flushPromises(); await nextTick();
      expect(get.mock.calls.some(([url]) => url.endsWith("/metadata"))).toBe(true);
      expect(f.unavailable).not.toHaveBeenCalled();
      if (view === "plot") {
        const trace = react.mock.calls.at(-1)![1].find((t: { name: string }) => t.name === "Screened outlier");
        expect(trace.meta.workflow_observation_refs).toEqual([refs[1]]);
        on.mock.calls.find(([event]) => event === "plotly_click")![1]({ points: [{ pointIndex: 0, data: trace }] }); await nextTick();
        await f.wrapper.findAll("button").find(button => button.text() === "Exclude selected")!.trigger("click");
      } else {
        const buttons = f.wrapper.findAllComponents(ObservationExclusionButton);
        expect(buttons.map(b => b.props("observationRef"))).toEqual(refs);
        await buttons[1].find("button").trigger("click");
      }
      expect(f.change).toHaveBeenCalledWith([refs[1]], true);
    } finally { f.wrapper.unmount(); }
  });
  it.each(["plot", "table"] as const)("does not authorize %s curation from reduced metadata", async view => {
    const f = fixture(view, true);
    try {
      await (view === "plot" ? f.inspection.openQuickPlot() : f.inspection.openDataTable()); await flushPromises();
      expect(f.inspection.quickPlotEvidenceError.value).toContain("exact retained output is unavailable");
      expect(f.inspection.quickPlotNodeOutput.value).toBeNull();
      expect(f.change).not.toHaveBeenCalled();
    } finally { f.wrapper.unmount(); }
  });
});
