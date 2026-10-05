import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h, nextTick, onUnmounted, reactive } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  dataSelectionReceiptStorageKey,
  storeDataSelectionReceipt,
} from "@/utils/workflowDataSelection";

const lifecycleCounts = reactive({
  toolbarUnmounts: 0,
  inspectorUnmounts: 0,
});

const workbookStore = reactive({
  sheets: [
    {
      kind: "workflow",
      workflowId: 101,
      name: "PCA Sheet",
      purpose: "analysis",
      tabColor: null,
      sheetOrder: 0,
    },
    {
      kind: "trial",
      workflowId: -1,
      trialId: "trial-101-pca-1",
      sourceWorkflowId: 101,
      sourceNodeId: "pca_1",
      name: "Trial: PCA",
      purpose: "analysis",
      tabColor: null,
      sheetOrder: 1,
      trialData: { id: "pca_1", label: "PCA", type: "model.pca", params: { n_components: 3 } },
    },
  ],
  activeIndex: 1,
  projectId: 1,
  isLoading: false,
  get activeSheet() {
    return this.sheets[this.activeIndex] ?? null;
  },
  get activeTrialSheet() {
    return this.activeSheet?.kind === "trial" ? this.activeSheet : null;
  },
  loadSheets: vi.fn(),
  switchSheet: vi.fn(),
  addSheet: vi.fn(),
  duplicateSheet: vi.fn(),
  renameSheet: vi.fn(),
  setSheetColor: vi.fn(),
  reorderSheets: vi.fn(),
  deleteSheet: vi.fn(),
  openTrialTab: vi.fn(),
  closeTrialTab: vi.fn(async () => {
    workbookStore.sheets.splice(1, 1);
    workbookStore.activeIndex = 0;
  }),
  setLastSelectedNodeId: vi.fn(),
});

const workflowStore = reactive({
  nodes: [{ id: "pca_1", type: "model.pca", x: 0, y: 0, params: { n_components: 3 } }],
  edges: [],
  workflowId: 101,
  workflowName: "PCA Sheet",
  workflowHash: null,
  workflowWarnings: [],
  hasFoldValidationPlan: false,
  hasUnsavedChanges: false,
  isWorkflowStale: false,
  markWorkflowStale: vi.fn(),
  setNodes: vi.fn((nodes) => {
    workflowStore.nodes = nodes;
  }),
  setEdges: vi.fn((edges) => {
    workflowStore.edges = edges;
  }),
  saveWorkflow: vi.fn(),
  loadWorkflow: vi.fn(),
  clearWorkflow: vi.fn(),
  updateNode: vi.fn(),
  addNode: vi.fn(),
  getNodeMetadata: vi.fn(() => ({ label: "PCA" })),
  validateNodeParams: vi.fn(() => []),
  executeWorkflow: vi.fn(),
  exportToPython: vi.fn(),
  exportToNotebook: vi.fn(),
  downloadZipBundle: vi.fn(),
});

const workflowBuilderConfigStore = {
  autoExecute: { __v_isRef: true, value: false },
};

const projectStore = reactive({
  currentProjectId: 1,
  currentProject: {
    id: 1,
    name: "Iris PCA",
    experiment_count: 2,
    workflows: [
      {
        id: 101,
        primary_data_source_id: 702,
        data_source_ids: [702],
      },
    ],
    data_sources: [
      {
        id: 701,
        display_name: "Iris",
      },
      {
        id: 702,
        display_name: "Synthetic Atmospheric FTIR",
      },
    ],
  },
  projects: [{ id: 1 }],
  recentProjects: [{ id: 1 }],
  getLastActiveProjectId: vi.fn(() => 1),
  fetchProject: vi.fn(async () => projectStore.currentProject),
  fetchProjects: vi.fn(),
  createProject: vi.fn(),
  selectProject: vi.fn(),
  exportProject: vi.fn(async () => undefined),
  error: null as string | null,
});

const routeQuery = reactive<Record<string, string>>({ project_id: "1" });
const routeLeaveGuards: Array<() => Promise<boolean>> = [];

