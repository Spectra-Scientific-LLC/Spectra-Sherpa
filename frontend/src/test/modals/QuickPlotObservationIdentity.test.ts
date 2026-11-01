import { flushPromises, mount } from "@vue/test-utils";
import { nextTick, ref } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ObservationExclusionButton from "@/components/ObservationExclusionButton.vue";
import PrimeVue from "primevue/config";
import Paginator from "primevue/paginator";
import { useDisplayPreferences } from "@/composables/useDisplayPreferences";
import producerFixture from "@/test/fixtures/observation-score-plot.json";
import compactFixture from "@/test/fixtures/observation-spectrum-plot.json";
import QuickPlotModal from "@/views/workflow-builder/modals/QuickPlotModal.vue";
import { buildNodeOutput } from "@/utils/nodeOutput";
import { projectScientificPresentation, resolveScientificPresentation } from "@/utils/scientificPresentation";
import { WORKFLOW_POPULATION_ACTIONS } from "@/utils/workflowPopulation";

const plotly = vi.hoisted(() => ({ react: vi.fn(), on: vi.fn() }));
vi.mock("plotly.js-cartesian-dist-min", () => ({ default: {
  react: plotly.react, relayout: vi.fn(), restyle: vi.fn(), purge: vi.fn(),
  downloadImage: vi.fn(), Plots: { resize: vi.fn() },
} }));

const refs = [0, 1, 2].map(i => `load:${"a".repeat(64)}:${i}`);
const stubs = {
  Dialog: { template: "<div><slot /></div>" }, Dropdown: true,
  Button: { props: ["label", "disabled"], template: '<button :disabled="disabled">{{ label }}</button>' },
  Paginator: true, MethodHelp: true,
};
async function settle() { await flushPromises(); await nextTick(); }

