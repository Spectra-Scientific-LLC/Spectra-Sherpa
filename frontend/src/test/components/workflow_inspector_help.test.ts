import { flushPromises, shallowMount } from "@vue/test-utils";
import { defineComponent, reactive } from "vue";
import { describe, expect, it, vi } from "vitest";

import DisabledReason from "@/components/DisabledReason.vue";
import WorkflowInspector from "@/views/workflow-builder/WorkflowInspector.vue";
import { projectScientificPresentation, resolveScientificPresentation } from "@/utils/scientificPresentation";

const nodeMetadata = reactive({
  presentation_contract: { digest: "b".repeat(64), payload: {
    schema_version: "spectrasherpa-node-presentation/1", default_presentation: "component_selection",
    presentations: [{ kind: "validation_result", presentation_id: "component_selection", source_ports: ["component_curve"], modes: ["record"], label: "Component selection", description: "" }],
  } },
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
vi.mock("@/stores/auth", () => ({ useAuthStore: () => ({ user: { id: 1 }, token: "local" }) }));
vi.mock("@/stores/workbook", () => ({ useWorkbookStore: () => ({ projectId: 1, activeSheet: { id: "sheet-1" } }) }));
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
          MethodHelp: false,
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

  it("links component methodology without pre-fitting prose and keeps wiring warnings", async () => {
    const wrapper = mountInspector();
    await wrapper.setProps({
      selectedNode: { ...selectedNode, type: "model.fitted_pls", params: {
        n_components: 4, component_curve_max: 8, component_cv_folds: 3,
      } },
      inputConnections: [{ nodeId: "split_1", nodeType: "data.train_test_split", nodeLabel: "Split",
        port: "X_train", toPort: "X", data: { data: [], metadata: { summary: { n_samples: 60 } } } }],
    });
    expect(wrapper.find('[aria-label="Planned component validation"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("Exact fold membership");
    expect(wrapper.find('a[href$="#component-selection"]').exists()).toBe(false);
    await wrapper.setProps({ inputConnections: [{ nodeId: "split_1", nodeType: "data.train_test_split", nodeLabel: "Split",
      port: "X_test", toPort: "X", data: { data: [], metadata: { summary: { n_samples: 20 } } } }] });
    expect(wrapper.get('[role="alert"]').text()).toContain("connect the split’s training ports");
    expect(wrapper.find('a[href$="#component-selection"]').exists()).toBe(true);
  });

  it("does not misclassify a retained MCR fitted record as not a model", async () => {
    const wrapper = mountInspector();
    const value = { n_components: 3, fitted_state_serializer: "spectrasherpa.model-artifact.mcr-als/2" };
    await wrapper.setProps({
      selectedNode: { ...selectedNode, type: "model.mcr_als", label: "Fit MCR-ALS" },
      nodeOutput: { data: [], metadata: { diagnostics: value },
        ports: { model: { value, metadata: { diagnostics: value } } },
        presentation_contract: { digest: "d".repeat(64), payload: {
          schema_version: "spectrasherpa-node-presentation/1", default_presentation: "model",
          presentations: [{ presentation_id: "model", label: "Fitted MCR-ALS Decomposition",
            kind: "metric_record", source_ports: ["model"], modes: ["record"] }],
        } },
      },
    });
    expect(wrapper.text()).not.toContain("not a fitted model");
    expect(wrapper.text()).not.toContain("Structured scientific result");
    expect(wrapper.get("details.node-identity").attributes("open")).toBeUndefined();
    expect(wrapper.get('[data-testid="inspector-canonical-node-type"]').text()).toContain("model.mcr_als");
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

  it.each(["plot", "table"])("loads exact retained output before opening a restored %s", async (view) => {
    apiGet.mockClear();
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
        data: [[1]], metadata: { diagnostics: { sample_labels: ["A", "B"], T2_limit: 9.35 } }, primary_port: "default",
        ports: { default: { data: [[1]], metadata: {}, value: exact } },
        presentation_contract: { digest: "a".repeat(64), payload: {
          schema_version: "spectrasherpa-node-presentation/1", default_presentation: "spectra",
          presentations: [{ presentation_id: "spectra", label: "Spectra", kind: "spectral_dataset",
            source_ports: ["default"], modes: ["plot", "table"], description: "Spectra" }],
        } },
      },
    });
    await flushPromises();
    await (wrapper.vm as any)[view === "plot" ? "openQuickPlot" : "openDataTable"]();
    await flushPromises();
    expect(apiGet).toHaveBeenCalledWith("/runs/3/outputs/clip_1/default", { params: { project_id: 1 }, signal: expect.any(AbortSignal) });
    if (view === "plot") {
      expect(apiGet).toHaveBeenCalledWith("/runs/3/outputs/source_1/default", { params: { project_id: 1 }, signal: expect.any(AbortSignal) });
    } else {
      expect(apiGet).toHaveBeenCalledTimes(1);
      expect((wrapper.vm as any).showDataTableModal).toBe(true);
    }
    expect((wrapper.vm as any).quickPlotNodeOutput.data).toEqual([[1, 2], [3, 4]]);
    expect((wrapper.vm as any).quickPlotNodeOutput.metadata.diagnostics).toEqual({ sample_labels: ["A", "B"], T2_limit: 9.35 });
    if (view === "table") {
      (wrapper.vm as any).showDataTableModal = false;
      apiGet.mockRejectedValueOnce(new Error("Exact evidence missing"));
      await (wrapper.vm as any).openDataTable();
      expect((wrapper.vm as any).showDataTableModal).toBe(false);
      expect((wrapper.vm as any).quickPlotNodeOutput).toBeNull();
      expect((wrapper.vm as any).quickPlotEvidenceError).toContain("unavailable");
    }
    wrapper.unmount();
    workflowStore.restoredRunId = null;
    workflowStore.executionEvidenceScope = "unavailable";
  });

  it("opens Detailed View with the same exact populations as Quick Plot and retains alternate ports", async () => {
    apiGet.mockClear();
    workflowStore.restoredRunId = 3;
    workflowStore.executionEvidenceScope = "restored_summary";
    const exact = { type: "SherpaDataset", data: Array.from({ length: 150 }, (_, i) => [i, i + 1]),
      metadata: { data_role: "X_features" },
      y_axis: { labels: Array.from({ length: 150 }, (_, i) => `sample-${i}`),
        include_mask: Array.from({ length: 150 }, (_, i) => i !== 5) },
      x_axis: { labels: ["feature-A", "feature-B"], units: "cm" } };
    const preview = { ...exact, data: exact.data.slice(0, 20) };
    const contract = { digest: "a".repeat(64), payload: {
      schema_version: "spectrasherpa-node-presentation/1", default_presentation: "spectra",
      presentations: [{ presentation_id: "spectra", label: "Spectra", kind: "spectral_dataset",
        source_ports: ["default"], modes: ["plot", "table"], description: "" }],
    } };
    apiGet.mockImplementation(async (url: string) => ({ data: { value: url.endsWith("/auxiliary") ? [1, 2, 3] : exact } }));
    const wrapper = mountInspector();
    try {
      await wrapper.setProps({ selectedNode: { ...selectedNode, id: "scale_1", type: "preprocess.scale" },
        inputConnections: [{ nodeId: "source_1", nodeType: "data.file_load", nodeLabel: "Load",
          port: "default", toPort: "X", data: { data: preview.data, metadata: {}, value: preview } }],
        nodeOutput: { data: preview.data, metadata: {}, primary_port: "default", model_id: "retained-artifact",
          ports: { default: { data: preview.data, metadata: {}, value: preview },
            auxiliary: { data: [0], metadata: {}, value: [0] } }, presentation_contract: contract },
      });
      const vm = wrapper.vm as any;
      await vm.openQuickPlot();
      const quickPlotValue = vm.quickPlotNodeOutput.presentation_value;
      const quickPlotInput = vm.quickPlotResolvedInputs.X.value;
      vm.showQuickPlotModal = false;
      await vm.openToRunTrials();
      const [detail] = wrapper.emitted("open-trial")!.at(-1)! as any[];
      expect(detail.output.data).toHaveLength(150);
      expect(detail.output.ports.default.value).toEqual(quickPlotValue);
      expect(detail.output.ports.auxiliary.value).toEqual([1, 2, 3]);
      expect(detail.output.model_id).toBe("retained-artifact");
      expect(detail.output.presentation_contract).toEqual(contract);
      expect(detail.inputConnections[0].data.value).toEqual(quickPlotInput);
      expect(detail.inputConnections[0].toPort).toBe("X");
      expect(detail.inputData.shape).toEqual([150, 2]);
      expect(detail.inputConnections[0].data.value.y_axis.include_mask[5]).toBe(false);
      expect(detail.output.ports.default.value.x_axis.units).toBe("cm");
      expect(vm.showQuickPlotModal).toBe(false);
      expect(vm.showDataTableModal).toBe(false);
      expect(wrapper.props("nodeOutput")!.data).toHaveLength(20);
    } finally {
      wrapper.unmount();
      workflowStore.restoredRunId = null;
      workflowStore.executionEvidenceScope = "unavailable";
    }
  });

  it("preserves primary model context when Quick Plot and Detailed View select a secondary port", async () => {
    workflowStore.restoredRunId = 3;
    workflowStore.executionEvidenceScope = "restored_summary";
    const scores = { type: "SherpaDataset", data: [[1, 2], [3, 4]], metadata: {
      pc_labels: ["PC1 (70.0%)", "PC2 (30.0%)"], explained_variance_ratio: [0.7, 0.3],
    } };
    const loadings = { type: "SherpaDataset", data: [[0.1, 0.2], [0.3, 0.4]],
      metadata: { y_title: "Principal Component" } };
    apiGet.mockImplementation(async (url: string) => ({ data: { value: url.endsWith("/loadings") ? loadings : scores } }));
    const wrapper = mountInspector();
    try {
      await wrapper.setProps({ selectedNode, nodeOutput: { data: [[0]], metadata: scores.metadata, primary_port: "default",
        ports: { default: { data: [[0]], metadata: scores.metadata },
          loadings: { data: [[0]], metadata: loadings.metadata } },
        presentation_contract: { digest: "e".repeat(64), payload: {
          schema_version: "spectrasherpa-node-presentation/1", default_presentation: "scores",
          presentations: [
            { presentation_id: "scores", label: "Scores", kind: "pca_scores", source_ports: ["default"], modes: ["plot"] },
            { presentation_id: "loadings", label: "Loadings", kind: "pca_loadings", source_ports: ["loadings"], modes: ["plot"] },
          ],
        } },
      } });
      const vm = wrapper.vm as any;
      vm.selectedPresentationId = "loadings";
      await vm.openQuickPlot();
      const quick = vm.quickPlotNodeOutput;
      vm.showQuickPlotModal = false;
      await vm.openToRunTrials();
      const [detail] = wrapper.emitted("open-trial")!.at(-1)! as any[];
      const projected = projectScientificPresentation(detail.output,
        resolveScientificPresentation(null, detail.output, "loadings"));
      expect(quick.metadata.pc_labels).toEqual(scores.metadata.pc_labels);
      expect(projected!.metadata.pc_labels).toEqual(quick.metadata.pc_labels);
      expect(projected!.presentation_value).toEqual(quick.presentation_value);
    } finally {
      wrapper.unmount();
      workflowStore.restoredRunId = null;
      workflowStore.executionEvidenceScope = "unavailable";
    }
  });

  it.each([["y_test", "X_test"], ["references", "held_population"]])("hydrates the declared cohort %s → %s", async (responsePort, cohortPort) => {
    apiGet.mockClear();
    apiGet.mockImplementation(async (url: string) => ({ data: { value: url.endsWith("/" + cohortPort)
      ? { type: "SherpaDataset", data: [[1]], y_axis: { labels: ["held-B"] } } : [2] } }));
    workflowStore.restoredRunId = 3;
    workflowStore.executionEvidenceScope = "restored_summary";
    const wrapper = mountInspector();
    await wrapper.setProps({ selectedNode: { ...selectedNode, id: "split_1" }, nodeOutput: {
      data: [2], metadata: {}, primary_port: responsePort,
      ports: { [responsePort]: { data: [2], metadata: {}, value: [2] },
        X_train: { data: [[9]], metadata: {} }, [cohortPort]: { data: [[1]], metadata: {} } },
      presentation_contract: { digest: "c".repeat(64), payload: {
        schema_version: "spectrasherpa-node-presentation/1", default_presentation: "references",
        presentations: [{ presentation_id: "references", label: "References", kind: "target_matrix",
          source_ports: [responsePort], modes: ["plot", "table"], description: "",
          output_binding: [cohortPort, "target_context"] }],
      } },
    } });
    await (wrapper.vm as any).openDataTable();
    expect(apiGet.mock.calls.map(call => call[0])).toEqual([
      "/runs/3/outputs/split_1/" + responsePort, "/runs/3/outputs/split_1/" + cohortPort,
    ]);
    wrapper.unmount();
    workflowStore.restoredRunId = null;
    workflowStore.executionEvidenceScope = "unavailable";
  });

  it("hydrates same-model feature authority for coefficient rows, not unrelated sample ports", async () => {
    apiGet.mockClear();
    apiGet.mockResolvedValue({ data: { value: [[1]] } });
    workflowStore.restoredRunId = 3;
    workflowStore.executionEvidenceScope = "restored_summary";
    const wrapper = mountInspector();
    await wrapper.setProps({ selectedNode: { ...selectedNode, id: "model_1" }, nodeOutput: {
      data: [[1]], metadata: {}, primary_port: "class_coefficients",
      ports: { class_coefficients: { data: [[1]], metadata: {},
        descriptor: { dimensions: [{ role: "spectral_variable", size: 1 }] } },
        feature_coordinates: { data: [[1]], metadata: {} },
        loadings: { data: [[999]], metadata: {} }, scores: { data: [[2]], metadata: {} } },
      presentation_contract: { digest: "c".repeat(64), payload: {
        schema_version: "spectrasherpa-node-presentation/1", default_presentation: "coefficients",
        presentations: [{ presentation_id: "coefficients", label: "Coefficients", kind: "regression_coefficients",
          source_ports: ["class_coefficients"], modes: ["plot", "table"], description: "",
          output_binding: ["feature_coordinates", "feature_axis"] }],
      } },
    } as any });
    await (wrapper.vm as any).openDataTable();
    expect(apiGet.mock.calls.map(call => call[0])).toEqual([
      "/runs/3/outputs/model_1/class_coefficients", "/runs/3/outputs/model_1/feature_coordinates",
    ]);
    wrapper.unmount();
    workflowStore.restoredRunId = null;
    workflowStore.executionEvidenceScope = "unavailable";
  });

  it("hydrates a declared feature input for retained tables", async () => {
    apiGet.mockClear();
    apiGet.mockImplementation(async (url: string) => ({ data: { value: url.endsWith("/spectra")
      ? { type: "SherpaDataset", data: [[1, 2]], x_axis: { data: [1100, 1102], units: "nm" } }
      : [0.8, 1.2] } }));
    workflowStore.restoredRunId = 3;
    workflowStore.executionEvidenceScope = "restored_summary";
    const wrapper = mountInspector();
    await wrapper.setProps({ selectedNode: { ...selectedNode, id: "model_1" },
      inputConnections: [{ nodeId: "selection_1", port: "spectra", toPort: "features", data: null }],
      nodeOutput: { data: [0.8, 1.2], metadata: {}, primary_port: "importance",
        ports: { importance: { data: [0.8, 1.2], metadata: {} } },
        presentation_contract: { digest: "c".repeat(64), payload: {
          schema_version: "spectrasherpa-node-presentation/1", default_presentation: "importance",
          presentations: [{ presentation_id: "importance", label: "Importance", kind: "variable_profile",
            source_ports: ["importance"], modes: ["plot", "table"], description: "",
            input_binding: ["features", "feature_axis"] }],
        } },
      },
    } as any);
    await (wrapper.vm as any).openDataTable();
    expect(apiGet.mock.calls.map(call => call[0])).toEqual([
      "/runs/3/outputs/model_1/importance", "/runs/3/outputs/selection_1/spectra",
    ]);
    expect((wrapper.vm as any).quickPlotNodeOutput.metadata.feature_names).toEqual(["1100", "1102"]);
    wrapper.unmount();
    workflowStore.restoredRunId = null;
    workflowStore.executionEvidenceScope = "unavailable";
  });

  it("hydrates PCA summary companions from the same retained run", async () => {
    apiGet.mockClear();
    apiGet.mockResolvedValue({ data: { value: [[1, 2]] } });
    workflowStore.restoredRunId = 3;
    workflowStore.executionEvidenceScope = "restored_summary";
    const wrapper = mountInspector();
    await wrapper.setProps({ selectedNode, nodeOutput: {
      data: [[1, 2]], metadata: {}, primary_port: "scores",
      ports: Object.fromEntries(["scores", "variable_correlations", "explained_variance", "loadings", "model"].map(name => [name, { data: [[1, 2]], metadata: {} }])),
      presentation_contract: { digest: "b".repeat(64), payload: {
        schema_version: "spectrasherpa-node-presentation/1", default_presentation: "scores",
        presentations: [{ presentation_id: "scores", label: "Scores", kind: "pca_scores", source_ports: ["scores"], modes: ["plot", "table"] }],
      } },
    } as any });
    await (wrapper.vm as any).openQuickPlot();
    expect(apiGet.mock.calls.map(call => call[0])).toEqual(["scores", "variable_correlations", "explained_variance", "loadings"].map(port => `/runs/3/outputs/pca_1/${port}`));
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