vi.mock("vue-router", () => ({
  useRoute: () => ({ query: routeQuery }),
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(async ({ query }) => {
      Object.keys(routeQuery).forEach((key) => {
        delete routeQuery[key];
      });
      Object.assign(routeQuery, query);
    }),
  }),
  onBeforeRouteLeave: vi.fn((guard: () => Promise<boolean>) => {
    routeLeaveGuards.push(guard);
  }),
}));

vi.mock("primevue/usetoast", () => ({
  useToast: () => ({ add: vi.fn() }),
}));

vi.mock("@/stores/workbook", () => ({
  useWorkbookStore: () => workbookStore,
}));

vi.mock("@/stores/runs", () => ({
  useRunsStore: () => ({
    saveRun: vi.fn(),
  }),
}));

vi.mock("@/stores/workflow", () => ({
  useWorkflowStore: () => workflowStore,
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({
    user: { id: 1 },
  }),
}));

vi.mock("@/stores/workflowBuilderConfig", () => ({
  useWorkflowBuilderConfigStore: () => workflowBuilderConfigStore,
}));

vi.mock("@/stores/sherpa", () => ({
  useSherpaStore: () => ({
    compactConversationMemory: vi.fn(),
  }),
}));

vi.mock("@/stores/experiment", () => ({
  useExperimentStore: () => ({
    experiments: [],
    fetchExperiments: vi.fn(),
  }),
}));

vi.mock("@/stores/project", () => ({
  useProjectStore: () => projectStore,
}));

vi.mock("@/stores/clipboard", () => ({
  useClipboardStore: () => ({
    set: vi.fn(),
    get: vi.fn(() => null),
  }),
}));

vi.mock("@/stores/advisor", () => ({
  useAdvisorStore: () => ({
    activeNodeId: null,
    switchScope: vi.fn(),
    activeNode: null,
    topics: [],
    activeTopicId: null,
  }),
}));

const ButtonStub = defineComponent({
  name: "PrimeButtonStub",
  props: {
    label: { type: String, default: "" },
    disabled: { type: Boolean, default: false },
  },
  emits: ["click"],
  template: `<button :disabled="disabled" @click="$emit('click', $event)">{{ label }}</button>`,
});

const PassiveStub = defineComponent({
  name: "PassiveStub",
  template: `<div><slot /></div>`,
});

const ExportMenuStub = defineComponent({
  name: "ExportMenuStub",
  props: { model: { type: Array, default: () => [] } },
  setup(props) {
    return () => h("div", { "data-testid": "export-menu" },
      (props.model as Array<{ label?: string; command?: () => void }>).filter((item) => item.label).map((item) =>
        h("button", { onClick: item.command }, item.label),
      ),
    );
  },
});

const WorkflowToolbarStub = defineComponent({
  name: "WorkflowToolbar",
  setup(_props, { attrs }) {
    onUnmounted(() => {
      lifecycleCounts.toolbarUnmounts += 1;
    });
    return () => h("aside", { ...attrs, "data-testid": "workflow-toolbar" }, "ADD NODES");
  },
});

const WorkflowInspectorStub = defineComponent({
  name: "WorkflowInspector",
  props: {
    executionDisabled: { type: Boolean, default: false },
    executionDisabledReason: { type: String, default: "" },
  },
  emits: ["open-trial", "close"],
  setup(props, { attrs }) {
    onUnmounted(() => {
      lifecycleCounts.inspectorUnmounts += 1;
    });
    return () =>
      h(
        "aside",
        {
          ...attrs,
          "data-testid": "workflow-inspector",
          "data-execution-disabled": String(props.executionDisabled),
          "data-execution-disabled-reason": props.executionDisabledReason,
        },
        "Inspector",
      );
  },
});

const NodeDetailViewStub = defineComponent({
  name: "NodeDetailView",
  emits: ["close", "save"],
  template: `<main data-testid="node-detail-view"><button data-testid="close-detail" @click="$emit('close')">Close</button></main>`,
});

const WorkflowCanvasStub = defineComponent({
  name: "WorkflowCanvas",
  template: `<main data-testid="workflow-canvas">Canvas</main>`,
});

const WorkbookSheetTabsStub = defineComponent({
  name: "WorkbookSheetTabs",
  emits: ["open-template-picker"],
  template: `<nav data-testid="workbook-tabs"><button data-testid="tab-analysis-starter" @click="$emit('open-template-picker')">Analysis Starter</button></nav>`,
});