describe("Quick Plot visualization observation identity", () => {
  beforeEach(() => {
    plotly.on.mockClear(); plotly.react.mockReset();
    plotly.react.mockImplementation(async (element: HTMLElement & { on: unknown }) => { element.on = plotly.on; });
    vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  });
  afterEach(() => vi.unstubAllGlobals());

  function view(declared: boolean, identified: boolean, withPopulation = false, withCompanion = false) {
    // Coincident coordinates and repeated editable labels cannot identify rows.
    // Trace order deliberately differs from source order and crosses classes.
    // Bound to actual PlotNode.execute by test_plot_observation_refs.py.
    const visualization = structuredClone(producerFixture);
    if (!identified) visualization.data.forEach(trace => { delete (trace as { meta?: unknown }).meta; });
    const fullVisualization = structuredClone(visualization);
    if (withCompanion) {
      fullVisualization.data[0].meta.workflow_included[1] = false;
      const trace = visualization.data[0];
      trace.x.splice(1, 1); trace.y.splice(1, 1); trace.text.splice(1, 1);
      trace.meta.workflow_observation_refs.splice(1, 1); trace.meta.workflow_included.splice(1, 1);
    }
    const output = buildNodeOutput({ visualization }, [
      { name: "visualization", type_ref: "spectrasherpa://types/Visualization/1.0", required: true, label: "Plot" },
    ]);
    if (declared) {
      output.presentation_contract = { schema_version: "spectrasherpa-node-presentation/1", digest: "b".repeat(64), payload: {
        default_presentation: "visualization", presentations: [{ presentation_id: "visualization", label: "Visualization",
          kind: "visualization", modes: ["plot", "table"], source_ports: ["visualization"] }],
      } } as typeof output.presentation_contract;
      output.presentation_value = visualization;
      output.metadata.scientific_presentation = {
        schema_version: "spectrasherpa-node-presentation/1", contract_digest: "b".repeat(64),
        presentation_id: "visualization", source_port: "visualization", source_ports: ["visualization"],
        kind: "visualization", modes: ["plot"],
      };
    }
    if (withCompanion) output.metadata.workflow_population = { availability: "available", sources: {},
      outputs: { visualization: fullVisualization } };
    const original = structuredClone(output);
    const change = vi.fn();
    const resolve = vi.fn((ref: string) => refs.includes(ref) ? { excluded: withPopulation && ref === refs[0], restorable: true } : null);
    const populations = () => withPopulation ? [{
      schema_version: "spectrasherpa-workflow-population/1", source_node_id: "load", source_digest: "a".repeat(64),
      identity_basis: "typed_sample_id", source_count: 3, active_count: 3, workflow_excluded_count: 0,
      rows: refs.map((ref, i) => ({ observation_ref: ref, source_row: i + 1,
        sample_id: `id-${i}`, sample_label: "Repeated", source_included: true, included: true,
        workflow_excluded: false, result_row: i + 1 })),
    }] : [];
    const wrapper = mount(QuickPlotModal, { props: {
      modelValue: true, embedded: true, nodeType: "output.plot", nodeLabel: "Scores", nodeOutput: output,
      // An adjacent matrix is not authority to reconstruct missing trace refs.
      nodeInput: { data: [[1, 2], [1, 2], [1, 2]], sample_axis: {
        labels: ["Repeated", "Repeated", "Repeated"], workflow_observation_refs: refs,
      } },
    }, global: { plugins: [PrimeVue], stubs, provide: { [WORKFLOW_POPULATION_ACTIONS]: { resolve, change, populations, scope: () => "workflow:1" } } } });
    return { wrapper, output, original, change };
  }

  it.each([false, true])("preserves producer refs through click/lasso with declared=%s", async declared => {
    const { wrapper, output, original, change } = view(declared, true);
    try {
      await settle();
      const [, plotted, , config] = plotly.react.mock.calls.at(-1)!;
      expect(plotted.map((trace: { meta: unknown }) => trace.meta)).toEqual([
        { workflow_observation_refs: [refs[2], refs[0]], workflow_included: [true, true] },
        { workflow_observation_refs: [refs[1]], workflow_included: [true] },
      ]);
      expect(config.modeBarButtonsToRemove).not.toContain("lasso2d");
      expect(config.modeBarButtonsToRemove).not.toContain("select2d");
      const handler = (name: string) => plotly.on.mock.calls.find(([event]) => event === name)![1];
      handler("plotly_click")({ points: [{ pointIndex: 1, data: plotted[0] }] });
      await nextTick();
      await wrapper.findAll("button").find(button => button.text() === "Exclude selected")!.trigger("click");
      expect(change).toHaveBeenLastCalledWith([refs[0]], true);
      handler("plotly_selected")({ points: [
        { pointIndex: 0, data: plotted[0] }, { pointIndex: 0, data: plotted[1] },
      ] });
      await nextTick();
      await wrapper.findAll("button").find(button => button.text() === "Exclude selected")!.trigger("click");
      expect(change).toHaveBeenLastCalledWith([refs[2], refs[1]], true);
      expect(output).toEqual(original);
    } finally { wrapper.unmount(); }
  });

  it("shows compact status in the existing coordinates, with exact refs and no extra table", async () => {
    const { wrapper, output, original, change } = view(true, true, true);
    try {
      await settle();
      await wrapper.findAll("button").find(button => button.text() === "View Data")!.trigger("click");
      await settle();
      expect(wrapper.findAll("table")).toHaveLength(1);
      expect(wrapper.text()).not.toContain("Observation exclusion map");
      const controls = wrapper.findAllComponents(ObservationExclusionButton);
      expect(controls.map(control => control.props("observationRef"))).toEqual([refs[2], refs[0], refs[1]]);
      expect(controls.map(control => control.props("usedInResult"))).toEqual([true, true, true]);
      expect(wrapper.findAll("tbody tr")[1].find('[role="img"]').attributes("title")).toBe("Used in this result");
      expect(controls[1].find("button").attributes("title")).toBe("Restore Repeated.");
      await controls[1].find("button").trigger("click");
      expect(change).toHaveBeenLastCalledWith([refs[0]], false);
      const rows = wrapper.vm as unknown as { dataPreview: Array<{ x: number; y: number }> };
      expect(rows.dataPreview).toHaveLength(3);
      expect(rows.dataPreview.map(row => [row.x, row.y])).toEqual([[1, 2], [1, 2], [1, 2]]);
      expect(wrapper.findAll("th").slice(0, 2).map(th => th.text())).toEqual(["", ""]);
      expect(wrapper.find("table").text()).not.toContain("load:");
      expect(output).toEqual(original);
    } finally { wrapper.unmount(); }
  });

  it("renders only an explicit excluded display companion, retaining active coordinates unchanged", async () => {
    const { wrapper, output, original, change } = view(true, true, true, true);
    try {
      await settle();
      const [, plotted] = plotly.react.mock.calls.at(-1)!;
      expect(plotted[0].meta.workflow_observation_refs).toEqual([refs[2], refs[0]]);
      expect(plotted[0].meta.workflow_included).toEqual([true, false]);
      expect(plotted[0].marker.symbol[1]).toBe("x-open");
      await wrapper.findAll("button").find(button => button.text() === "View Data")!.trigger("click");
      await settle();
      const controls = wrapper.findAllComponents(ObservationExclusionButton);
      expect(controls.map(control => control.props("usedInResult"))).toEqual([true, false, true]);
      expect(wrapper.findAll("tbody tr")[1].find('[role="img"]').attributes("title")).toBe("Not used in this result");
      await controls[1].find("button").trigger("click");
      expect(change).toHaveBeenLastCalledWith([refs[0]], false);
      expect(wrapper.findAll("table")).toHaveLength(1);
      expect(output).toEqual(original);
      expect(output.presentation_value.data[0].meta.workflow_observation_refs).toEqual([refs[2]]);
    } finally { wrapper.unmount(); }
  });

  it.each([true, false])("uses compact spectrum refs for points and retained tables, live actions=%s", async withActions => {
    const output = buildNodeOutput({ visualization: structuredClone(compactFixture) }, [
      { name: "visualization", type_ref: "spectrasherpa://types/Visualization/1.0", required: true, label: "Plot" },
    ]);
    output.presentation_value = output.ports!.visualization.value;
    output.metadata.scientific_presentation = { schema_version: "spectrasherpa-node-presentation/1",
      contract_digest: "b".repeat(64), presentation_id: "visualization", source_port: "visualization",
      source_ports: ["visualization"], kind: "visualization", modes: ["plot", "table"] };
    const original = structuredClone(output);
    const change = vi.fn();
    const scope = ref("workflow:1");
    const wrapper = mount(QuickPlotModal, { props: { embedded: true, modelValue: true,
      nodeType: "output.plot", nodeLabel: "Spectra", nodeOutput: output }, global: {
      plugins: [PrimeVue], stubs, provide: withActions ? { [WORKFLOW_POPULATION_ACTIONS]: {
        scope: () => scope.value, change, resolve: (reference: string) => refs.includes(reference)
          ? { excluded: reference === refs[1], restorable: true } : null,
      } } : {},
    } });
    try {
      await settle();
      const [, plotted] = plotly.react.mock.calls.at(-1)!;
      expect(plotted[1].meta).toEqual({ workflow_observation_ref: refs[1], workflow_included: false });
      expect(plotted[1].marker.symbol).toEqual(["x-open", "x-open"]);
      if (withActions) {
        const click = plotly.on.mock.calls.find(([event]) => event === "plotly_click")![1];
        click({ points: [{ pointIndex: 1, data: plotted[1] }] });
        await nextTick();
        await wrapper.findAll("button").find(button => button.text() === "Restore selected")!.trigger("click");
        expect(change).toHaveBeenLastCalledWith([refs[1]], false);
      }
      await wrapper.findAll("button").find(button => button.text() === "View Data")!.trigger("click");
      await settle();
      expect(wrapper.findAll("tbody tr")).toHaveLength(6);
      expect(wrapper.findAll("tbody tr")[2].find('[role="img"]').attributes("title")).toBe("Not used in this result");
      expect(wrapper.findAllComponents(ObservationExclusionButton).map(control => control.props("observationRef")))
        .toEqual(withActions ? [refs[2], refs[2], refs[1], refs[1], refs[0], refs[0]] : []);
      expect(wrapper.findAll("th").filter(th => th.text() === "")).toHaveLength(withActions ? 2 : 1);
      if (withActions) {
        await wrapper.findAllComponents(ObservationExclusionButton)[3].find("button").trigger("click");
        expect(change).toHaveBeenLastCalledWith([refs[1]], false);
        scope.value = "workflow:2";
        await settle();
        expect(wrapper.findAllComponents(ObservationExclusionButton)).toHaveLength(0);
        expect(wrapper.findAll("th").filter(th => th.text() === "")).toHaveLength(1);
      }
      expect(output).toEqual(original);
    } finally { wrapper.unmount(); }
  });

  function matrixView({ missingAxis = false, partialDisplay = false, sourceMissing = false, activeCount = 2, excludedCount = 1 } = {}) {
    const allRefs = Array.from({ length: activeCount + excludedCount }, (_, i) => `load:${"a".repeat(64)}:${i}`);
    const activeRefs = activeCount === 2 && excludedCount === 1 ? [refs[2], refs[1]] : allRefs.slice(excludedCount);
    const scoreValue = { type: "SherpaDataset", data: activeRefs.map((_, i) => [21 + 10 * i, 22 + 10 * i]),
      sample_axis: { labels: activeRefs.map(() => "Repeated"), ...(missingAxis ? {} : { workflow_observation_refs: activeRefs }) },
      feature_axis: { labels: ["PC1", "PC2"] }, metadata: {} };
    const excludedRefs = allRefs.slice(0, excludedCount);
    const displayRefs = partialDisplay ? [refs[0], refs[2]] : [...excludedRefs, ...activeRefs];
    const raw = buildNodeOutput({ scores: scoreValue }, [
      { name: "scores", type_ref: "spectrasherpa://types/ScoreMatrix/1.0", required: true, label: "Scores" },
    ]);
    raw.presentation_contract = { schema_version: "spectrasherpa-node-presentation/1", digest: "test", payload: {
      default_presentation: "scores", presentations: [{ presentation_id: "scores", label: "Summary",
        kind: "pca_scores", modes: ["plot", "table"], source_ports: ["scores"], output_binding: ["scores", "sample_axis"] }],
    } } as typeof raw.presentation_contract;
    raw.metadata.workflow_population = { availability: "available", sources: {}, outputs: {
      scores: { ...scoreValue, data: displayRefs.map(() => [99991, 99992]), sample_axis: {
        labels: displayRefs.map(() => "Repeated"), workflow_observation_refs: displayRefs,
        include_mask: displayRefs.map(reference => !excludedRefs.includes(reference)),
      } },
    } };
    const output = projectScientificPresentation(raw, resolveScientificPresentation(null, raw))!;
    const original = structuredClone(output);
    const change = vi.fn();
    const wrapper = mount(QuickPlotModal, { props: {
      embedded: true, modelValue: true, nodeType: "model.pca", nodeLabel: "Summary", nodeOutput: output,
      nodeInput: { data: scoreValue.data, sample_axis: { workflow_observation_refs: activeRefs } },
    }, global: { plugins: [PrimeVue], stubs, provide: { [WORKFLOW_POPULATION_ACTIONS]: {
      scope: () => "workflow:1", change,
      resolve: (reference: string) => ({ excluded: excludedRefs.includes(reference), restorable: true }),
      populations: () => sourceMissing ? [] : [{ schema_version: "spectrasherpa-workflow-population/1", source_node_id: "load",
        source_digest: "a".repeat(64), identity_basis: "typed_sample_id", source_count: allRefs.length, active_count: activeCount, workflow_excluded_count: excludedCount,
        rows: allRefs.map((reference, index) => ({ observation_ref: reference, source_row: index + 1, sample_id: `id-${index}`,
          sample_label: "Repeated", source_included: true, included: index >= excludedCount, workflow_excluded: index < excludedCount, result_row: index >= excludedCount ? index - excludedCount + 1 : null })),
      }],
    } } } });
    return { wrapper, output, original, change };
  }

  it("shows excluded PCA Summary observations in the original matrix with blank cells and no projected numbers", async () => {
    const { wrapper, output, original, change } = matrixView();
    try {
      await settle();
      await wrapper.findAll("button").find(button => button.text() === "View Data")!.trigger("click");
      await settle();
      expect(wrapper.findAll("table")).toHaveLength(1);
      const rows = wrapper.findAll("tbody tr");
      expect(rows).toHaveLength(3);
      expect(rows[0].find('[role="img"]').attributes("aria-label")).toBe("Not used in this result");
      expect(rows[0].findAll("td").slice(-2).map(cell => cell.text())).toEqual(["—", "—"]);
      expect(rows[1].findAll("td").slice(-2).map(cell => cell.text())).toEqual(["21", "22"]);
      expect(rows[2].findAll("td").slice(-2).map(cell => cell.text())).toEqual(["31", "32"]);
      expect(wrapper.find("table").text()).not.toContain("9999");
      expect(wrapper.findAll("th").slice(0, 2).map(th => th.text())).toEqual(["", ""]);
      const controls = wrapper.findAllComponents(ObservationExclusionButton);
      expect(controls.map(control => control.props("observationRef"))).toEqual([refs[0], refs[2], refs[1]]);
      await controls[0].find("button").trigger("click");
      expect(change).toHaveBeenLastCalledWith([refs[0]], false);
      expect(output).toEqual(original);
      const vm = wrapper.vm as unknown as { previewFirst: number };
      vm.previewFirst = 2;
      await settle();
      const nextControls = wrapper.findAllComponents(ObservationExclusionButton);
      expect(nextControls.map(control => control.props("observationRef"))).toEqual([refs[1]]);
      expect(wrapper.findAll("tbody tr")[0].findAll("td").slice(-2).map(cell => cell.text())).toEqual(["31", "32"]);
      await nextControls[0].find("button").trigger("click");
      expect(change).toHaveBeenLastCalledWith([refs[1]], true);
    } finally { wrapper.unmount(); }
  });

  it("counts calculated rows separately when a blank excluded identity consumes a preview slot", async () => {
    const preferences = useDisplayPreferences();
    const previousLimit = preferences.maxRows;
    preferences.maxRows = 100;
    const { wrapper } = matrixView({ activeCount: 100 });
    try {
      await settle();
      await wrapper.findAll("button").find(button => button.text() === "View Data")!.trigger("click");
      await settle();
      expect(wrapper.findAll("tbody tr")).toHaveLength(100);
      expect(wrapper.findAllComponents(ObservationExclusionButton).filter(control => control.props("usedInResult"))).toHaveLength(99);
      expect(wrapper.find('.display-subset-indicator').exists()).toBe(true);
      const vm = wrapper.vm as unknown as { dataPreviewSummary: string };
      expect(vm.dataPreviewSummary).toBe("1–99 of 100 rows");
      expect(wrapper.findAll('.data-summary').some(item => item.attributes("title")?.includes("Calculated observations shown"))).toBe(true);
    } finally { wrapper.unmount(); preferences.maxRows = previousLimit; }
  });

  it("uses the declared T²/Q observation axis for the same fused table without projected diagnostics", async () => {
    const { wrapper } = matrixView();
    const raw = buildNodeOutput({ T2: [2, 3], Q: [.2, .3], sample_labels: ["Repeated", "Repeated"] }, [
      { name: "T2", type_ref: "spectrasherpa://types/Array/1.0", required: true, label: "T²" },
      { name: "Q", type_ref: "spectrasherpa://types/Array/1.0", required: true, label: "Q" },
    ]);
    raw.presentation_contract = { schema_version: "spectrasherpa-node-presentation/1", digest: "test", payload: {
      default_presentation: "diagnostics", presentations: [{ presentation_id: "diagnostics", label: "Diagnostics",
        kind: "t2_q_diagnostics", modes: ["plot", "table"], source_ports: ["T2", "Q"], sample_labels_field: "sample_labels" }],
    } } as typeof raw.presentation_contract;
    raw.metadata.observation_axis = { workflow_observation_refs: refs.slice(1), include_mask: [true, true] };
    raw.metadata.workflow_population = { outputs: { T2: [999, 2, 3], Q: [999, .2, .3],
      sample_labels: ["Repeated", "Repeated", "Repeated"],
      observation_axis: { workflow_observation_refs: refs, include_mask: [false, true, true] } } };
    const output = projectScientificPresentation(raw, resolveScientificPresentation(null, raw))!;
    const original = structuredClone(output);
    try {
      await wrapper.setProps({ nodeOutput: output, tableOnly: true });
      await settle();
      const rows = wrapper.findAll("tbody tr");
      expect(rows).toHaveLength(3);
      expect(wrapper.findAllComponents(ObservationExclusionButton).map(control => control.props("observationRef"))).toEqual(refs);
      expect(rows[0].findAll("td").slice(-4).map(cell => cell.text())).toEqual(["Repeated", "—", "—", "—"]);
      expect(rows[1].findAll("td").slice(-3).map(cell => cell.text())).toEqual(["2", "0.200000", "Not screened"]);
      expect(rows[2].findAll("td").slice(-3).map(cell => cell.text())).toEqual(["3", "0.300000", "Not screened"]);
      expect(output).toEqual(original);
    } finally { wrapper.unmount(); }
  });

  it.each([1, 120])("pages every computed and excluded identity exactly once with %i exclusions", async excludedCount => {
    const preferences = useDisplayPreferences();
    const previousLimit = preferences.maxRows;
    preferences.maxRows = 100;
    const { wrapper, output, original } = matrixView({ activeCount: 101, excludedCount });
    try {
      await settle();
      await wrapper.findAll("button").find(button => button.text() === "View Data")!.trigger("click");
      await settle();
      const observed: string[] = [];
      const totals: number[] = [];
      for (let first = 0; first < 101 + excludedCount; first += 100) {
        const paginator = wrapper.findComponent(Paginator);
        totals.push(Number(paginator.attributes("total-records")));
        paginator.vm.$emit("page", { first });
        await settle();
        const controls = wrapper.findAllComponents(ObservationExclusionButton);
        const domRows = wrapper.findAll("tbody tr");
        controls.forEach((control, index) => {
          const reference = control.props("observationRef") as string;
          observed.push(reference);
          const sourceIndex = Number(reference.split(":").at(-1));
          const computedIndex = sourceIndex - excludedCount;
          expect(control.props("usedInResult")).toBe(computedIndex >= 0);
          expect(domRows[index].findAll("td").slice(-2).map(cell => cell.text())).toEqual(computedIndex < 0
            ? ["—", "—"] : [String(21 + 10 * computedIndex), String(22 + 10 * computedIndex)]);
        });
        expect(wrapper.find("table").text()).not.toContain("9999");
      }
      expect(observed).toEqual(Array.from({ length: 101 + excludedCount }, (_, i) => `load:${"a".repeat(64)}:${i}`));
      expect(new Set(observed).size).toBe(observed.length);
      expect(totals.every(total => total === 101 + excludedCount)).toBe(true);
      expect(output).toEqual(original);
    } finally { wrapper.unmount(); preferences.maxRows = previousLimit; }
  });

  it.each(["missingAxis", "partialDisplay", "sourceMissing"] as const)("does not invent omitted matrix rows with %s", async reason => {
    const { wrapper, output, original } = matrixView({ [reason]: true });
    try {
      await settle();
      await wrapper.findAll("button").find(button => button.text() === "View Data")!.trigger("click");
      await settle();
      expect(wrapper.findAll("tbody tr")).toHaveLength(2);
      expect(wrapper.find("table").text()).not.toContain("9999");
      const controls = wrapper.findAllComponents(ObservationExclusionButton);
      expect(controls.map(control => control.props("observationRef"))).toEqual(reason === "missingAxis" ? [] : [refs[2], refs[1]]);
      expect(output).toEqual(original);
    } finally { wrapper.unmount(); }
  });

  it.each([false, true])("never invents refs from adjacent input, labels or coordinates with declared=%s", async declared => {
    const { wrapper, output, original, change } = view(declared, false);
    try {
      await settle();
      const [, plotted, , config] = plotly.react.mock.calls.at(-1)!;
      expect(plotted.every((trace: { meta?: unknown }) => trace.meta === undefined)).toBe(true);
      expect(config.modeBarButtonsToRemove).toContain("lasso2d");
      plotly.on.mock.calls.find(([event]) => event === "plotly_click")![1]({ points: [{ pointIndex: 0, data: plotted[0] }] });
      await nextTick();
      expect(wrapper.find('[aria-label="Workflow observation selection"]').exists()).toBe(false);
      expect(change).not.toHaveBeenCalled();
      await wrapper.findAll("button").find(button => button.text() === "View Data")!.trigger("click");
      await settle();
      expect(wrapper.findAllComponents(ObservationExclusionButton)).toHaveLength(0);
      expect(output).toEqual(original);
    } finally { wrapper.unmount(); }
  });
});
