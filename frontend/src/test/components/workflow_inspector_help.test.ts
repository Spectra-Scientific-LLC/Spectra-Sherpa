import { flushPromises, shallowMount } from "@vue/test-utils";
import { defineComponent, reactive } from "vue";
import { describe, expect, it, vi } from "vitest";

import DisabledReason from "@/components/DisabledReason.vue";
import WorkflowInspector from "@/views/workflow-builder/WorkflowInspector.vue";

const nodeMetadata = reactive({
  label: "Principal Component Analysis",
  parameters: [],
  execution_contract: {
    digest: "a".repeat(64),
    payload: { help_reference: "docs/nodes/exploratory.md" },
  },
});

const workflowStore = reactive({
  nodes: [],
  edges: [],
  workflowId: 1 as number | null,
  getNodeMetadata: vi.fn(() => nodeMetadata),
  validateNodeParams: vi.fn(() => []),
  fetchReferenceDatasets: vi.fn(),
  executeTrial: vi.fn(),
  saveWorkflow: vi.fn(async () => 77),
  restoredRunId: null as number | null,
  executionEvidenceScope: "unavailable",
  lastExecutionResultDescriptors: {} as Record<string, unknown>,
});

const routerPush = vi.fn();
const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));

vi.mock("@/api/client", () => ({ default: { get: apiGet } }));
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: vi.fn() }) }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: routerPush }) }));
vi.mock("@/stores/workflow", () => ({ useWorkflowStore: () => workflowStore }));
vi.mock("@/stores/project", () => ({
  useProjectStore: () => ({ currentProjectId: 1 }),
}));

const selectedNode = {
  id: "pca_1",
  type: "model.pca",
  label: "PCA",
  x: 0,
  y: 0,
  params: {},
};