const TemplatePickerDialogStub = defineComponent({
  name: "TemplatePickerDialog",
  props: {
    visible: { type: Boolean, default: false },
    dataSelection: { type: Object, default: null },
    preferredTemplateSlug: { type: String, default: null },
  },
  emits: ["sheet-opened"],
  template: `<section data-testid="template-picker" :data-visible="String(visible)" :data-datasets="String(dataSelection?.datasets?.length ?? 0)" :data-preferred-template-slug="preferredTemplateSlug || ''"><button data-testid="sheet-opened" @click="$emit('sheet-opened')">opened</button>{{ dataSelection?.datasets?.[0]?.dataset_name ?? "" }}</section>`,
});

async function mountBuilder() {
  const { default: WorkflowBuilderContent } =
    await import("@/views/workflow-builder/WorkflowBuilderContent.vue");

  return mount(WorkflowBuilderContent, {
    global: {
      stubs: {
        Button: ButtonStub,
        Checkbox: PassiveStub,
        Menu: ExportMenuStub,
        TieredMenu: PassiveStub,
        OverlayPanel: PassiveStub,
        WorkbookSheetTabs: WorkbookSheetTabsStub,
        WorkflowToolbar: WorkflowToolbarStub,
        WorkflowCanvas: WorkflowCanvasStub,
        WorkflowInspector: WorkflowInspectorStub,
        NodeDetailView: NodeDetailViewStub,
        TemplatePickerDialog: TemplatePickerDialogStub,
      },
    },
  });
}

