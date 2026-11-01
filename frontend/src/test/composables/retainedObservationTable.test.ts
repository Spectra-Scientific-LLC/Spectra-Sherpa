import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h, reactive, ref } from "vue";
import { describe, expect, it, vi } from "vitest";
import PrimeVue from "primevue/config";
import DataTableModal from "@/views/workflow-builder/modals/DataTableModal.vue";
import ObservationExclusionButton from "@/components/ObservationExclusionButton.vue";
import { useInspectorRetainedEvidence } from "@/views/workflow-builder/composables/useInspectorRetainedEvidence";
import { buildNodeOutput } from "@/utils/nodeOutput";
import { WORKFLOW_POPULATION_ACTIONS } from "@/utils/workflowPopulation";
import type { NodeTypeMetadata, NodePresentationContract } from "@/types";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/api/client", () => ({ default: { get } }));
const exact = (value: unknown) => ({ data: { value, evidence: { state: "exact", storage: "file" } } });

// Same typed ports/axis shape as hash-verified Wine Run3 (177 computed/178
// display rows). Synthetic values make accidental display-value substitution obvious.
function fixture() {
  const refs = Array.from({ length: 178 }, (_, i) => `data_1:${"a".repeat(64)}:${i}`);
  const axis = (references: string[]) => ({ labels: references.map(reference => `Sample${Number(reference.split(":").at(-1)) + 1}`),
    workflow_observation_refs: references, include_mask: references.map(reference => reference !== refs[0]) });
  const scores = { type: "SherpaDataset", shape: [177, 3], data: refs.slice(1).map((_, i) => [i + 1, i + 2, i + 3]),
    y_axis: axis(refs.slice(1)), x_axis: { labels: ["PC1", "PC2", "PC3"] } };
  const display = { ...scores, shape: [178, 3], data: refs.map(() => [99991, 99992, 99993]), y_axis: axis(refs) };
  const companion = { availability: "available", outputs: { default: display, scores: display } };
  const contract = { digest: "b".repeat(64), payload: { schema_version: "spectrasherpa-node-presentation/1",
    default_presentation: "scores", presentations: [{ presentation_id: "scores", kind: "pca_scores", label: "Summary",
      modes: ["plot", "table"], source_ports: ["scores"], output_binding: ["scores", "sample_axis"] }] } } as NodePresentationContract;
  const metadata = { output_ports: [{ name: "default" }, { name: "scores" }] } as NodeTypeMetadata;
  const source = ref(buildNodeOutput({ default: scores, scores, __workflow_population: companion }, metadata.output_ports,
    null, null, contract));
  const owner = reactive({ project: 1, run: 3 });
  const change = vi.fn();
  const unavailable = vi.fn();
  let inspection!: ReturnType<typeof useInspectorRetainedEvidence>;
  const wrapper = mount(defineComponent({ setup() {
    inspection = useInspectorRetainedEvidence({ identity: () => [owner.project, owner.run, "model_1"],
      nodeId: () => "model_1", projectId: () => owner.project, runId: () => owner.run, evidenceScope: () => "restored_summary",
      metadata: ref(metadata), output: source, presentationId: ref("scores"), inputs: () => [], descriptors: () => null,
      unavailable, closeContextDialogs: vi.fn(),
    });
    return () => inspection.showDataTableModal.value && inspection.quickPlotNodeOutput.value
      ? h(DataTableModal, { modelValue: true, nodeOutput: inspection.quickPlotNodeOutput.value,
        nodeType: "model.pca", nodeLabel: "Fit PCA" }) : h("div");
  } }), { global: { plugins: [PrimeVue], stubs: {
    Dialog: { template: "<div><slot /></div>" }, MethodHelp: true,
  }, provide: { [WORKFLOW_POPULATION_ACTIONS]: {
    scope: () => `${owner.project}:${owner.run}`, change,
    resolve: (reference: string) => refs.includes(reference) ? { excluded: reference === refs[0] || reference === refs[158], restorable: true } : null,
    populations: () => [{ schema_version: "spectrasherpa-workflow-population/1", source_node_id: "data_1", source_digest: "a".repeat(64),
      identity_basis: "typed_sample_id", source_count: 178, active_count: 176, workflow_excluded_count: 2,
      rows: refs.map((reference, index) => ({ observation_ref: reference, source_row: index + 1,
        sample_id: `id-${index}`, sample_label: `Sample${index + 1}`, source_included: true,
        included: index !== 0 && index !== 158, workflow_excluded: index === 0 || index === 158, result_row: index || null })),
    }],
  } } } });
  get.mockImplementation(async (url: string) => exact(url.endsWith("/__workflow_population") ? companion : scores));
  return { wrapper, inspection, scores, companion, owner, refs, change, unavailable };
}

describe("native retained PCA View Data", () => {
  it("hydrates the exact display identity cohort while keeping all 177 computed rows and Sample159 membership", async () => {
    const f = fixture();
    const before = JSON.stringify(f.scores);
    try {
      await f.inspection.openDataTable(); await flushPromises();
      expect(get.mock.calls.some(([url]) => url.endsWith("/__workflow_population"))).toBe(true);
      const rows = f.wrapper.findAll("tbody tr");
      expect(rows).toHaveLength(178);
      expect(rows[0].text()).toContain("Sample1");
      expect(rows[0].findAll("td").slice(-3).map(cell => cell.text())).toEqual(["-", "-", "-"]);
      expect(rows.slice(1).map(row => row.findAll("td").slice(-3).map(cell => Number(cell.text())))).toEqual(f.scores.data);
      const controls = f.wrapper.findAllComponents(ObservationExclusionButton);
      expect(controls.map(control => control.props("observationRef"))).toEqual(f.refs);
      expect(controls[0].props("usedInResult")).toBe(false);
      expect(controls[158].props("usedInResult")).toBe(true);
      expect(controls[158].find("button").attributes("title")).toBe("Restore Sample159.");
      await controls[0].find("button").trigger("click");
      expect(f.change).toHaveBeenCalledWith([f.refs[0]], false);
      expect(f.inspection.quickPlotNodeOutput.value?.data).toEqual(f.scores.data);
      expect(JSON.stringify(f.scores)).toBe(before);
    } finally { f.wrapper.unmount(); get.mockReset(); }
  });

  it.each(["missing", "reduced", "wrong branch"])("keeps exact active values without inventing excluded rows when companion is %s", async failure => {
    const f = fixture();
    try {
      get.mockImplementation(async (url: string) => {
        if (!url.endsWith("/__workflow_population")) return exact(f.scores);
        if (failure === "missing") throw new Error("Missing retained companion");
        if (failure === "reduced") return { data: { value: f.companion, evidence: { state: "reduced", storage: "file" } } };
        const changed = structuredClone(f.companion);
        changed.outputs.scores.y_axis.workflow_observation_refs[1] = `other:${"b".repeat(64)}:1`;
        return exact(changed);
      });
      await f.inspection.openDataTable(); await flushPromises();
      expect(f.inspection.quickPlotEvidenceError.value).toBe("");
      expect(f.unavailable).not.toHaveBeenCalled();
      const rows = f.wrapper.findAll("tbody tr");
      expect(rows).toHaveLength(177);
      expect(rows.map(row => row.findAll("td").slice(-3).map(cell => Number(cell.text())))).toEqual(f.scores.data);
      expect(f.wrapper.findAllComponents(ObservationExclusionButton).map(control => control.props("observationRef"))).toEqual(f.refs.slice(1));
    } finally { f.wrapper.unmount(); get.mockReset(); }
  });
});