describe("WorkflowInspector node help", () => {
  const mountInspector = () =>
    shallowMount(WorkflowInspector, {
      props: { selectedNode: null, nodeOutput: null, isOpen: true },
      global: {
        directives: { tooltip: () => undefined },
        stubs: {
          QuickPlotModal: defineComponent({ template: "<div />" }),
          DataTableModal: defineComponent({ template: "<div />" }),
        },
      },
    });

  it("renders the selected node contract as a keyboard-native secure new-tab link", async () => {
    const wrapper = mountInspector();
    await wrapper.setProps({ selectedNode });

    const link = wrapper.get('[data-testid="inspector-node-help"]');
    expect(link.element.tagName).toBe("A");
    expect(link.attributes("href")).toBe("https://docs.spectrascientific.ai/nodes/exploratory/");
    expect(link.attributes("target")).toBe("_blank");
    expect(link.attributes("rel")).toBe("noopener noreferrer");
    expect(link.text()).toBe("?");
    expect(link.attributes("title")).toContain("Learn about this node");
    expect(link.attributes("aria-label")).toContain("opens in a new tab");
  });

  it("previews component validation before fitting without claiming executed folds", async () => {
    const wrapper = mountInspector();
    await wrapper.setProps({
      selectedNode: { ...selectedNode, type: "model.fitted_pls", params: {
        n_components: 4, component_curve_max: 8, component_cv_folds: 3,
      } },
      inputConnections: [{ nodeId: "split_1", nodeType: "data.train_test_split", nodeLabel: "Split",
        port: "X_train", toPort: "X", data: { data: [], metadata: { summary: { n_samples: 60 } } } }],
    });
    const preview = wrapper.get('[aria-label="Planned component validation"]').text();
    expect(preview).toContain("4 LV requested");
    expect(preview).toContain("3-fold group or row CV");
    expect(preview).toContain("Connected calibration rows: 60");
    expect(preview).toContain("test partition stays outside component selection");
    expect(preview).toContain("Exact fold membership");
    await wrapper.setProps({ inputConnections: [{ nodeId: "split_1", nodeType: "data.train_test_split", nodeLabel: "Split",
      port: "X_test", toPort: "X", data: { data: [], metadata: { summary: { n_samples: 20 } } } }] });
    expect(wrapper.get('[aria-label="Planned component validation"]').text()).toContain("without a verified training port");
  });

  it("fails closed when the selected node contract has no safe help authority", async () => {
    nodeMetadata.execution_contract.payload.help_reference = "../../private.md";
    const wrapper = mountInspector();
    await wrapper.setProps({ selectedNode });

    expect(wrapper.find('[data-testid="inspector-node-help"]').exists()).toBe(false);
    nodeMetadata.execution_contract.payload.help_reference = "docs/nodes/exploratory.md";
  });

  it("shows an in-sheet Data Portfolio picker for collection loads", async () => {
    workflowStore.workflowId = null;
    workflowStore.saveWorkflow.mockClear();
    routerPush.mockClear();
    const wrapper = mountInspector();
    await wrapper.setProps({
      selectedNode: {
        ...selectedNode,
        id: "collection_load_1",
        type: "data.collection_load",
        label: "Collection Load",
      },
    });

    await flushPromises();
    expect(wrapper.findComponent({ name: 'WorkflowDataPortfolioPicker' }).exists()).toBe(true);
    expect(wrapper.find('[data-testid="configure-sheet-data"]').exists()).toBe(false);
    expect(routerPush).not.toHaveBeenCalled();
    workflowStore.workflowId = 1;
  });

  it("loads exact retained output and its immediate input before plotting a restored run", async () => {
    workflowStore.restoredRunId = 3;
    workflowStore.executionEvidenceScope = "restored_summary";
    const exact = { type: "SherpaDataset", data: [[1, 2], [3, 4]], metadata: {},
      y_axis: { include_mask: [true, true], labels: ["A", "B"] },
      x_axis: { data: [1000, 1100] } };
    apiGet.mockImplementation(async () => ({ data: { value: exact } }));
    const wrapper = mountInspector();
    await wrapper.setProps({
      selectedNode: { ...selectedNode, id: "clip_1", type: "preprocess.clip_range" },
      inputConnections: [{ nodeId: "source_1", nodeType: "data.file_load", nodeLabel: "Load",
        port: "default", toPort: "default", data: null }],
      nodeOutput: {
        data: [[1]], metadata: {}, primary_port: "default",
        ports: { default: { data: [[1]], metadata: {}, value: exact } },
        presentation_contract: { digest: "a".repeat(64), payload: {
          schema_version: "spectrasherpa-node-presentation/1", default_presentation: "spectra",
          presentations: [{ presentation_id: "spectra", label: "Spectra", kind: "spectral_dataset",
            source_ports: ["default"], modes: ["plot", "table"], description: "Spectra" }],
        } },
      },
    });
    await flushPromises();
    await (wrapper.vm as any).openQuickPlot();
    await flushPromises();
    expect(apiGet).toHaveBeenCalledWith("/runs/3/outputs/clip_1/default", { params: { project_id: 1 } });
    expect(apiGet).toHaveBeenCalledWith("/runs/3/outputs/source_1/default", { params: { project_id: 1 } });
    expect((wrapper.vm as any).quickPlotNodeOutput.data).toEqual([[1, 2], [3, 4]]);
    wrapper.unmount();
    workflowStore.restoredRunId = null;
    workflowStore.executionEvidenceScope = "unavailable";
  });

  it("hides generic axis selectors when an output node receives a declared visualization", async () => {
    const wrapper = mountInspector();
    await wrapper.setProps({
      selectedNode: { ...selectedNode, type: "output.plot", label: "PCA Scores" },
      nodeOutput: {
        data: [{ type: "scatter", x: [1], y: [2] }],
        metadata: {},
        ports: {
          visualization: {
            data: [{ type: "scatter", x: [1], y: [2] }],
            metadata: {},
            value: { data: [{ type: "scatter", x: [1], y: [2] }], layout: {} },
          },
        },
        presentation_contract: {
          digest: "b".repeat(64),
          payload: {
            schema_version: "spectrasherpa-node-presentation/1",
            default_presentation: "plot",
            presentations: [
              {
                presentation_id: "plot",
                label: "Plot",
                kind: "visualization",
                source_ports: ["visualization"],
                modes: ["plot"],
                description: "Declared visualization.",
              },
            ],
          },
        },
      },
    });

    expect(wrapper.text()).not.toContain("X-Axis");
    expect(wrapper.text()).not.toContain("Y-Axis");
    expect(wrapper.text()).toContain("No adjustable parameters");
  });

  it("labels PCA statistics by component and reports cumulative variance", async () => {
    const wrapper = mountInspector();
    const rows = [
      { pc: 1, mean: 0, std: 0.5163 },
      { pc: 2, mean: 0, std: 0.3284 },
      { pc: 3, mean: 0, std: 0.0874 },
    ];
    await wrapper.setProps({
      selectedNode: { ...selectedNode, type: "stats.summary", label: "Summarize Scores" },
      nodeOutput: {
        data: rows,
        metadata: {},
        ports: {
          default: {
            data: rows,
            value: { data: rows },
            metadata: {
              type: "PCA",
              summary: {
                n_observations: 50,
                n_components: 3,
                total_variance_explained: 0.982729,
              },
            },
          },
        },
        presentation_contract: {
          digest: "c".repeat(64),
          payload: {
            schema_version: "spectrasherpa-node-presentation/1",
            default_presentation: "summary",
            presentations: [
              {
                presentation_id: "summary",
                label: "Summary",
                kind: "statistics_summary",
                source_ports: ["default"],
                modes: ["record"],
                description: "PCA score summary.",
              },
            ],
          },
        },
      },
    });

    expect(wrapper.text()).toContain("PC1");
    expect(wrapper.text()).toContain("PC2");
    expect(wrapper.text()).toContain("PC3");
    expect(wrapper.text()).toContain("50 samples × 3 components; 98.3% variance explained");
  });

  it("says in visible text why Run Node is unavailable, and links the button to it", async () => {
    const wrapper = mountInspector();
    await wrapper.setProps({
      selectedNode,
      executionDisabled: true,
      executionDisabledReason: "Only the governed Harness may execute it.",
    });

    const reason = wrapper.getComponent(DisabledReason);
    expect(reason.props("reason")).toBe("Only the governed Harness may execute it.");
    const run = wrapper.findAll("button-stub, [label]").find((b) => b.attributes("label") === "Run Node");
    expect(run?.attributes("aria-describedby")).toBe(reason.props("id"));

    await wrapper.setProps({ executionDisabled: false, executionDisabledReason: "" });
    expect(wrapper.getComponent(DisabledReason).props("reason")).toBe("");
    const enabled = wrapper.findAll("button-stub, [label]").find((b) => b.attributes("label") === "Run Node");
    expect(enabled?.attributes("aria-describedby")).toBeUndefined();
  });
});


