import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, it, expect, vi } from "vitest";
import { ref, computed } from "vue";
import OutputPanel from "@/views/workflow-builder/node-detail/panels/OutputPanel.vue";
import {
  NODE_DETAIL_STATE_KEY,
  type NodeDetailState,
} from "@/views/workflow-builder/node-detail/state/useNodeDetailState";

/* eslint-disable @typescript-eslint/no-explicit-any */

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  routerPush: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: {
    get: mocks.apiGet,
  },
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({
    push: mocks.routerPush,
  }),
}));

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
  modelId?: string | null;
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
          modelArtifact: true,
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
      modelId: ref<string | null>(overrides.modelId ?? null),
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
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders saved model artifact provenance links from the current artifact schema", async () => {
    mocks.apiGet.mockResolvedValueOnce({
      data: {
        artifact_uid: "artifact-123456",
        name: "PLSDA — auto",
        display_name: "Wine PLSDA v1",
        model_type: "plsda",
        n_features: 13,
        n_components: 3,
        source_run_id: 42,
        training_dataset_id: 7,
        metrics: { cv_accuracy: 0.91 },
      },
    });

    const { wrapper } = factory({ modelId: "artifact-123456" });
    await flushPromises();

    expect(mocks.apiGet).toHaveBeenCalledWith("/models/artifact-123456");
    expect(wrapper.text()).toContain("Wine PLSDA v1");
    expect(wrapper.text()).toContain("Source Run");
    expect(wrapper.text()).toContain("#42");
    expect(wrapper.text()).toContain("Training Dataset");
    expect(wrapper.text()).toContain("Dataset #7");

    await wrapper.findAll(".artifact-link")[0].trigger("click");
    expect(mocks.routerPush).toHaveBeenCalledWith({ path: "/runs", query: { run: "42" } });
    await wrapper.findAll(".artifact-link")[1].trigger("click");
    expect(mocks.routerPush).toHaveBeenCalledWith({ path: "/data", query: { experiment: "7" } });
  });

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

  it("renders sample-axis port cardinality as samples rather than label count", () => {
    const { wrapper } = factory({
      portSummaries: [
        {
          name: "X_test",
          type: "dataset",
          shape: [196, 401],
          xTitle: "Wavelength",
          xUnits: "nm",
          xPoints: 401,
          yTitle: "Sample",
          yCount: 196,
          yCountLabel: "samples",
          nLabels: 20,
        },
      ],
      subsections: {
        coordinates: false,
        metadata: false,
        processing: false,
        provenance: false,
        quality: false,
        ports: true,
      },
    });

    expect(wrapper.text()).toContain("X: Wavelength (nm), 401 pts");
    expect(wrapper.text()).toContain("Y: Sample, 196 samples");
    expect(wrapper.text()).not.toContain("20 labels");
  });

  it("renders explicit zero axis and sample counts", () => {
    const { wrapper } = factory({
      datasetInfo: {
        xAxis: { title: "Feature", units: "", points: 0 },
        yAxis: { title: "Sample", nSamples: 0 },
      },
      subsections: {
        coordinates: true,
        metadata: false,
        processing: false,
        provenance: false,
        quality: false,
        ports: true,
      },
      portSummaries: [
        {
          name: "empty",
          type: "dataset",
          xTitle: "Feature",
          xPoints: 0,
          yTitle: "Sample",
          yCount: 0,
          yCountLabel: "samples",
        },
      ],
    });

    expect(wrapper.text()).toContain("X Points");
    expect(wrapper.text()).toContain("0 pts");
    expect(wrapper.text()).toContain("0 samples");
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
