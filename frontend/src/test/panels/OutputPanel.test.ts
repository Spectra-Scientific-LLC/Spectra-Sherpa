import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import { ref, computed } from "vue";
import OutputPanel from "@/views/workflow-builder/node-detail/panels/OutputPanel.vue";
import {
  NODE_DETAIL_STATE_KEY,
  type NodeDetailState,
} from "@/views/workflow-builder/node-detail/state/useNodeDetailState";

/* eslint-disable @typescript-eslint/no-explicit-any */

interface OutputOverrides {
  summary?: string;
  hasOutput?: boolean;
  data?: any;
  metadata?: Record<string, any>;
  subsections?: NodeDetailState["output"]["subsections"]["value"];
  datasetInfo?: any;
  processingHistory?: any;
  provenance?: any;
  quality?: any;
  isRegressionNode?: boolean;
  regressionTargetOptions?: { label: string; value: number }[];
  regressionTargetIdx?: number;
  portSummaries?: any[];
  preview?: { rows: any[]; columns: { field: string; header: string }[]; summary: string };
  pcaDiagnostics?: { rows: any[]; columns: { field: string; header: string }[]; summary: string };
}

function makeState(overrides: OutputOverrides = {}): NodeDetailState {
  const regressionTargetIdx = ref(overrides.regressionTargetIdx ?? 0);
  return {
    output: {
      summary: ref(overrides.summary ?? ""),
      hasOutput: ref(overrides.hasOutput ?? true),
      data: ref(overrides.data ?? null),
      metadata: ref(overrides.metadata ?? {}),
      subsections: ref(
        overrides.subsections ?? {
          coordinates: false,
          metadata: false,
          processing: false,
          provenance: false,
          quality: false,
          ports: false,
        },
      ),
      datasetInfo: ref(overrides.datasetInfo ?? null),
      datasetLabelTable: ref({ headers: [], rows: [] }),
      labelPreviewLimit: 10,
      processingHistory: ref(overrides.processingHistory ?? null),
      provenance: ref(overrides.provenance ?? null),
      quality: ref(overrides.quality ?? null),
      portSummaries: ref(overrides.portSummaries ?? []),
      preview: computed(() => overrides.preview ?? { rows: [], columns: [], summary: "" }),
      pcaDiagnostics: computed(
        () => overrides.pcaDiagnostics ?? { rows: [], columns: [], summary: "" },
      ),
      isRegressionNode: ref(overrides.isRegressionNode ?? false),
      regressionTargetOptions: ref(overrides.regressionTargetOptions ?? []),
      selectedRegressionR2: ref(null),
      selectedRegressionRmse: ref(null),
      getMetaTooltip: () => "",
      formatMetaValue: (v: unknown) => String(v),
    },
    plots: ref({
      hasOutput: false, availablePlots: [], nodeTypeKey: "",
      isPCAOutput: false, isPreprocessingNode: false, isDataNode: false,
      isSpectraData: false, isGenericDataNode: false, nodeOutput: null,
      contourClickPoint: null, pcaAxisOptions: [], regressionTargetOptions: [],
      spectraDisplayOptions: [], genericDisplayOptions: [], featureOptions: [],
      holdoutVisualization: null,
    }),
    writable: {
      pcaXAxis: ref(0),
      pcaYAxis: ref(1),
      plsdaLoadingsViewMode: ref("lines"),
      regressionTargetIdx,
      spectraDisplayMode: ref("overlay"),
      genericDisplayMode: ref("boxplot"),
      featureXAxis: ref(0),
      featureYAxis: ref(1),
      contourClickPoint: ref(null),
    },
    plotSections: ref({}),
  };
}

function factory(overrides: OutputOverrides = {}, expanded = true) {
  const state = makeState(overrides);
  const wrapper = mount(OutputPanel, {
    props: { expanded },
    global: {
      provide: { [NODE_DETAIL_STATE_KEY as symbol]: state },
      stubs: {
        Transition: false,
        DataTable: true,
        Column: true,
        Dropdown: true,
        Button: {
          props: ["label"],
          template: '<button :aria-label="label" @click="$emit(\'click\')"><slot/></button>',
        },
      },
    },
  });
  return { wrapper, state };
}

