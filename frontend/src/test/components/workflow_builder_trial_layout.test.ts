import { mount } from "@vue/test-utils";
import { defineComponent, h, nextTick, onUnmounted, reactive } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  hasUnsavedChanges: false,
  isWorkflowStale: false,
  setNodes: vi.fn((nodes) => {
    workflowStore.nodes = nodes;
  }),
  setEdges: vi.fn((edges) => {
    workflowStore.edges = edges;
  }),
  saveWorkflow: vi.fn(),
  loadWorkflow: vi.fn(),
  updateNode: vi.fn(),
  getNodeMetadata: vi.fn(() => ({ label: "PCA" })),
  executeWorkflow: vi.fn(),
  exportToPython: vi.fn(),
  exportToNotebook: vi.fn(),
  downloadZipBundle: vi.fn(),
});

const workflowBuilderConfigStore = {
  autoExecute: { __v_isRef: true, value: false },
};

vi.mock("vue-router", () => ({
  useRoute: () => ({ query: { project_id: "1" } }),
  useRouter: () => ({ push: vi.fn() }),
  onBeforeRouteLeave: vi.fn(),
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
  useProjectStore: () => ({
    currentProjectId: 1,
    projects: [{ id: 1 }],
    recentProjects: [{ id: 1 }],
    getLastActiveProjectId: vi.fn(() => 1),
    fetchProjects: vi.fn(),
    createProject: vi.fn(),
    selectProject: vi.fn(),
  }),
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
  emits: ["open-trial", "close"],
  setup(_props, { attrs }) {
    onUnmounted(() => {
      lifecycleCounts.inspectorUnmounts += 1;
    });
    return () => h("aside", { ...attrs, "data-testid": "workflow-inspector" }, "Inspector");
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
  template: `<nav data-testid="workbook-tabs">Tabs</nav>`,
});

async function mountBuilder() {
  const { default: WorkflowBuilderContent } = await import(
    "@/views/workflow-builder/WorkflowBuilderContent.vue"
  );

  return mount(WorkflowBuilderContent, {
    global: {
      stubs: {
        Button: ButtonStub,
        Checkbox: PassiveStub,
        Menu: PassiveStub,
        TieredMenu: PassiveStub,
        OverlayPanel: PassiveStub,
        WorkbookSheetTabs: WorkbookSheetTabsStub,
        WorkflowToolbar: WorkflowToolbarStub,
        WorkflowCanvas: WorkflowCanvasStub,
        WorkflowInspector: WorkflowInspectorStub,
        NodeDetailView: NodeDetailViewStub,
      },
    },
  });
}

describe("WorkflowBuilderContent trial/detail layout", () => {
  beforeEach(() => {
    lifecycleCounts.toolbarUnmounts = 0;
    lifecycleCounts.inspectorUnmounts = 0;
    workbookStore.sheets = [
      {
        kind: "workflow",
        workflowId: 101,
        name: "PCA Sheet",
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
        tabColor: null,
        sheetOrder: 1,
        trialData: { id: "pca_1", label: "PCA", type: "model.pca", params: { n_components: 3 } },
      },
    ];
    workbookStore.activeIndex = 1;
    vi.clearAllMocks();
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
    expect(wrapper.get('[data-testid="workflow-inspector"]').classes()).not.toContain("trial-hidden");
    expect(lifecycleCounts.toolbarUnmounts).toBe(0);
    expect(lifecycleCounts.inspectorUnmounts).toBe(0);
  });
});
