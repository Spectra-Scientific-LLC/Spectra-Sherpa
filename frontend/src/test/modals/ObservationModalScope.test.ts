import { flushPromises, mount } from "@vue/test-utils";
import { nextTick, ref } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PrimeVue from "primevue/config";
import producerFixture from "@/test/fixtures/observation-score-plot.json";
import QuickPlotModal from "@/views/workflow-builder/modals/QuickPlotModal.vue";
import DataTableModal from "@/views/workflow-builder/modals/DataTableModal.vue";
import ObservationExclusionButton from "@/components/ObservationExclusionButton.vue";
import { buildNodeOutput } from "@/utils/nodeOutput";
import { projectScientificPresentation, resolveScientificPresentation } from "@/utils/scientificPresentation";
import { WORKFLOW_POPULATION_ACTIONS } from "@/utils/workflowPopulation";

vi.mock("plotly.js-cartesian-dist-min", () => ({ default: {
  react: vi.fn(), relayout: vi.fn(), restyle: vi.fn(), purge: vi.fn(), Plots: { resize: vi.fn() },
} }));
const refs = [0, 1, 2].map(index => `load:${"a".repeat(64)}:${index}`);
async function settle() { await flushPromises(); await nextTick(); }

function output() {
  const dataset = { type: "SherpaDataset", data: [[21, 22], [31, 32]],
    sample_axis: { labels: ["Repeated", "Repeated"], workflow_observation_refs: refs.slice(1) },
    feature_axis: { labels: ["PC1", "PC2"] } };
  const raw = buildNodeOutput({ scores: dataset }, [
    { name: "scores", type_ref: "spectrasherpa://types/ScoreMatrix/1.0", required: true, label: "Scores" },
  ]);
  raw.presentation_contract = { schema_version: "spectrasherpa-node-presentation/1", digest: "test", payload: {
    default_presentation: "scores", presentations: [{ presentation_id: "scores", label: "Summary",
      kind: "pca_scores", modes: ["plot", "table"], source_ports: ["scores"], output_binding: ["scores", "sample_axis"] }],
  } } as typeof raw.presentation_contract;
  raw.metadata.workflow_population = { outputs: { scores: { ...dataset, data: [[999, 999], ...dataset.data],
    sample_axis: { labels: ["Repeated", "Repeated", "Repeated"], workflow_observation_refs: refs, include_mask: [false, true, true] } } } };
  return projectScientificPresentation(raw, resolveScientificPresentation(null, raw))!;
}

describe.each([
  { name: "QuickPlot matrix", component: QuickPlotModal, coordinates: false },
  { name: "QuickPlot plot coordinates", component: QuickPlotModal, coordinates: true },
  { name: "DataTable", component: DataTableModal, coordinates: false },
])("$name open-time scope", ({ component, coordinates }) => {
  beforeEach(() => vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} }));
  afterEach(() => vi.unstubAllGlobals());
  it("survives closed workflow load, rejects a stale open across A→B→A, and admits explicit reopening", async () => {
    const scope = ref("loading");
    const change = vi.fn();
    const nodeOutput = coordinates ? buildNodeOutput({ visualization: structuredClone(producerFixture) }, [
      { name: "visualization", type_ref: "spectrasherpa://types/Visualization/1.0", required: true, label: "Plot" },
    ]) : output();
    if (coordinates) {
      nodeOutput.presentation_value = nodeOutput.ports!.visualization.value;
      nodeOutput.metadata.scientific_presentation = { schema_version: "spectrasherpa-node-presentation/1",
        contract_digest: "b".repeat(64), presentation_id: "visualization", source_port: "visualization",
        source_ports: ["visualization"], kind: "visualization", modes: ["plot", "table"] };
    }
    const expectedRefs = coordinates ? [refs[2], refs[0], refs[1]] : refs;
    const original = structuredClone(nodeOutput);
    const wrapper = mount(component, {
      props: { modelValue: false, nodeOutput, nodeType: coordinates ? "output.plot" : "model.pca", nodeLabel: "Scores", tableOnly: !coordinates },
      global: { plugins: [PrimeVue], stubs: {
        Dialog: { template: "<div><slot /></div>" }, Dropdown: true, Button: { props: ["label"], template: "<button>{{ label }}</button>" }, Paginator: true, MethodHelp: true,
      }, provide: { [WORKFLOW_POPULATION_ACTIONS]: {
        scope: () => scope.value, change,
        resolve: (reference: string) => refs.includes(reference) ? { excluded: reference === refs[0], restorable: true } : null,
        populations: () => [{ schema_version: "spectrasherpa-workflow-population/1", source_node_id: "load",
          source_digest: "a".repeat(64), identity_basis: "typed_sample_id", source_count: 3, active_count: 2, workflow_excluded_count: 1,
          rows: refs.map((reference, index) => ({ observation_ref: reference, source_row: index + 1,
            sample_id: `id-${index}`, sample_label: "Repeated", source_included: true, included: index !== 0,
            workflow_excluded: index === 0, result_row: index || null })),
        }],
      } } },
    });
    try {
      await settle();
      expect(wrapper.findAllComponents(ObservationExclusionButton)).toHaveLength(0);
      scope.value = "workflow:A";
      await settle();
      await wrapper.setProps({ modelValue: true });
      await settle();
      if (coordinates) {
        await wrapper.findAll("button").find(button => button.text() === "View Data")!.trigger("click");
        await settle();
      }
      const controls = wrapper.findAllComponents(ObservationExclusionButton);
      expect(controls.map(control => control.props("observationRef"))).toEqual(expectedRefs);
      expect(controls.map(control => control.props("usedInResult"))).toEqual(coordinates ? [true, true, true] : [false, true, true]);
      await controls.find(control => control.props("observationRef") === refs[0])!.find("button").trigger("click");
      expect(change).toHaveBeenLastCalledWith([refs[0]], false);
      scope.value = "workflow:B";
      await settle();
      expect(wrapper.findAllComponents(ObservationExclusionButton)).toHaveLength(0);
      expect(wrapper.findAll("tbody tr")).toHaveLength(coordinates ? 3 : 2);
      scope.value = "workflow:A";
      await settle();
      expect(wrapper.findAllComponents(ObservationExclusionButton)).toHaveLength(0);
      await wrapper.setProps({ modelValue: false });
      scope.value = "workflow:B";
      await wrapper.setProps({ modelValue: true });
      await settle();
      if (coordinates) {
        await wrapper.findAll("button").find(button => button.text() === "View Data")!.trigger("click");
        await settle();
      }
      const reopened = wrapper.findAllComponents(ObservationExclusionButton);
      expect(reopened.map(control => control.props("observationRef"))).toEqual(expectedRefs);
      await reopened.find(control => control.props("observationRef") === refs[1])!.find("button").trigger("click");
      expect(change).toHaveBeenLastCalledWith([refs[1]], true);
      expect(change).toHaveBeenCalledTimes(2);
      expect(nodeOutput).toEqual(original);
    } finally { wrapper.unmount(); }
  });
});