describe("OutputPanel", () => {
  it("renders empty state when hasOutput is false", () => {
    const { wrapper } = factory({ hasOutput: false });
    expect(wrapper.text()).toContain("No output data available");
  });

  it("renders rows / cols / type / range stats when outputData is present", () => {
    const { wrapper } = factory({
      data: { rows: 50, cols: 10, type: "PCA scores", range: [-1.5, 1.5] },
    });
    expect(wrapper.text()).toContain("50");
    expect(wrapper.text()).toContain("PCA scores");
    expect(wrapper.text()).toContain("-1.500 - 1.500");
  });

  it("emits toggleSub with the correct subsection key", async () => {
    const { wrapper } = factory({ processingHistory: [{ operation: "scale" }] });
    const toggles = wrapper.findAll(".inspector-toggle");
    expect(toggles.length).toBeGreaterThan(0);
    await toggles[0].trigger("click");
    const events = wrapper.emitted("toggleSub");
    expect(events).toBeTruthy();
    expect(["coordinates", "metadata", "processing", "provenance", "quality", "ports"]).toContain(
      events?.[0]?.[0] as string,
    );
  });

  it("expands metadata subsection and renders key/value pairs", () => {
    const { wrapper } = factory({
      metadata: { n_components: 3, explained_variance: 0.92 },
      subsections: {
        coordinates: false,
        metadata: true,
        processing: false,
        provenance: false,
        quality: false,
        ports: false,
      },
    });
    expect(wrapper.text()).toContain("n_components");
    expect(wrapper.text()).toContain("3");
    expect(wrapper.text()).toContain("explained_variance");
  });

  it("renders processing timeline when processingHistory is expanded", () => {
    const { wrapper } = factory({
      processingHistory: [
        { operation: "snv", parameters: {}, input_shape: [80, 700], output_shape: [80, 700] },
        "smooth",
      ],
      subsections: {
        coordinates: false,
        metadata: false,
        processing: true,
        provenance: false,
        quality: false,
        ports: false,
      },
    });
    expect(wrapper.findAll(".timeline-item")).toHaveLength(2);
    expect(wrapper.text()).toContain("snv");
    expect(wrapper.text()).toContain("smooth");
    expect(wrapper.text()).toContain("In: 80×700");
  });

  it("renders port summary cards when portSummaries is non-empty + expanded", () => {
    const { wrapper } = factory({
      portSummaries: [{ name: "scores", type: "dataset", shape: [50, 3] }],
      subsections: {
        coordinates: false,
        metadata: false,
        processing: false,
        provenance: false,
        quality: false,
        ports: true,
      },
    });
    expect(wrapper.findAll(".port-summary-card")).toHaveLength(1);
    expect(wrapper.text()).toContain("scores");
    expect(wrapper.text()).toContain("Shape: 50×3");
  });

  it("emits the action events from the output-actions buttons", async () => {
    const { wrapper } = factory();
    const click = (label: string) =>
      wrapper.find(`button[aria-label="${label}"]`).trigger("click");
    await click("View Full Metadata (JSON)");
    await click("View Data Table");
    await click("Quick Plot");
    await click("Export CSV");
    expect(wrapper.emitted("showFullMetadata")).toBeTruthy();
    expect(wrapper.emitted("openDataTable")).toBeTruthy();
    expect(wrapper.emitted("openQuickPlot")).toBeTruthy();
    expect(wrapper.emitted("exportOutput")).toBeTruthy();
  });

  it("mutating regressionTargetIdx via the shared writable ref propagates to the state object", async () => {
    const { wrapper, state } = factory({
      isRegressionNode: true,
      regressionTargetOptions: [
        { label: "all", value: -1 },
        { label: "target 0", value: 0 },
      ],
      quality: { latest_model_type: "pls" },
      subsections: {
        coordinates: false,
        metadata: false,
        processing: false,
        provenance: false,
        quality: true,
        ports: false,
      },
    });
    const dropdown = wrapper.findComponent({ name: "Dropdown" });
    dropdown.vm.$emit("update:model-value", 0);
    await wrapper.vm.$nextTick();
    expect(state.writable.regressionTargetIdx.value).toBe(0);
  });
});