describe("WorkflowBuilderContent trial/detail layout", () => {
  beforeEach(() => {
    routeQuery.project_id = "1";
    delete routeQuery.fromDataSelection;
    delete routeQuery.selection;
    window.sessionStorage.clear();
    window.localStorage.clear();
    projectStore.currentProjectId = 1;
    workbookStore.projectId = 1;
    lifecycleCounts.toolbarUnmounts = 0;
    lifecycleCounts.inspectorUnmounts = 0;
    routeLeaveGuards.length = 0;
    workflowStore.workflowId = 101;
    workflowStore.workflowHash = null;
    workflowStore.hasUnsavedChanges = false;
    workflowStore.hasFoldValidationPlan = false;
    projectStore.error = null;
    projectStore.exportProject.mockClear();
    workflowStore.validateNodeParams.mockReturnValue([]);
    workbookStore.sheets = [
      {
        kind: "workflow",
        workflowId: 101,
        name: "PCA Sheet",
        purpose: "analysis",
        tabColor: null,
        sheetOrder: 0,
      },
      {
        kind: "trial",
        workflowId: -1,
        trialId: "trial-101-pca-1",
        sourceWorkflowId: 101,
        sourceNodeId: "pca_1",
        name: "Trial: PCA",
        purpose: "analysis",
        tabColor: null,
        sheetOrder: 1,
        trialData: { id: "pca_1", label: "PCA", type: "model.pca", params: { n_components: 3 } },
      },
    ];
    workbookStore.activeIndex = 1;
    vi.clearAllMocks();
  });

  it("exports a campaign-derived sheet only through the project archive that retains its fold plan", async () => {
    workbookStore.activeIndex = 0;
    workflowStore.hasFoldValidationPlan = true;
    const wrapper = await mountBuilder();
    await flushPromises();

    expect(wrapper.text()).toContain("cross-validation plan");
    const menu = wrapper.find('[data-testid="export-menu"]');
    expect(wrapper.text()).toContain("not a deployable campaign winner");
    expect(menu.text()).toContain("Project archive (.sherpa) — not a winner package");
    expect(menu.text()).not.toContain("Download Bundle (.zip)");
    expect(menu.text()).not.toContain("Jupyter Notebook");
    await menu.get("button").trigger("click");
    expect(projectStore.exportProject).toHaveBeenCalledWith(1);
    wrapper.unmount();
  });

  it("keeps standalone export formats for sheets without a fold plan", async () => {
    workbookStore.activeIndex = 0;
    const wrapper = await mountBuilder();
    await flushPromises();

    const menu = wrapper.find('[data-testid="export-menu"]');
    expect(menu.text()).toContain("Canonical Workflow Python (.py)");
    expect(menu.text()).toContain("Jupyter Notebook (.ipynb)");
    expect(menu.text()).toContain("Download Bundle (.zip)");
    expect(menu.text()).not.toContain("Project archive (.sherpa)");
    wrapper.unmount();
  });

  it("creates Peak Finding with only current catalog defaults", async () => {
    workbookStore.activeIndex = 0;
    workflowStore.getNodeMetadata.mockReturnValue({
      label: "Peak Finding",
      parameters: [
        { name: "distance", default: 10 },
        { name: "prominence", default: null },
        { name: "consensus_tolerance", default: 0 },
      ],
    } as never);
    const wrapper = await mountBuilder();
    wrapper.getComponent(WorkflowToolbarStub).vm.$emit("add-node", "analysis.peak_finding");
    await flushPromises();
    expect(workflowStore.addNode).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "analysis.peak_finding",
        params: { distance: 10, consensus_tolerance: 0 },
      }),
    );
    wrapper.unmount();
    workflowStore.getNodeMetadata.mockReturnValue({ label: "PCA" });
  });

  it("loads the selected project's workbook instead of retaining the previous canvas", async () => {
    workbookStore.projectId = 1;
    projectStore.currentProjectId = 1;
    const wrapper = await mountBuilder();
    await flushPromises();
    vi.clearAllMocks();

    projectStore.currentProjectId = 2;
    await flushPromises();

    expect(workflowStore.clearWorkflow).toHaveBeenCalledOnce();
    expect(workbookStore.loadSheets).toHaveBeenCalledWith(2);
    wrapper.unmount();
  });

  it("shows the exact My Dataset handoff without claiming that execution is already bound", async () => {
    routeQuery.fromDataSelection = "1";
    routeQuery.selection = "selection-test-1";
    window.sessionStorage.setItem(
      "spectra-my-dataset-workflow-selection-v3",
      JSON.stringify({
        schema_version: "spectra-my-dataset-workflow-selection/3",
        receipt_id: "selection-test-1",
        project_id: 1,
        datasets: [
          {
            experiment_id: 27,
            dataset_name: "Lavender Essential Oil FTIR Corpus v1",
            selection: "subset",
            selected_file_count: 3,
            file_ids: [101, 104, 107],
            file_paths: ["raw/ESL__B1.spa", "raw/ELF__B1.spa", "raw/ELS__B1.spa"],
            stage: "raw",
          },
        ],
        target_authority: {
          schema_version: "spectrasherpa-target-authority/1",
          column: "claimed_botanical_group",
          target_type: "categorical",
          units: null,
          source_digest: "a".repeat(64),
        },
        group: "block",
      }),
    );

    const wrapper = await mountBuilder();
    await flushPromises();

    const handoff = wrapper.get('[aria-label="My Dataset selection"]');
    expect(handoff.text()).toContain("3 selected files selected");
    expect(handoff.text()).toContain("waiting for Analysis Starter");
    expect(handoff.text()).toContain("block requested for grouping");
    expect(handoff.text()).not.toContain("will be offered");
    expect(wrapper.get('[aria-label="Workflow workspace context"]').text()).toContain(
      "Active DataPending: Lavender Essential Oil FTIR Corpus v1",
    );
    expect(
      wrapper.get('[data-testid="workflow-inspector"]').attributes("data-execution-disabled"),
    ).toBe("true");
    wrapper.unmount();
  });

  it("fails closed when an incoming selection receipt is missing or belongs to another tab", async () => {
    routeQuery.fromDataSelection = "1";
    routeQuery.selection = "selection-for-this-tab";
    window.sessionStorage.setItem(
      "spectra-my-dataset-workflow-selection-v3",
      JSON.stringify({
        schema_version: "spectra-my-dataset-workflow-selection/3",
        receipt_id: "selection-from-another-tab",
        project_id: 1,
        datasets: [
          {
            experiment_id: 44,
            dataset_name: "Stale selection",
            selection: "all",
            selected_file_count: 80,
            file_ids: null,
            file_paths: null,
            stage: "raw",
          },
        ],
        target_authority: null,
        group: null,
      }),
    );

    const wrapper = await mountBuilder();
    await flushPromises();

    expect(wrapper.get('[aria-label="My Dataset selection unavailable"]').text()).toContain(
      "missing, expired, or belongs to another browser tab",
    );
    expect(wrapper.get('[aria-label="Workflow workspace context"]').text()).toContain(
      "Active DataPending selection unavailable",
    );
    expect(
      wrapper.get('[data-testid="workflow-inspector"]').attributes("data-execution-disabled"),
    ).toBe("true");
    expect(
      wrapper
        .findAll("button")
        .find((button) => button.text() === "Run")
        ?.attributes(),
    ).toHaveProperty("disabled");
    expect(
      wrapper
        .findAll("button")
        .find((button) => button.text() === "Analysis Starter")
        ?.attributes(),
    ).toHaveProperty("disabled");
    wrapper.unmount();
  });

  it("opens each pending route against its own immutable dataset receipt", async () => {
    const selection = (receiptId: string, experimentId: number, datasetName: string) => ({
      schema_version: "spectra-my-dataset-workflow-selection/3" as const,
      receipt_id: receiptId,
      project_id: 1,
      datasets: [
        {
          experiment_id: experimentId,
          dataset_name: datasetName,
          selection: "all" as const,
          selected_file_count: 1,
          file_ids: null,
          file_paths: null,
          stage: "raw" as const,
        },
      ],
      target_authority: null,
      group: null,
    });
    storeDataSelectionReceipt(selection("receipt-wine", 11, "Wine"));
    storeDataSelectionReceipt(selection("receipt-uv", 12, "UV spectra"));
    routeQuery.fromDataSelection = "1";
    routeQuery.selection = "receipt-wine";

    const wineTab = await mountBuilder();
    await flushPromises();
    expect(wineTab.get('[aria-label="Workflow workspace context"]').text()).toContain(
      "Pending: Wine",
    );
    expect(wineTab.text()).not.toContain("Pending: UV spectra");
    wineTab.unmount();

    routeQuery.selection = "receipt-uv";
    const uvTab = await mountBuilder();
    await flushPromises();
    expect(uvTab.get('[aria-label="Workflow workspace context"]').text()).toContain(
      "Pending: UV spectra",
    );
    expect(uvTab.text()).not.toContain("Pending: Wine");
    uvTab.unmount();
  });

  it("resolves a pending receipt after a cold tab hydrates its routed project", async () => {
    routeQuery.fromDataSelection = "1";
    routeQuery.selection = "receipt-cold-tab";
    projectStore.currentProjectId = null;
    let finishHydration!: () => void;
    const hydration = new Promise<void>((resolve) => {
      finishHydration = resolve;
    });
    projectStore.selectProject.mockImplementationOnce(async (projectId: number) => {
      await hydration;
      projectStore.currentProjectId = projectId;
    });
    storeDataSelectionReceipt({
      schema_version: "spectra-my-dataset-workflow-selection/3",
      receipt_id: "receipt-cold-tab",
      project_id: 1,
      datasets: [
        {
          experiment_id: 11,
          dataset_name: "Wine",
          selection: "all",
          selected_file_count: 1,
          file_ids: null,
          file_paths: null,
          stage: "raw",
        },
      ],
      target_authority: null,
      group: null,
    });

    const wrapper = await mountBuilder();
    await flushPromises();

    expect(wrapper.find('[aria-label="Loading workflow"]').exists()).toBe(true);
    expect(wrapper.find('[aria-label="My Dataset selection unavailable"]').exists()).toBe(false);
    finishHydration();
    await flushPromises();

    expect(projectStore.selectProject).toHaveBeenCalledWith(1);
    expect(wrapper.find('[aria-label="Loading workflow"]').exists()).toBe(false);
    expect(wrapper.find('[aria-label="My Dataset selection unavailable"]').exists()).toBe(false);
    expect(wrapper.get('[aria-label="Workflow workspace context"]').text()).toContain(
      "Pending: Wine",
    );
    wrapper.unmount();
  });

  it("names the active sheet data source instead of repeating a stale project-derived identity", async () => {
    workbookStore.activeIndex = 0;
    const wrapper = await mountBuilder();
    await flushPromises();

    const context = wrapper.get('[aria-label="Workflow workspace context"]');
    expect(context.text()).not.toContain("ProjectIris PCA");
    expect(context.text()).toContain("Active DataSynthetic Atmospheric FTIR");
    expect(context.text()).not.toContain("1 dataset bound");
    expect(context.findAll(".workspace-context-item")[1]?.get("strong").attributes("title")).toBe(
      "Synthetic Atmospheric FTIR",
    );
    wrapper.unmount();
  });

  it("does not repeat the active sheet name or SHA beside the Workflows title", async () => {
    workbookStore.activeIndex = 0;
    workflowStore.workflowHash = "a".repeat(64);
    const wrapper = await mountBuilder();
    await flushPromises();

    expect(wrapper.get(".workspace-header__title h1").text()).toBe("Workflow");
    expect(wrapper.find(".workspace-header__title .workflow-meta-badge").exists()).toBe(false);
    wrapper.unmount();
  });

  it("carries the retained My Dataset selection into Analysis Starter opened from workbook tabs", async () => {
    workbookStore.activeIndex = 0;
    window.sessionStorage.setItem(
      "spectra-my-dataset-workflow-selection-v3",
      JSON.stringify({
        schema_version: "spectra-my-dataset-workflow-selection/3",
        receipt_id: "selection-test-2",
        project_id: 1,
        datasets: [
          {
            experiment_id: 44,
            dataset_name: "Eigenvector Corn M5",
            selection: "all",
            selected_file_count: 80,
            file_ids: null,
            file_paths: null,
            stage: "raw",
          },
        ],
        target_authority: null,
        group: null,
      }),
    );

    const wrapper = await mountBuilder();
    await flushPromises();

    expect(wrapper.find('[aria-label="My Dataset selection"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="template-picker"]').attributes("data-datasets")).toBe("0");

    await wrapper.get('[data-testid="tab-analysis-starter"]').trigger("click");
    await nextTick();

    const picker = wrapper.get('[data-testid="template-picker"]');
    expect(picker.attributes("data-visible")).toBe("true");
    expect(picker.attributes("data-datasets")).toBe("1");
    expect(picker.text()).toContain("Eigenvector Corn M5");
    wrapper.unmount();
  });

  it("auto-targets the Dashboard-selected starter after My Dataset handoff", async () => {
    routeQuery.fromDataSelection = "1";
    routeQuery.selection = "selection-test-3";
    workbookStore.activeIndex = 0;
    window.sessionStorage.setItem(
      "spectra-my-dataset-workflow-selection-v3",
      JSON.stringify({
        schema_version: "spectra-my-dataset-workflow-selection/3",
        receipt_id: "selection-test-3",
        project_id: 1,
        datasets: [
          {
            experiment_id: 44,
            dataset_name: "Lavender",
            selection: "subset",
            selected_file_count: 3,
            file_ids: [101, 102, 103],
            file_paths: ["raw/a.spa", "raw/b.spa", "raw/c.spa"],
            stage: "raw",
          },
        ],
        target_authority: null,
        group: null,
      }),
    );
    window.sessionStorage.setItem("sherpa:data-entry-mode", "analysis-starter");
    window.sessionStorage.setItem("sherpa:data-entry-project-id", "1");
    window.sessionStorage.setItem(
      "sherpa:data-entry-dataset-intent",
      JSON.stringify({
        schema_version: "spectra-analysis-starter-dataset-intent/1",
        project_id: 1,
        dataset_id: "builtin:lavender-essential-oil-v1",
        source: "builtin",
        name: "lavender-essential-oil-v1",
        label: "Lavender",
        template_slug: "pca",
      }),
    );

    const wrapper = await mountBuilder();
    await flushPromises();

    const picker = wrapper.get('[data-testid="template-picker"]');
    expect(picker.attributes("data-visible")).toBe("true");
    expect(picker.attributes("data-preferred-template-slug")).toBe("pca");

    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    projectStore.fetchProject.mockRejectedValueOnce(new Error("summary temporarily unavailable"));
    await wrapper.get('[data-testid="sheet-opened"]').trigger("click");
    await flushPromises();

    expect(projectStore.fetchProject).toHaveBeenCalledWith(1);
    expect(warn).toHaveBeenCalledWith(
      "Failed to refresh project summary after opening workflow sheet",
    );
    expect(window.sessionStorage.getItem("sherpa:data-entry-mode")).toBeNull();
    expect(routeQuery.fromDataSelection).toBeUndefined();
    expect(routeQuery.selection).toBeUndefined();
    expect(wrapper.find('[aria-label="My Dataset selection"]').exists()).toBe(false);
    expect(sessionStorage.getItem(dataSelectionReceiptStorageKey("selection-test-3"))).toBeNull();
    warn.mockRestore();
    wrapper.unmount();
  });

  it("keeps Blank Analysis from reopening the starter picker after data selection", async () => {
    routeQuery.fromDataSelection = "1";
    routeQuery.selection = "selection-test-4";
    workbookStore.activeIndex = 0;
    window.sessionStorage.setItem(
      "spectra-my-dataset-workflow-selection-v3",
      JSON.stringify({
        schema_version: "spectra-my-dataset-workflow-selection/3",
        receipt_id: "selection-test-4",
        project_id: 1,
        datasets: [
          {
            experiment_id: 44,
            dataset_name: "Lavender",
            selection: "all",
            selected_file_count: 33,
            file_ids: null,
            file_paths: null,
            stage: "raw",
          },
        ],
        target_authority: null,
        group: null,
      }),
    );
    window.sessionStorage.setItem("sherpa:data-entry-mode", "analysis-starter");
    window.sessionStorage.setItem("sherpa:data-entry-project-id", "1");
    window.sessionStorage.setItem(
      "sherpa:data-entry-dataset-intent",
      JSON.stringify({
        schema_version: "spectra-analysis-starter-dataset-intent/1",
        project_id: 1,
        dataset_id: "builtin:lavender-essential-oil-v1",
        source: "builtin",
        name: "lavender-essential-oil-v1",
        label: "Lavender",
        template_slug: null,
      }),
    );

    const wrapper = await mountBuilder();
    await flushPromises();

    const picker = wrapper.get('[data-testid="template-picker"]');
    expect(picker.attributes("data-visible")).toBe("false");
    expect(wrapper.find('[aria-label="My Dataset selection"]').exists()).toBe(true);
    expect(window.sessionStorage.getItem("sherpa:data-entry-mode")).toBeNull();
    wrapper.unmount();
  });

  it("removes the retired v1 My Dataset handoff state", async () => {
    window.sessionStorage.setItem(
      "spectra-my-dataset-workflow-selection-v1",
      JSON.stringify({ stale: true }),
    );

    const wrapper = await mountBuilder();
    await nextTick();

    expect(window.sessionStorage.getItem("spectra-my-dataset-workflow-selection-v1")).toBeNull();
    wrapper.unmount();
  });

  it("shows only the detail panel on a trial sheet while preserving ADD NODES state", async () => {
    const wrapper = await mountBuilder();
    await nextTick();

    const toolbar = wrapper.get('[data-testid="workflow-toolbar"]');
    const inspector = wrapper.get('[data-testid="workflow-inspector"]');

    expect(wrapper.get('[data-testid="node-detail-view"]').isVisible()).toBe(true);
    expect(wrapper.find('[data-testid="workflow-canvas"]').exists()).toBe(false);
    expect(toolbar.exists()).toBe(true);
    expect(toolbar.classes()).toContain("trial-hidden");
    expect(inspector.exists()).toBe(true);
    expect(inspector.classes()).toContain("trial-hidden");

    await wrapper.get('[data-testid="close-detail"]').trigger("click");
    await nextTick();

    expect(wrapper.find('[data-testid="node-detail-view"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="workflow-canvas"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="workflow-toolbar"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="workflow-toolbar"]').classes()).not.toContain("trial-hidden");
    expect(wrapper.get('[data-testid="workflow-inspector"]').classes()).not.toContain(
      "trial-hidden",
    );
    expect(lifecycleCounts.toolbarUnmounts).toBe(0);
    expect(lifecycleCounts.inspectorUnmounts).toBe(0);
  });

  it("keeps a managed-candidate authority inspectable but disables ordinary execution", async () => {
    workbookStore.sheets = [
      {
        kind: "workflow",
        workflowId: 202,
        name: "Harness candidate authority",
        purpose: "managed_candidate_authority",
        tabColor: null,
        sheetOrder: 0,
      },
    ];
    workbookStore.activeIndex = 0;

    const wrapper = await mountBuilder();
    await nextTick();

    expect(wrapper.get('[data-action="run_workflow"]').attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("Harness authority");
    expect(wrapper.get('[data-testid="workflow-canvas"]').isVisible()).toBe(true);
    expect(
      wrapper.get('[data-testid="workflow-inspector"]').attributes("data-execution-disabled"),
    ).toBe("true");
    expect(
      wrapper
        .get('[data-testid="workflow-inspector"]')
        .attributes("data-execution-disabled-reason"),
    ).toContain("only the governed Harness may execute it");
  });

  it("flushes a pending autosave before route navigation without prompting", async () => {
    workbookStore.activeIndex = 0;
    workflowStore.saveWorkflow.mockImplementationOnce(async () => {
      workflowStore.hasUnsavedChanges = false;
      return 101;
    });
    const confirm = vi.fn(() => false);
    Object.defineProperty(window, "confirm", { configurable: true, value: confirm });
    const wrapper = await mountBuilder();
    await flushPromises();

    workflowStore.hasUnsavedChanges = true;
    const guard = routeLeaveGuards.at(-1);
    expect(guard).toBeDefined();
    const allowed = await guard?.();

    expect(allowed).toBe(true);
    expect(workflowStore.saveWorkflow).toHaveBeenCalledWith({
      createVersion: false,
      projectId: 1,
    });
    expect(confirm).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("prompts only after the route-time autosave genuinely fails", async () => {
    workbookStore.activeIndex = 0;
    workflowStore.saveWorkflow.mockRejectedValueOnce(new Error("network unavailable"));
    const confirm = vi.fn(() => false);
    Object.defineProperty(window, "confirm", { configurable: true, value: confirm });
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const wrapper = await mountBuilder();
    await flushPromises();

    workflowStore.hasUnsavedChanges = true;
    const guard = routeLeaveGuards.at(-1);
    expect(guard).toBeDefined();
    const allowed = await guard?.();

    expect(allowed).toBe(false);
    expect(confirm).toHaveBeenCalledWith(
      "Autosave failed. Your edits are preserved in this browser but are not saved to the server. Leave this page?",
    );
    expect(wrapper.text()).toContain("Save failed");
    consoleError.mockRestore();
    wrapper.unmount();
  });

  it("keeps an invalid workflow as a local draft without attempting autosave", async () => {
    workbookStore.activeIndex = 0;
    workflowStore.validateNodeParams.mockReturnValue([
      {
        param_name: "maximum",
        message: "Maximum Feature Coordinate must be greater than Minimum Feature Coordinate",
      },
    ]);
    const confirm = vi.fn(() => false);
    Object.defineProperty(window, "confirm", { configurable: true, value: confirm });
    const wrapper = await mountBuilder();
    await flushPromises();

    workflowStore.hasUnsavedChanges = true;
    const guard = routeLeaveGuards.at(-1);
    const allowed = await guard?.();

    expect(allowed).toBe(true);
    expect(workflowStore.saveWorkflow).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("keeps current execution badges when an obsolete draft matches the saved graph", async () => {
    workbookStore.activeIndex = 0;
    const key = "spectra_sherpa_workflow_draft_v1:1:1:101";
    localStorage.setItem(
      key,
      JSON.stringify({
        projectId: 1,
        workflowId: 101,
        workflowName: workflowStore.workflowName,
        workflowDescription: "",
        nodes: workflowStore.nodes.map((node) => ({
          ...node,
          executionState: { status: "error" },
        })),
        edges: workflowStore.edges,
      }),
    );
    const wrapper = await mountBuilder();
    await flushPromises();
    expect(localStorage.getItem(key)).toBeNull();
    expect(workflowStore.setNodes).not.toHaveBeenCalled();
    expect(workflowStore.markWorkflowStale).not.toHaveBeenCalled();
    expect(workflowStore.hasUnsavedChanges).toBe(false);
    wrapper.unmount();
  });
});