it.each([
  ["classification.simca", { metrics: { schema_version: 1, task_type: "classification", method: "simca", evidence_scope: "calibration_fit_diagnostics_not_validation_evidence" }, train_f1_macro: 0.8 }, {}, "rejection label is not an additional class"],
  ["clustering.dbscan", { silhouette_score: 0.24 }, { quality_summary: { population: "non_noise_samples_only" } }, "DBSCAN noise samples are excluded"],
])("shows metric population explanations beside %s diagnostics", async (type, diagnostics, metadata, note) => {
  const wrapper = shallowMount(WorkflowInspector, {
    props: { selectedNode: { ...selectedNode, type: String(type) }, isOpen: true,
      nodeOutput: { data: [[1]], metadata: { ...metadata, diagnostics },
        ports: { default: { data: [[1]], value: { ...metadata }, metadata: { ...metadata } } },
        presentation_contract: { digest: "a".repeat(64), payload: {
          schema_version: "spectrasherpa-node-presentation/1", default_presentation: "metrics",
          presentations: [{ presentation_id: "metrics", label: "Metrics", kind: "metric_record", source_ports: ["default"], modes: ["record"] }],
        } },
      } as any },
    global: { directives: { tooltip: () => undefined }, stubs: {
      QuickPlotModal: defineComponent({ template: "<div />" }),
      DataTableModal: defineComponent({ template: "<div />" }),
    } },
  });
  const card = wrapper.findAll(".diagnostics-card").find(card => card.text().includes("Scientific Diagnostics"));
  expect(card?.find('[role="note"]').text()).toContain(note);
});
