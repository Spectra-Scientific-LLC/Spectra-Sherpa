/* eslint-disable vue/one-component-per-file */
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, reactive } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/api/client";
import type { ReferenceDatasetOption } from "@/stores/workflow-types";
import DataContent from "@/views/data/DataContent.vue";
import { retainedDatasetWorkspace } from "@/utils/retainedInspection";
import {
  dataSelectionReceiptStorageKey,
  type DataSelectionReceipt,
} from "@/utils/workflowDataSelection";

const mocks = vi.hoisted(() => ({
  pro: false,
  route: { query: {} as Record<string, string> },
  routerPush: vi.fn(),
  routerReplace: vi.fn(),
  toastAdd: vi.fn(),
  dataStore: {
    availableDatasets: { experiments: [], library: [], builder: [] },
    catalogLoading: false,
    catalogError: null as string | null,
    experimentsError: null as string | null,
    experiments: [
      {
        id: 11,
        name: "Wine",
        description: "Wine reference dataset",
        file_count: 1,
        created_at: "2026-05-01T00:00:00Z",
      },
    ],
    experimentsLoading: false,
    activeExperimentId: 11 as number | null,
    experimentFiles: [
      {
        id: 22,
        experiment_id: 11,
        file_path: "raw/wine.csv",
        file_size_bytes: 2048,
        stage: "raw",
        created_at: "2026-05-02T00:00:00Z",
      },
    ],
    experimentFilesLoading: false,
    experimentFilesRefusal: null as { code: string | null; message: string } | null,
    activeFileId: null as number | null,
    activeFilePath: null as string | null,
    fileInfo: null as Record<string, unknown> | null,
    fileInfoLoading: false,
    fileInfoError: null as string | null,
    referenceCatalog: {
      builtin: [],
      registered: [],
      synthetic: [],
      eigenvector: [],
      oes: [],
      sklearn: [],
    },
    referenceCatalogLoading: false,
    referenceCatalogError: null as string | null,
    catalogDatasetInfo: null,
    catalogDatasetLoading: false,
    catalogDatasetError: null,
    dataStoryText: null,
    dataStoryMemoryScopes: [],
    dataStoryLoading: false,
    dataStoryContext: "",
    experimentDatasets: [],
    libraryDatasets: [],
    fetchCatalog: vi.fn().mockResolvedValue(undefined),
    fetchExperiments: vi.fn().mockResolvedValue(undefined),
    fetchReferenceCatalog: vi.fn().mockResolvedValue(undefined),
    restoreActiveExperimentForCurrentProject: vi.fn().mockResolvedValue(undefined),
    clearActiveExperimentSelection: vi.fn(),
    selectExperiment: vi.fn().mockResolvedValue(undefined),
    clearCatalogExploration: vi.fn(),
    clearInspection: vi.fn(),
    fetchFileAssets: vi.fn().mockResolvedValue({
      format_id: "csv",
      variant: "headered-matrix",
      parser_id: "spectrasherpa.csv",
      parser_version: "1",
      source_sha256: "a".repeat(64),
      assets: [{ asset_id: "data", title: "Data", shape: [178, 13], warnings: [] }],
    }),
    inspectFile: vi.fn().mockImplementation(async (fileId: number, filePath: string) => {
      mocks.dataStore.activeFileId = fileId;
      mocks.dataStore.activeFilePath = filePath;
      mocks.dataStore.fileInfo = { label: "Wine", n_samples: 178, n_features: 13 };
      return mocks.dataStore.fileInfo;
    }),
    activateFile: vi.fn().mockImplementation((fileId: number, filePath: string) => {
      mocks.dataStore.activeFileId = fileId;
      mocks.dataStore.activeFilePath = filePath;
    }),
    inspectExperimentRawFiles: vi.fn().mockImplementation(async (experimentId: number) => {
      mocks.dataStore.activeFileId = null;
      mocks.dataStore.activeFilePath = null;
      mocks.dataStore.fileInfo = {
        label: "Wine",
        n_samples: 178,
        n_features: 13,
        metadata: { contents_file_count: 1, contents_title: `Dataset ${experimentId}` },
      };
      return mocks.dataStore.fileInfo;
    }),
    downloadFile: vi.fn(),
    deleteFile: vi.fn(),
    deleteExperiment: vi.fn(),
    createExperiment: vi.fn(),
    uploadFile: vi.fn(),
    stageUploadFile: vi.fn(),
    stageUploadBatch: vi.fn(),
    deleteStagedUpload: vi.fn(),
    commitStagedUploads: vi.fn(),
    importReferenceDatasets: vi.fn(),
    importRegisteredReference: vi.fn(),
    importLibraryDatasets: vi.fn(),
    fetchDataMatrix: vi.fn(),
    exploreCatalogDataset: vi.fn(),
    generateDataStory: vi.fn(),
  },
  projectStore: {
    currentProjectId: 3 as number | null,
    currentProject: {
      id: 3,
      name: "Wine Project",
      experiment_count: 1,
      workflow_count: 0,
      experiments: [],
      workflows: [],
    },
    ensureProjectForBrowserTab: vi.fn().mockResolvedValue(undefined),
    fetchProjects: vi.fn().mockResolvedValue(undefined),
    fetchProject: vi.fn().mockResolvedValue(undefined),
  },
  authStore: {
    user: { id: 7 },
  },
  advisorStore: {
    switchScope: vi.fn().mockResolvedValue(undefined),
  },
  sherpaStore: {},
  workflowStore: {
    fetchCompatibilityMatrix: vi.fn().mockResolvedValue(undefined),
    compatibleAnalysisCount: vi.fn().mockReturnValue(0),
  },
  provenanceStore: {
    refresh: vi.fn().mockResolvedValue(undefined),
  },
  disabledCapabilities: new Set<string>(),
}));

vi.mock("vue-router", () => ({
  useRoute: () => mocks.route,
  useRouter: () => ({
    push: mocks.routerPush,
    replace: mocks.routerReplace.mockImplementation(async ({ query }) => {
      mocks.route.query = query;
    }),
  }),
}));

vi.mock("primevue/usetoast", () => ({
  useToast: () => ({ add: mocks.toastAdd }),
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appMode: { value: mocks.pro ? "enterprise" : "local" },
    siteProfile: { value: mocks.pro ? "pro" : "local" },
    isFeatureEnabled: () => true,
    isCapabilityDisabled: (capability: string) => mocks.disabledCapabilities.has(capability),
  }),
}));

vi.mock("@/stores/data", () => ({
  useDataStore: () => mocks.dataStore,
}));

// Make the project store reactive so the component's
// `watch(() => projectStore.currentProjectId, ...)` actually fires when a
// test mutates currentProjectId (a plain object would never trigger it).
mocks.projectStore = reactive(mocks.projectStore);

vi.mock("@/stores/project", () => ({
  useProjectStore: () => mocks.projectStore,
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => mocks.authStore,
}));

vi.mock("@/stores/advisor", () => ({
  useAdvisorStore: () => mocks.advisorStore,
}));

vi.mock("@/stores/sherpa", () => ({
  useSherpaStore: () => mocks.sherpaStore,
}));

vi.mock("@/stores/workflow", () => ({
  useWorkflowStore: () => mocks.workflowStore,
}));

vi.mock("@/stores/projectProvenance", () => ({
  useProjectProvenanceStore: () => mocks.provenanceStore,
}));

vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("@/components/MemoryAttribution.vue", () => ({
  default: defineComponent({ name: "MemoryAttribution", template: "<div />" }),
}));

vi.mock("@/components/PlotlyChart.vue", () => ({
  default: defineComponent({ name: "PlotlyChart", template: "<div />" }),
}));

vi.mock("@/views/data/DataQualityPanel.vue", () => ({
  default: defineComponent({ name: "DataQualityPanel", template: "<div />" }),
}));

vi.mock("@/views/data/DataContentsPanel.vue", () => ({
  default: defineComponent({
    name: "DataContentsPanel",
    props: {
      initialAnalysisTarget: { type: String, default: "" },
      initialAnalysisGroup: { type: String, default: "" },
      analysisSelectionHydrated: { type: Boolean, default: false },
      analysisSelectionStatus: { type: String, default: "loading" },
    },
    emits: ["analysisChoice", "analysisSelectionCommit"],
    template: "<div />",
  }),
}));

vi.mock("@/views/data/SelectedSpectraPlotPanel.vue", () => ({
  default: defineComponent({
    name: "SelectedSpectraPlotPanel",
    props: {
      plotDatasets: { type: Array, default: () => [] },
      plotDatasetCount: { type: Number, default: 0 },
      plotFileCount: { type: Number, default: 0 },
      plotDatasetsLoading: Boolean,
      plotDatasetsError: { type: String, default: null },
      activeExperimentId: { type: Number, default: null },
      activeFileName: { type: String, default: null },
    },
    template:
      "<div data-testid='contents-panel' :data-plot-count='plotDatasetCount' :data-plot-sources='plotDatasets.length' />",
  }),
}));

vi.mock("@/views/data/CollectionDefinitionPanel.vue", () => ({
  default: defineComponent({
    name: "CollectionDefinitionPanel",
    props: { experimentId: Number, refreshKey: String },
    template:
      "<div data-testid='collection-definition-panel' :data-experiment-id='experimentId' :data-refresh-key='refreshKey' />",
  }),
}));

vi.mock("@/views/data/SynthesisPanel.vue", () => ({
  default: defineComponent({ name: "SynthesisPanel", template: "<div />" }),
}));

const TabViewStub = defineComponent({
  name: "TabView",
  props: {
    activeIndex: { type: Number, default: 0 },
  },
  template: `<div data-testid="data-tabs" :data-active-index="String(activeIndex)"><slot /></div>`,
});

const TabPanelStub = defineComponent({
  name: "TabPanel",
  props: {
    header: { type: String, default: "" },
  },
  template: `<section><slot name="header" /><slot /></section>`,
});

const ButtonStub = defineComponent({
  name: "PrimeButtonStub",
  props: {
    label: { type: String, default: "" },
    icon: { type: String, default: "" },
    title: { type: String, default: "" },
    disabled: Boolean,
    loading: Boolean,
  },
  emits: ["click"],
  template: `
    <button type="button" :title="title" :disabled="disabled" @click="$emit('click', $event)">
      <span v-if="icon" :class="icon" />
      {{ label }}
      <slot />
    </button>
  `,
});

const InputNumberStub = defineComponent({
  name: "InputNumberStub",
  inheritAttrs: false,
  props: {
    inputId: { type: String, default: "" },
    modelValue: { type: [Number, String], default: null },
  },
  emits: ["update:modelValue"],
  template: `
    <input
      type="number"
      :id="inputId"
      :value="modelValue"
      @input="$emit('update:modelValue', Number($event.target.value))"
    />
  `,
});

const PassiveStub = defineComponent({
  name: "PassiveStub",
  template: "<div><slot name='header' /><slot /></div>",
});

const TagStub = defineComponent({
  name: "TagStub",
  props: {
    value: { type: [String, Number], default: "" },
    severity: { type: String, default: "" },
  },
  template: "<span class='tag-stub' :data-severity='severity'>{{ value }}<slot /></span>",
});

const RenderedDataTableStub = defineComponent({
  name: "RenderedDataTableStub",
  inheritAttrs: false,
  template: `<div class="rendered-data-table"><slot /></div>`,
});

const RenderedColumnStub = defineComponent({
  name: "RenderedColumnStub",
  props: {
    header: { type: String, default: "" },
  },
  setup() {
    const row = {
      id: 101,
      key: "nist:101",
      compound_name: "Acetone",
      formula: "",
      cas_number: "67-64-1",
      resolution: "low",
      source_label: "NIST",
      file_path: "nist_library/acetone.jdx",
    };
    return { row };
  },
  template: `
    <div class="rendered-column" :data-header="header">
      <span class="column-header">{{ header }}</span>
      <slot name="body" :data="row" />
    </div>
  `,
});

function mountDataContent() {
  return mount(DataContent, {
    global: {
      stubs: {
        TabView: TabViewStub,
        TabPanel: TabPanelStub,
        Button: ButtonStub,
        Checkbox: PassiveStub,
        DataTable: PassiveStub,
        Column: PassiveStub,
        Dialog: PassiveStub,
        InputText: PassiveStub,
        InputNumber: InputNumberStub,
        Textarea: PassiveStub,
        Dropdown: PassiveStub,
        Menu: PassiveStub,
        Panel: PassiveStub,
        ProgressSpinner: PassiveStub,
        Tag: TagStub,
        InputSwitch: PassiveStub,
        MultiWellAcquisitionPanel: PassiveStub,
      },
    },
  });
}

function mountDataContentWithRenderedColumns() {
  return mount(DataContent, {
    global: {
      stubs: {
        TabView: TabViewStub,
        TabPanel: TabPanelStub,
        Button: ButtonStub,
        Checkbox: PassiveStub,
        DataTable: RenderedDataTableStub,
        Column: RenderedColumnStub,
        Dialog: PassiveStub,
        InputText: PassiveStub,
        InputNumber: InputNumberStub,
        Textarea: PassiveStub,
        Dropdown: PassiveStub,
        Menu: PassiveStub,
        Panel: PassiveStub,
        ProgressSpinner: PassiveStub,
        Tag: TagStub,
        InputSwitch: PassiveStub,
        MultiWellAcquisitionPanel: PassiveStub,
      },
    },
  });
}

function latestWorkflowReceipt(): DataSelectionReceipt | null {
  const navigation = mocks.routerPush.mock.calls.findLast(
    ([location]) => location?.path === "/workflow" && location?.query?.selection,
  )?.[0];
  const receiptId = navigation?.query?.selection;
  if (typeof receiptId !== "string") return null;
  return JSON.parse(
    sessionStorage.getItem(dataSelectionReceiptStorageKey(receiptId)) || "null",
  ) as DataSelectionReceipt | null;
}

function storedWorkflowReceiptCount(): number {
  return Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index)).filter(
    (key) => key?.startsWith("spectra-my-dataset-workflow-selection-v3:") && !key.endsWith(":index"),
  ).length;
}

type DataContentVm = {
  selectedRefDatasets: Set<string>;
  previewRefKey: string | null;
  registeredCollapsed: boolean;
  legacyCollapsed: boolean;
  refOverrides: Record<string, Record<string, unknown>>;
  importDatasetName: string;
  selectedLibraryKeys: Set<string>;
  selectedLibraryRows: Record<string, Record<string, unknown>>;
  libraryDatasetName: string;
  librarySearch: string;
  librarySource: string;
  libraryRangeMode: string;
  libraryResolutionCm1: number;
  libraryWavenumberMin: number;
  libraryWavenumberMax: number;
  libraryTemperatureK: number;
  libraryPressureAtm: number;
  hitranLibraryRows: Array<Record<string, unknown>>;
  librarySpectra: Record<string, Record<string, unknown>>;
  selectedFile: File | null;
  stagedUploadMembers: Array<{ staging_id: string; filename: string; size_bytes: number }>;
  uploadOverrides: Record<string, Record<string, unknown>>;
  previewUploadId: string | null;
  uploadDatasetName: string;
  uploadStage: string;
  uploadDataRole: string;
  uploadTargetColumn: string;
  uploadTargetType: string;
  onImportSelectedDatasets: () => Promise<void>;
  toggleRefDataset: (dataset: ReferenceDatasetOption) => void;
  selectRegisteredReferenceFile: (dataset: Record<string, unknown>) => void;
  onRegisteredReferenceSelection: (event: Event) => Promise<void>;
  onImportSelectedLibraryDatasets: () => Promise<void>;
  onAddAllVisibleNistToBasket: () => void;
  librarySpectrumParams: (entry: Record<string, unknown>) => Record<string, string | number>;
  persistDataDraftNow: () => void;
  onUploadFile: () => Promise<void>;
  onFileSelect: (event: { files?: File[] }) => Promise<void>;
  onInspectFile: (
    file: Record<string, unknown>,
    options?: { updateRoute?: boolean },
  ) => Promise<void>;
  inspectionAssets: Array<{
    asset_id: string;
    title: string;
    shape: number[];
    warnings?: string[];
  }>;
  inspectionAssetId: string | null;
  pendingInspection:
    | { kind: "file"; experimentId: number; file: Record<string, unknown> }
    | { kind: "experiment"; experimentId: number }
    | null;
  onInspectionAssetChange: () => Promise<void>;
  onCollectionDefinitionChanged: (receipt: {
    experiment_id: number;
    status: "attached" | "absent";
    message: string;
  }) => Promise<void>;
  onExperimentSelect: (
    experiment: Record<string, unknown>,
    options?: { preserveComparisons?: boolean },
  ) => Promise<void>;
  onAcquisitionExperimentSelect: (experimentId: number) => Promise<void>;
  onPlotAllExperiments: (checked: boolean) => Promise<void>;
  onPlotExperimentToggle: (experiment: Record<string, unknown>, checked: boolean) => Promise<void>;
  onPlotFileToggle: (file: Record<string, unknown>, checked: boolean) => Promise<void>;
  useOnlyDataView: (file: Record<string, unknown>) => Promise<void>;
  goToWorkflow: () => void;
  applyWorkflowDataSelection: () => Promise<void>;
  isExperimentPartlyPlotted: (experimentId: number) => boolean;
  plottedExperimentIds: number[];
  plotDatasetSources: Array<{
    experimentId: number;
    name: string;
    members: Array<{ fileName: string }>;
  }>;
  plotFileSelections: Record<number, unknown>;
};

describe("DataContent file inspection", () => {
  beforeEach(() => {
    mocks.pro = false;
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    retainedDatasetWorkspace(mocks.dataStore, "7:3").clear();
    mocks.route.query = {};
    mocks.projectStore.currentProjectId = 3;
    mocks.dataStore.catalogError = null;
    mocks.dataStore.experimentsError = null;
    mocks.dataStore.experiments = [
      {
        id: 11,
        name: "Wine",
        description: "Wine reference dataset",
        file_count: 1,
        created_at: "2026-05-01T00:00:00Z",
      },
    ];
    mocks.dataStore.experimentFiles = [
      {
        id: 22,
        experiment_id: 11,
        file_path: "raw/wine.csv",
        file_size_bytes: 2048,
        stage: "raw",
        created_at: "2026-05-02T00:00:00Z",
      },
    ];
    mocks.dataStore.activeExperimentId = 11;
    mocks.dataStore.experimentFilesRefusal = null;
    mocks.dataStore.activeFileId = null;
    mocks.dataStore.activeFilePath = null;
    mocks.dataStore.fileInfo = null;
    mocks.dataStore.selectExperiment.mockResolvedValue(undefined);
    mocks.dataStore.fetchFileAssets.mockResolvedValue({
      format_id: "csv",
      variant: "headered-matrix",
      parser_id: "spectrasherpa.csv",
      parser_version: "1",
      source_sha256: "a".repeat(64),
      assets: [{ asset_id: "data", title: "Data", shape: [178, 13], warnings: [] }],
    });
    mocks.dataStore.inspectFile.mockImplementation(async (fileId: number, filePath: string) => {
      mocks.dataStore.activeFileId = fileId;
      mocks.dataStore.activeFilePath = filePath;
      mocks.dataStore.fileInfo = { label: "Wine", n_samples: 178, n_features: 13 };
      return mocks.dataStore.fileInfo;
    });
    mocks.dataStore.inspectExperimentRawFiles.mockImplementation(async (experimentId: number) => {
      mocks.dataStore.activeFileId = null;
      mocks.dataStore.activeFilePath = null;
      mocks.dataStore.fileInfo = {
        label: "Wine",
        n_samples: 178,
        n_features: 13,
        metadata: { contents_file_count: 1, contents_title: `Dataset ${experimentId}` },
      };
      return mocks.dataStore.fileInfo;
    });
    mocks.dataStore.referenceCatalog = {
      builtin: [],
      registered: [],
      synthetic: [],
      eigenvector: [],
      oes: [],
      sklearn: [],
    };
    mocks.dataStore.libraryDatasets = [
      {
        id: 101,
        compound_name: "Acetone",
        cas_number: "67-64-1",
        resolution: "low",
        file_path: "nist_library/acetone.jdx",
      },
      {
        id: 102,
        compound_name: "Ethanol",
        cas_number: "64-17-5",
        resolution: "low",
        file_path: "nist_library/ethanol.jdx",
      },
    ];
    mocks.dataStore.createExperiment.mockResolvedValue({ id: 33, name: "Created Dataset" });
    mocks.dataStore.uploadFile.mockResolvedValue(undefined);
    mocks.dataStore.stageUploadBatch.mockResolvedValue({
      file_count: 1,
      total_size_bytes: 12,
      refused_count: 0,
      refusals: [],
      files: [
        {
          staging_id: "abc123",
          filename: "features.csv",
          size_bytes: 12,
          format_id: "csv",
          variant: "headered-matrix",
          assets: [],
        },
      ],
    });
    mocks.dataStore.commitStagedUploads.mockResolvedValue({ imported: 1, files: [44] });
    mocks.dataStore.importReferenceDatasets.mockResolvedValue({ imported: 1 });
    mocks.dataStore.importLibraryDatasets.mockResolvedValue({ imported: 1, files: [55] });
    mocks.dataStore.fetchDataMatrix.mockResolvedValue(null);
    mocks.dataStore.fileInfoError = null;
    mocks.disabledCapabilities.clear();
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
  });

  it("explains a missing Pro project before requesting upload access", async () => {
    mocks.pro = true;
    mocks.projectStore.currentProjectId = null;
    const wrapper = mountDataContent();
    await flushPromises();
    expect(wrapper.get(".upload-disabled-notice").text()).toContain("Select or create a project");
    expect(wrapper.findAll("button").find(b => b.text() === "Choose sources")!.attributes("disabled")).toBeDefined();
    expect(vi.mocked(api.get).mock.calls.some(([path]) => String(path).endsWith("/availability"))).toBe(false);
    wrapper.unmount();
  });

  it("shows loading, explains a failed check, and enables Pro upload after Retry", async () => {
    mocks.pro = true;
    let rejectAccess!: (reason: Error) => void;
    const pending = new Promise<never>((_resolve, reject) => { rejectAccess = reject; });
    vi.mocked(api.get).mockImplementation(path => String(path).endsWith("/availability")
      ? pending : Promise.resolve({ data: {} }));
    const wrapper = mountDataContent();
    await flushPromises();
    expect(wrapper.get(".upload-disabled-notice").text()).toContain("Checking project access");
    expect(wrapper.findAll("button").find(b => b.text() === "Choose sources")!.attributes("disabled")).toBeDefined();
    rejectAccess(new Error("Network interrupted"));
    await flushPromises();
    expect(wrapper.get(".upload-disabled-notice").attributes("role")).toBe("alert");
    expect(wrapper.get(".upload-disabled-notice").text()).toContain("Could not check project access");
    vi.mocked(api.get).mockResolvedValue({ data: { read: true, write: true } });
    await wrapper.findAll("button").find(b => b.text() === "Retry access check")!.trigger("click");
    await flushPromises();
    expect(wrapper.find(".upload-disabled-notice").exists()).toBe(false);
    expect(wrapper.findAll("button").find(b => b.text() === "Choose sources")!.attributes("disabled")).toBeUndefined();
    expect(api.get).toHaveBeenLastCalledWith("/commercial/projects/3/availability");
    wrapper.unmount();
  });

  it("explains read-only Pro access without presenting it as a network failure", async () => {
    mocks.pro = true;
    vi.mocked(api.get).mockResolvedValue({ data: { read: true, write: false } });
    const wrapper = mountDataContent();
    await flushPromises();
    expect(wrapper.get(".upload-disabled-notice").text()).toContain("This project is read-only");
    expect(wrapper.get(".upload-disabled-notice").attributes("role")).toBe("status");
    expect(wrapper.findAll("button").some(b => b.text() === "Retry access check")).toBe(false);
    wrapper.unmount();
  });

  it("keeps the deployment upload restriction visible without a project-access retry", async () => {
    mocks.disabledCapabilities.add("data_upload");
    const wrapper = mountDataContent();
    await flushPromises();
    expect(wrapper.get(".upload-disabled-notice").text()).toBe("File upload is disabled for this deployment.");
    expect(wrapper.findAll("button").some(b => b.text() === "Retry access check")).toBe(false);
    wrapper.unmount();
  });

  it.each(["one", "all"])("opens inspection on the first %s Preview selection in a fresh session", async (mode) => {
    const originalStore = mocks.dataStore;
    mocks.dataStore = reactive(originalStore);
    mocks.route.query = { tab: "my-dataset" };
    mocks.dataStore.activeExperimentId = null;
    const files = [...mocks.dataStore.experimentFiles];
    mocks.dataStore.experimentFiles = [];
    mocks.dataStore.selectExperiment.mockImplementationOnce(async (id: number) => {
      mocks.dataStore.activeExperimentId = id;
      mocks.dataStore.experimentFiles = files;
    });
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;

    if (mode === "one") await vm.onPlotExperimentToggle(mocks.dataStore.experiments[0], true);
    else await vm.onPlotAllExperiments(true);
    await flushPromises();

    expect(mocks.dataStore.selectExperiment).toHaveBeenCalledWith(11);
    expect(mocks.dataStore.inspectFile).toHaveBeenCalledWith(22, "raw/wine.csv", 11);
    expect(mocks.dataStore.fileInfo?.n_samples).toBe(178);
    expect(vm.plotDatasetSources.map((dataset) => dataset.experimentId)).toEqual([11]);
    expect(wrapper.text()).not.toContain("No dataset selected");
    expect(wrapper.text()).not.toContain("Select a dataset to view its files");
    wrapper.unmount();
    mocks.dataStore = originalStore;
  });

  it("offers qualified Pro reference import without fetching provider libraries", async () => {
    mocks.pro = true;
    const wrapper = mountDataContent();
    await flushPromises();
    wrapper.getComponent({ name: "TabView" }).vm.$emit("update:activeIndex", 0);
    await flushPromises();
    expect(wrapper.text()).toContain("Reference catalog");
    expect(wrapper.text()).toContain("Automatic provider downloads are unavailable");
    expect(wrapper.text()).not.toContain("Reference import unavailable");
    expect(mocks.dataStore.fetchReferenceCatalog).toHaveBeenCalled();
    expect(mocks.dataStore.fetchCatalog).not.toHaveBeenCalled();
    expect(wrapper.findComponent({ name: "SynthesisPanel" }).exists()).toBe(false);
  });

  it("shows a file inventory refusal without trying to inspect a failed first preview", async () => {
    const originalStore = mocks.dataStore;
    mocks.dataStore = reactive(originalStore);
    mocks.route.query = { tab: "my-dataset" };
    mocks.dataStore.activeExperimentId = null;
    mocks.dataStore.experimentFiles = [];
    mocks.dataStore.selectExperiment.mockImplementationOnce(async (id: number) => {
      mocks.dataStore.activeExperimentId = id;
      mocks.dataStore.experimentFilesRefusal = { code: "unavailable", message: "Source files unavailable" };
    });
    const wrapper = mountDataContent();
    await flushPromises();

    await (wrapper.vm as unknown as DataContentVm).onPlotExperimentToggle(mocks.dataStore.experiments[0], true);
    await flushPromises();

    expect(wrapper.text()).toContain("Source files unavailable");
    expect(mocks.dataStore.inspectFile).not.toHaveBeenCalled();
    expect(mocks.dataStore.inspectExperimentRawFiles).not.toHaveBeenCalled();
    expect(mocks.dataStore.fileInfo).toBeNull();
    wrapper.unmount();
    mocks.dataStore = originalStore;
  });

  it("still plots valid comparisons when Preview All cannot inspect its first dataset", async () => {
    mocks.route.query = { tab: "my-dataset" };
    mocks.dataStore.activeExperimentId = null;
    mocks.dataStore.experimentFiles = [];
    mocks.dataStore.experiments.push({ ...mocks.dataStore.experiments[0], id: 12, name: "Valid comparison" });
    mocks.dataStore.selectExperiment.mockImplementationOnce(async (id: number) => {
      mocks.dataStore.activeExperimentId = id;
      mocks.dataStore.experimentFilesRefusal = { code: "unavailable", message: "First source unavailable" };
    });
    // Even if the projection endpoint would succeed, do not bypass the refused
    // inventory by retrying the first dataset through that different endpoint.
    vi.mocked(api.post).mockResolvedValue({ data: {
      data: [[1, 2]], n_samples: 1, n_features: 2,
    } } as never);
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;

    await vm.onPlotAllExperiments(true);
    await flushPromises();

    expect(vm.plotDatasetSources.map((dataset) => dataset.experimentId)).toEqual([12]);
    expect(mocks.dataStore.fileInfo).toBeNull();
    expect(mocks.dataStore.experimentFilesRefusal?.message).toBe("First source unavailable");
    expect(api.post).toHaveBeenCalledWith("/builder/file-info", { experiment_id: 12 });
    expect(api.post).not.toHaveBeenCalledWith("/builder/file-info", { experiment_id: 11 });
    wrapper.unmount();
  });

  it("loads multi-file metadata when entering My Dataset after fresh project restoration", async () => {
    mocks.route.query = { tab: "import" };
    mocks.dataStore.activeExperimentId = null;
    const files = [22, 23, 24].map((id) => ({
      id, experiment_id: 11, file_path: `raw/spectra-${id}.csv`, stage: "raw",
      file_size_bytes: 2048, created_at: "2026-05-02T00:00:00Z",
    }));
    mocks.dataStore.experiments[0].file_count = 3;
    mocks.dataStore.restoreActiveExperimentForCurrentProject.mockImplementationOnce(async () => {
      mocks.dataStore.activeExperimentId = 11;
      mocks.dataStore.experimentFiles = files;
    });
    const wrapper = mountDataContent();
    await flushPromises();
    expect(mocks.dataStore.inspectExperimentRawFiles).not.toHaveBeenCalled();

    wrapper.getComponent({ name: "TabView" }).vm.$emit("update:activeIndex", 5);
    await flushPromises();

    expect(mocks.dataStore.inspectExperimentRawFiles).toHaveBeenCalledTimes(1);
    expect(mocks.dataStore.inspectExperimentRawFiles).toHaveBeenCalledWith(11, null, null);
    expect(mocks.dataStore.fileInfo?.n_samples).toBe(178);
    wrapper.unmount();
  });

  it("does not undo a newer tab choice when initial inspection finishes late", async () => {
    mocks.route.query = { tab: "import" };
    let finishInspection!: () => void;
    mocks.dataStore.inspectFile.mockImplementationOnce(() => new Promise((resolve) => {
      finishInspection = () => {
        mocks.dataStore.fileInfo = { label: "Wine", n_samples: 178, n_features: 13 };
        resolve(mocks.dataStore.fileInfo);
      };
    }));
    const wrapper = mountDataContent();
    await flushPromises();
    const tabs = wrapper.getComponent({ name: "TabView" });
    tabs.vm.$emit("update:activeIndex", 5);
    await flushPromises();
    expect(mocks.dataStore.inspectFile).toHaveBeenCalledTimes(1);

    tabs.vm.$emit("update:activeIndex", 0);
    await flushPromises();
    finishInspection();
    await flushPromises();

    expect(wrapper.get("[data-testid='data-tabs']").attributes("data-active-index")).toBe("0");
    wrapper.unmount();
  });

  it("keeps active inspection metadata while adding a comparison preview", async () => {
    mocks.route.query = { tab: "my-dataset" };
    const retained = { label: "Active Wine", n_samples: 178, n_features: 13 };
    mocks.dataStore.fileInfo = retained;
    const second = { ...mocks.dataStore.experiments[0], id: 12, name: "Comparison" };
    mocks.dataStore.experiments.push(second);
    vi.mocked(api.post).mockResolvedValue({ data: {
      data: [[1, 2]], n_samples: 1, n_features: 2, x_axis: { data: [1000, 1100] },
    }} as never);
    const wrapper = mountDataContent();
    await flushPromises();

    await (wrapper.vm as unknown as DataContentVm).onPlotExperimentToggle(second, true);

    expect(mocks.dataStore.activeExperimentId).toBe(11);
    expect(mocks.dataStore.fileInfo).toEqual(retained);
    expect(mocks.dataStore.selectExperiment).not.toHaveBeenCalled();
    expect(mocks.dataStore.inspectFile).not.toHaveBeenCalled();
    expect(mocks.dataStore.inspectExperimentRawFiles).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("does not replace the project selection with a stale experiment deep link", async () => {
    mocks.route.query = { tab: "my-dataset", experiment: "124" };

    const wrapper = mountDataContent();
    await flushPromises();

    expect(mocks.dataStore.selectExperiment).not.toHaveBeenCalledWith(124);
    expect(mocks.dataStore.activeExperimentId).toBe(11);
    expect(wrapper.find('[data-testid="data-tabs"]').attributes("data-active-index")).toBe("5");
  });

  it("opens a dataset-scoped multi-well acquisition deep link", async () => {
    mocks.route.query = { tab: "multi-well", experiment: "11" };

    const wrapper = mountDataContent();
    await flushPromises();

    expect(mocks.dataStore.selectExperiment).toHaveBeenCalledWith(11);
    expect(wrapper.find('[data-testid="data-tabs"]').attributes("data-active-index")).toBe("4");
  });

  it("returns from Workflow without reinspecting the retained dataset", async () => {
    mocks.route.query = { tab: "my-dataset", experiment: "11" };
    mocks.dataStore.fileInfo = { label: "Wine", n_samples: 178, n_features: 13 };
    mocks.dataStore.activeFileId = 22;
    const retained = mocks.dataStore.fileInfo;
    const wrapper = mountDataContent();
    await flushPromises();
    expect(mocks.dataStore.fileInfo).toBe(retained);
    expect(mocks.dataStore.selectExperiment).not.toHaveBeenCalled();
    expect(mocks.dataStore.inspectFile).not.toHaveBeenCalled();
    expect(mocks.dataStore.inspectExperimentRawFiles).not.toHaveBeenCalled();
    expect(mocks.dataStore.fetchFileAssets).not.toHaveBeenCalled();
    expect(wrapper.findComponent({ name: "DatasetSourcePreview" }).exists()).toBe(false);
    expect(wrapper.findComponent({ name: "SynthesisPanel" }).exists()).toBe(false);
    const tabs = wrapper.getComponent({ name: "TabView" });
    tabs.vm.$emit("update:activeIndex", 1);
    await flushPromises();
    const synthesis = wrapper.getComponent({ name: "SynthesisPanel" }).vm;
    tabs.vm.$emit("update:activeIndex", 4);
    await flushPromises();
    tabs.vm.$emit("update:activeIndex", 1);
    await flushPromises();
    expect(wrapper.getComponent({ name: "SynthesisPanel" }).vm).toBe(synthesis);
    wrapper.unmount();
  });

  it("does not wait for reference catalog jobs before showing My Dataset", async () => {
    mocks.route.query = { tab: "my-dataset", experiment: "11" };
    let finish!: () => void;
    mocks.dataStore.fetchReferenceCatalog.mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );
    const wrapper = mountDataContent();
    await flushPromises();
    expect(mocks.dataStore.inspectFile).toHaveBeenCalledTimes(1);
    finish();
    await flushPromises();
    wrapper.unmount();
  });

  it("honors an experiment deep link admitted by the active project", async () => {
    mocks.route.query = { tab: "my-dataset", experiment: "11" };

    mountDataContent();
    await flushPromises();

    expect(mocks.dataStore.selectExperiment).toHaveBeenCalledWith(11);
  });

  it("blocks workflow handoff until the active dataset readiness is available", async () => {
    mocks.dataStore.fileInfoLoading = true;
    const wrapper = mountDataContent();
    await flushPromises();

    const nextButton = wrapper.get(
      'button[title="Inspecting the active dataset before choosing an analysis starter."]',
    );
    expect(nextButton.attributes("disabled")).toBeDefined();
  });

  it("restores the dataset-scoped target and group after returning to My Dataset", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        metadata: {
          custody: { source: "reference" },
          analysis_selection: {
            schema_version: "spectra-sherpa-analysis-selection/1",
            selected_target: "cultivar",
            target_type: "categorical",
            group_column: "batch",
            source_digest: "a".repeat(64),
            updated_at: "2026-09-09T12:00:00Z",
          },
        },
      },
    } as never);

    const wrapper = mountDataContent();
    await flushPromises();

    const panel = wrapper.getComponent({ name: "DataContentsPanel" });
    expect(panel.props("initialAnalysisTarget")).toBe("cultivar");
    expect(panel.props("initialAnalysisGroup")).toBe("batch");
    expect(panel.props("analysisSelectionHydrated")).toBe(true);
    expect(panel.props("analysisSelectionStatus")).toBe("saved");
    // The panel may have no sample annotations yet, or a temporarily empty subset.
    panel.vm.$emit("analysisChoice", {
      target: "",
      targetType: null,
      targetUnits: null,
      sourceDigest: null,
      group: "",
      readiness: null,
    });
    await flushPromises();
    expect(panel.props("initialAnalysisTarget")).toBe("cultivar");
    expect(panel.props("initialAnalysisGroup")).toBe("batch");
    expect(api.put).not.toHaveBeenCalled();
  });

  it("saves an explicit target choice in place without reloading dataset lists", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { metadata: { custody: "retained" } } } as never);
    vi.mocked(api.put).mockResolvedValue({
      data: {
        schema_version: "spectra-sherpa-analysis-selection/1",
        selected_target: "moisture",
        target_type: "continuous",
        group_column: "specimen_id",
        source_digest: "b".repeat(64),
        updated_at: "2026-09-09T12:01:00Z",
      },
    } as never);
    const wrapper = mountDataContent();
    await flushPromises();
    mocks.dataStore.fetchExperiments.mockClear();
    mocks.dataStore.fetchCatalog.mockClear();

    wrapper.getComponent({ name: "DataContentsPanel" }).vm.$emit("analysisSelectionCommit", {
      target: "moisture",
      targetType: "continuous",
      targetUnits: "%",
      sourceDigest: "b".repeat(64),
      group: "specimen_id",
      readiness: null,
    });
    await flushPromises();

    expect(vi.mocked(api.put)).toHaveBeenCalledWith("/experiments/11/analysis-selection", {
      selected_target: "moisture",
      target_type: "continuous",
      group_column: "specimen_id",
      source_digest: "b".repeat(64),
    });
    expect(mocks.dataStore.fetchExperiments).not.toHaveBeenCalled();
    expect(mocks.dataStore.fetchCatalog).not.toHaveBeenCalled();
    expect(
      wrapper.getComponent({ name: "DataContentsPanel" }).props("analysisSelectionStatus"),
    ).toBe("saved");
    const panel = wrapper.getComponent({ name: "DataContentsPanel" });
    expect(panel.props("initialAnalysisTarget")).toBe("moisture");
    expect(panel.props("initialAnalysisGroup")).toBe("specimen_id");
    panel.vm.$emit("analysisSelectionCommit", {
      target: "",
      targetType: null,
      targetUnits: null,
      sourceDigest: null,
      group: "",
      readiness: null,
    });
    await flushPromises();
    expect(panel.props("initialAnalysisTarget")).toBe("");
    expect(panel.props("initialAnalysisGroup")).toBe("");
  });

  it("labels a blank Collection Load as pending its first sheet binding", async () => {
    mocks.route.query = {
      tab: "my-dataset",
      project_id: "3",
      workflow: "41",
      source_node: "source-blank",
    };
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url.includes("/data-selections/")) {
        return {
          data: {
            workflow_id: 41,
            workflow_name: "Blank analysis",
            source_node_id: "source-blank",
            source_node_label: "Collection Load",
            project_id: 3,
            current_revision: null,
            saved_selection: null,
          },
        } as never;
      }
      return { data: {} } as never;
    });

    const wrapper = mountDataContent();
    await flushPromises();

    const context = wrapper.get('[aria-label="Workflow sheet data selection"]');
    expect(context.text()).toContain("Pending first binding");
    expect(context.text()).toContain("Choose this source node's dataset, views, target, and groups");
    expect(context.text()).not.toContain("revision 1");
    wrapper.unmount();
  });

  it("restores and applies target choices to one workflow sheet without changing dataset defaults", async () => {
    mocks.route.query = {
      tab: "my-dataset",
      project_id: "3",
      workflow: "41",
      source_node: "source-1",
      experiment: "11",
    };
    const savedSelection = {
      experiment_id: 11,
      dataset_name: "Wine",
      stage: "raw",
      selected_file_ids: [22],
      asset_id: null,
      source_manifest_sha256: "a".repeat(64),
      collection_definition_sha256: "b".repeat(64),
      scientific_collection_sha256: "c".repeat(64),
      target_authority: {
        schema_version: "spectrasherpa-target-authority/1",
        column: "cultivar",
        target_type: "categorical",
        units: null,
        source_digest: "c".repeat(64),
      },
      group_column: "batch",
    };
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url.includes("/data-selections/")) {
        return {
          data: {
            workflow_id: 41,
            workflow_name: "Wine PLS-DA",
            source_node_id: "source-1",
            source_node_label: "Training cohort",
            project_id: 3,
            current_revision: null,
            saved_selection: savedSelection,
          },
        } as never;
      }
      return { data: { metadata: { analysis_selection: null } } } as never;
    });
    mocks.dataStore.inspectExperimentRawFiles.mockImplementation(async () => {
      mocks.dataStore.fileInfo = {
        label: "Wine",
        n_samples: 178,
        n_features: 13,
        metadata: {
          source_collection: {
            source_manifest_sha256: "a".repeat(64),
            collection_definition_sha256: "b".repeat(64),
            scientific_collection_sha256: "c".repeat(64),
          },
        },
      };
      return mocks.dataStore.fileInfo;
    });
    mocks.dataStore.inspectFile.mockImplementation(async (fileId: number, filePath: string) => {
      mocks.dataStore.activeFileId = fileId;
      mocks.dataStore.activeFilePath = filePath;
      mocks.dataStore.fileInfo = {
        label: "Wine",
        n_samples: 178,
        n_features: 13,
        metadata: {
          source_collection: {
            source_manifest_sha256: "a".repeat(64),
            collection_definition_sha256: "b".repeat(64),
            scientific_collection_sha256: "c".repeat(64),
          },
        },
      };
      return mocks.dataStore.fileInfo;
    });
    vi.mocked(api.put).mockResolvedValue({
      data: {
        id: 71,
        revision_number: 1,
        created_by_name: "testuser",
        created_at: "2026-09-20T10:00:00Z",
        reason: null,
        selection: savedSelection,
      },
    } as never);

    const wrapper = mountDataContent();
    await flushPromises();
    const panel = wrapper.getComponent({ name: "DataContentsPanel" });
    expect(panel.props("initialAnalysisTarget")).toBe("cultivar");
    expect(panel.props("initialAnalysisGroup")).toBe("batch");
    expect(wrapper.text()).toContain("Wine PLS-DA");

    panel.vm.$emit("analysisSelectionCommit", {
      target: "cultivar",
      targetType: "categorical",
      targetUnits: null,
      sourceDigest: "c".repeat(64),
      group: "batch",
      readiness: null,
    });
    await flushPromises();
    expect(vi.mocked(api.put)).not.toHaveBeenCalledWith(
      "/experiments/11/analysis-selection",
      expect.anything(),
    );

    await (wrapper.vm as unknown as DataContentVm).applyWorkflowDataSelection();
    expect(vi.mocked(api.put)).toHaveBeenCalledWith(
      "/workflows/41/data-selections/source-1",
      expect.objectContaining({
        expected_revision: null,
        origin: "data_page",
        selection: expect.objectContaining({
          experiment_id: 11,
          selected_file_ids: [22],
          target_authority: expect.objectContaining({ column: "cultivar" }),
          group_column: "batch",
        }),
      }),
    );
    expect(mocks.routerPush).toHaveBeenCalledWith({
      path: "/workflow",
      query: { project_id: "3", workflow_id: "41" },
    });
  });

  it("keeps a deleted saved definition's sheet inspectable on its exact file cohort", async () => {
    mocks.route.query = {
      tab: "my-dataset",
      project_id: "3",
      workflow: "41",
      source_node: "source-1",
      experiment: "11",
    };
    mocks.dataStore.experiments[0].file_count = 2;
    mocks.dataStore.experimentFiles.push({
      id: 23,
      experiment_id: 11,
      file_path: "raw/other.csv",
      file_size_bytes: 2048,
      stage: "raw",
      created_at: "2026-05-02T00:00:00Z",
    });
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url.includes("/data-selections/")) {
        return { data: {
          workflow_id: 41, workflow_name: "Wine PLS-DA", source_node_id: "source-1",
          source_node_label: "Training cohort", project_id: 3, current_revision: null,
          saved_selection: {
            experiment_id: 11, dataset_name: "Wine", stage: "raw",
            selected_file_ids: [22], asset_id: null,
            source_manifest_sha256: "a".repeat(64),
            collection_definition_sha256: null,
            scientific_collection_sha256: "c".repeat(64),
            target_authority: null, group_column: null,
            dataset_view_id: 41, dataset_view_sha256: "d".repeat(64),
          },
        } } as never;
      }
      if (url.includes("/dataset-views/41")) throw { response: { status: 404 } };
      return { data: {} } as never;
    });

    const wrapper = mountDataContent();
    await flushPromises();

    expect(wrapper.text()).toContain("This sheet's saved definition was deleted");
    expect(mocks.dataStore.inspectFile).toHaveBeenCalledWith(22, "raw/wine.csv", 11);
    expect(mocks.dataStore.inspectExperimentRawFiles).not.toHaveBeenCalledWith(11);
    wrapper.unmount();
  });

  it("inspects a single-view dataset through its exact file before workflow handoff", async () => {
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;
    mocks.dataStore.inspectFile.mockClear();
    mocks.dataStore.inspectExperimentRawFiles.mockClear();

    await vm.onExperimentSelect(mocks.dataStore.experiments[0]);

    expect(mocks.dataStore.inspectFile).toHaveBeenCalledWith(22, "raw/wine.csv", 11);
    expect(mocks.dataStore.inspectExperimentRawFiles).not.toHaveBeenCalled();
  });

  it("presents one progressive source chooser instead of separate file, folder, and ZIP buttons", async () => {
    const wrapper = mountDataContent();
    await flushPromises();

    const actions = wrapper.get(".upload-source-actions");
    const buttons = actions.findAll("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0].text()).toContain("Choose sources");
    expect(actions.findAll('input[type="file"]')).toHaveLength(2);
  });

  it("binds the selected dataset and exact file inventory to the definition panel", async () => {
    const wrapper = mountDataContent();
    await flushPromises();

    const panel = wrapper.get("[data-testid='collection-definition-panel']");
    expect(panel.attributes("data-experiment-id")).toBe("11");
    expect(panel.attributes("data-refresh-key")).toBe("22:raw:2048");
  });

  it("loads every checkbox-selected packaged dataset into the shared plot surface", async () => {
    const second = {
      id: 12,
      name: "JF observations",
      description: "Independent observations",
      file_count: 6,
      created_at: "2026-05-03T00:00:00Z",
    };
    mocks.dataStore.experiments = [...mocks.dataStore.experiments, second];
    vi.mocked(api.post).mockImplementation(async (_path, body) => {
      const experimentId = Number((body as { experiment_id: number }).experiment_id);
      return {
        data: {
          data_role: "X_spectra",
          n_samples: 1,
          n_features: 3,
          data: [[experimentId, experimentId + 1, experimentId + 2]],
          x_axis: { data: [1800, 1200, 600], title: "Wavenumber", units: "cm-1" },
          y_axis: { labels: [`sample-${experimentId}`] },
          metadata: { is_spectra: true, data_quantity: "Absorbance" },
        },
      } as never;
    });
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;

    await vm.onExperimentSelect(mocks.dataStore.experiments[0]);
    await vm.onPlotExperimentToggle(mocks.dataStore.experiments[0], true);
    await vm.onPlotExperimentToggle(second, true);
    await flushPromises();

    expect(vm.plottedExperimentIds).toEqual([11, 12]);
    expect(vm.plotDatasetSources.map((source) => source.experimentId)).toEqual([11, 12]);
    expect(vi.mocked(api.post)).toHaveBeenCalledWith("/builder/file-info", {
      experiment_id: 12,
    });
    expect(wrapper.get("[data-testid='contents-panel']").attributes("data-plot-count")).toBe("2");
    expect(wrapper.get("[data-testid='contents-panel']").attributes("data-plot-sources")).toBe("2");
    const projectionCalls = () =>
      vi.mocked(api.post).mock.calls.filter(([url]) => url === "/builder/file-info").length;
    const beforeReturn = projectionCalls();
    wrapper.unmount();
    const returned = mountDataContent();
    await flushPromises();
    expect(projectionCalls()).toBe(beforeReturn);
    expect(
      (returned.vm as unknown as DataContentVm).plotDatasetSources.map(
        (source) => source.experimentId,
      ),
    ).toEqual([11, 12]);
    returned.unmount();
  });

  it("atomically replaces comparison and workflow context when the active dataset changes", async () => {
    const second = {
      id: 12,
      name: "UV spectra",
      description: "Independent UV collection",
      file_count: 1,
      created_at: "2026-05-03T00:00:00Z",
    };
    const secondFile = {
      ...mocks.dataStore.experimentFiles[0],
      id: 23,
      experiment_id: 12,
      file_path: "raw/uv.csv",
    };
    mocks.dataStore.experiments = [...mocks.dataStore.experiments, second];
    mocks.dataStore.selectExperiment.mockImplementation(async (id: number) => {
      mocks.dataStore.activeExperimentId = id;
      mocks.dataStore.experimentFiles = id === 12 ? [secondFile] : [mocks.dataStore.experimentFiles[0]];
      mocks.dataStore.activeFileId = null;
      mocks.dataStore.activeFilePath = null;
      mocks.dataStore.fileInfo = null;
    });
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;

    await vm.onPlotExperimentToggle(mocks.dataStore.experiments[0], true);
    await vm.onPlotExperimentToggle(second, true);
    expect(vm.plottedExperimentIds).toEqual([11, 12]);

    await vm.onExperimentSelect(second);
    await flushPromises();

    expect(vm.plottedExperimentIds).toEqual([12]);
    expect(Object.keys(vm.plotFileSelections)).toEqual(["12"]);
    expect(mocks.dataStore.activeExperimentId).toBe(12);
    await vm.goToWorkflow();
    const receipt = latestWorkflowReceipt();
    expect(receipt.datasets).toEqual([
      expect.objectContaining({ experiment_id: 12, dataset_name: "UV spectra" }),
    ]);
  });

  it("does not let an obsolete inspection response overwrite a newer active dataset", async () => {
    const wine = mocks.dataStore.experiments[0];
    const uv = {
      id: 12,
      name: "UV spectra",
      description: "Independent UV collection",
      file_count: 1,
      created_at: "2026-05-03T00:00:00Z",
    };
    const wineFile = mocks.dataStore.experimentFiles[0];
    const uvFile = { ...wineFile, id: 23, experiment_id: 12, file_path: "raw/uv.csv" };
    mocks.dataStore.experiments = [wine, uv];
    mocks.dataStore.selectExperiment.mockImplementation(async (id: number) => {
      mocks.dataStore.activeExperimentId = id;
      mocks.dataStore.experimentFiles = id === 12 ? [uvFile] : [wineFile];
      mocks.dataStore.fileInfo = null;
    });
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;
    let releaseWineAssets: ((value: unknown) => void) | undefined;
    const wineAssets = new Promise((resolve) => {
      releaseWineAssets = resolve;
    });
    mocks.dataStore.fetchFileAssets.mockClear();
    mocks.dataStore.inspectFile.mockClear();
    mocks.dataStore.fetchFileAssets
      .mockImplementationOnce(() => wineAssets)
      .mockResolvedValue({
        format_id: "csv",
        variant: "headered-matrix",
        parser_id: "spectrasherpa.csv",
        parser_version: "1",
        source_sha256: "b".repeat(64),
        assets: [{ asset_id: "data", title: "Data", shape: [120, 2038], warnings: [] }],
      });

    const openingWine = vm.onExperimentSelect(wine);
    await flushPromises();
    const openingUv = vm.onExperimentSelect(uv);
    await openingUv;
    releaseWineAssets?.({
      format_id: "csv",
      variant: "headered-matrix",
      parser_id: "spectrasherpa.csv",
      parser_version: "1",
      source_sha256: "a".repeat(64),
      assets: [{ asset_id: "data", title: "Data", shape: [178, 13], warnings: [] }],
    });
    await openingWine;

    expect(mocks.dataStore.activeExperimentId).toBe(12);
    expect(mocks.dataStore.inspectFile).toHaveBeenCalledWith(uvFile.id, uvFile.file_path, 12);
    expect(mocks.dataStore.inspectFile).not.toHaveBeenCalledWith(
      wineFile.id,
      wineFile.file_path,
      11,
    );
  });

  it("does not let an obsolete file-list response restore the prior dataset context", async () => {
    const wine = mocks.dataStore.experiments[0];
    const uv = {
      id: 12,
      name: "UV spectra",
      description: "Independent UV collection",
      file_count: 1,
      created_at: "2026-05-03T00:00:00Z",
    };
    const wineFile = mocks.dataStore.experimentFiles[0];
    const uvFile = { ...wineFile, id: 23, experiment_id: 12, file_path: "raw/uv.csv" };
    mocks.dataStore.experiments = [wine, uv];
    let releaseWineFiles: (() => void) | undefined;
    const wineFiles = new Promise<void>((resolve) => {
      releaseWineFiles = resolve;
    });
    mocks.dataStore.selectExperiment.mockImplementation(async (id: number) => {
      mocks.dataStore.activeExperimentId = id;
      mocks.dataStore.experimentFiles = [];
      mocks.dataStore.fileInfo = null;
      if (id === wine.id) {
        await wineFiles;
        // The store itself rejects the stale response, so the active UV state
        // remains authoritative when this caller resumes.
        return;
      }
      mocks.dataStore.experimentFiles = [uvFile];
    });
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;
    mocks.routerReplace.mockClear();
    mocks.dataStore.inspectFile.mockClear();

    const openingWine = vm.onExperimentSelect(wine);
    await flushPromises();
    const openingUv = vm.onExperimentSelect(uv);
    await openingUv;
    releaseWineFiles?.();
    await openingWine;

    expect(mocks.dataStore.activeExperimentId).toBe(12);
    expect(vm.plottedExperimentIds).toEqual([12]);
    expect(mocks.dataStore.inspectFile).toHaveBeenCalledWith(uvFile.id, uvFile.file_path, 12);
    expect(mocks.dataStore.inspectFile).not.toHaveBeenCalledWith(
      wineFile.id,
      wineFile.file_path,
      11,
    );
    expect(mocks.routerReplace).toHaveBeenCalledTimes(1);
    expect(mocks.routerReplace).toHaveBeenCalledWith({
      path: "/data",
      query: { tab: "my-dataset", experiment: "12" },
    });
  });

  it("removes a superseded registered dataset from the plot without poisoning valid selections", async () => {
    vi.mocked(api.post).mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 409,
        data: {
          detail: {
            code: "trial_dataset_authority_superseded",
            message: "Import the reviewed reference file again.",
          },
        },
      },
    });
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;

    await vm.onPlotExperimentToggle(mocks.dataStore.experiments[0], true);
    await flushPromises();

    expect(vm.plottedExperimentIds).toEqual([]);
    expect(vm.plotDatasetSources).toEqual([]);
    expect(mocks.toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Outdated dataset removed from plot" }),
    );
  });

  it("turns a fully selected dataset into a partial selection when one file is cleared", async () => {
    mocks.dataStore.experiments[0].file_count = 2;
    const first = mocks.dataStore.experimentFiles[0];
    const second = { ...first, id: 23, file_path: "raw/second.spa" };
    mocks.dataStore.experimentFiles = [first, second];
    vi.mocked(api.post).mockImplementation(async () => ({
      data: {
        data_role: "X_spectra",
        n_samples: 1,
        n_features: 3,
        data: [[0.1, 0.2, 0.3]],
        x_axis: { data: [1800, 1200, 600], title: "Wavenumber", units: "cm-1" },
        y_axis: { labels: ["sample"] },
        metadata: { is_spectra: true, data_quantity: "Absorbance" },
      },
    })) as never;
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;

    await vm.onPlotExperimentToggle(mocks.dataStore.experiments[0], true);
    mocks.dataStore.activeFileId = second.id;
    mocks.dataStore.activeFilePath = second.file_path;
    mocks.dataStore.activateFile.mockClear();
    await vm.onPlotFileToggle(first, false);
    await flushPromises();

    expect(vm.isExperimentPartlyPlotted(11)).toBe(true);
    expect(vm.plotDatasetSources[0].members).toEqual([
      expect.objectContaining({ fileName: "second.spa" }),
    ]);
    expect(vi.mocked(api.post)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.post)).toHaveBeenLastCalledWith("/builder/file-info", {
      experiment_id: 11,
    });
    expect(mocks.dataStore.activateFile).toHaveBeenCalledWith(second.id, second.file_path);
  });

  it("keeps checkbox changes local after loading the complete collection", async () => {
    mocks.dataStore.experiments[0].file_count = 2;
    const first = mocks.dataStore.experimentFiles[0];
    const second = { ...first, id: 23, file_path: "raw/second.spa" };
    mocks.dataStore.experimentFiles = [first, second];
    const dataset = {
      n_samples: 2,
      n_features: 3,
      data: [
        [1, 2, 3],
        [4, 5, 6],
      ],
      metadata: {
        source_member_metadata: [{ file_name: first.file_path }, { file_name: second.file_path }],
      },
    };
    mocks.dataStore.inspectExperimentRawFiles.mockImplementationOnce(async () => {
      mocks.dataStore.fileInfo = dataset;
      return dataset;
    });
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;
    await vm.showExperimentContents(11);
    await vm.onPlotExperimentToggle(mocks.dataStore.experiments[0], true);
    mocks.dataStore.inspectExperimentRawFiles.mockClear();
    mocks.dataStore.inspectFile.mockClear();
    mocks.dataStore.fetchFileAssets.mockClear();
    vi.mocked(api.post).mockClear();
    await vm.onPlotFileToggle(first, false);
    await vm.onPlotFileToggle(first, true);
    await vm.onPlotFileToggle(second, false);
    expect(mocks.dataStore.inspectExperimentRawFiles).not.toHaveBeenCalled();
    expect(mocks.dataStore.inspectFile).not.toHaveBeenCalled();
    expect(mocks.dataStore.fetchFileAssets).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
    expect(mocks.dataStore.fileInfo).toBe(dataset);
    expect(vm.plotDatasetSources[0].selectedFileNames).toEqual([first.file_path]);
    await vm.goToWorkflow();
    expect(mocks.dataStore.inspectExperimentRawFiles).toHaveBeenCalledOnce();
    expect(mocks.dataStore.inspectExperimentRawFiles).toHaveBeenCalledWith(11, null, [first.id]);
    expect(mocks.routerPush).toHaveBeenCalledWith({
      path: "/workflow",
      query: expect.objectContaining({
        fromDataSelection: "1",
        project_id: 3,
        selection: expect.any(String),
      }),
    });
    wrapper.unmount();
    const returned = mountDataContent();
    await flushPromises();
    expect(mocks.dataStore.fileInfo).toBe(dataset);
    mocks.dataStore.inspectExperimentRawFiles.mockClear();
    mocks.dataStore.fetchFileAssets.mockClear();
    vi.mocked(api.post).mockClear();
    await (returned.vm as unknown as DataContentVm).onPlotFileToggle(second, true);
    expect(mocks.dataStore.inspectExperimentRawFiles).not.toHaveBeenCalled();
    expect(mocks.dataStore.fetchFileAssets).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
    returned.unmount();
  });

  it("makes a heterogeneous registered package view set explicit and narrows it in one action", async () => {
    mocks.dataStore.experiments[0].file_count = 3;
    mocks.dataStore.fileInfo = {
      ...mocks.dataStore.fileInfo,
      sample_axis: {
        sample_table: {
          analysis_role: ["normal", "normal", "fault"],
        },
      },
    };
    const base = mocks.dataStore.experimentFiles[0];
    const machine = { ...base, id: 31, file_path: "raw/metal-etch-machine.csv", n_samples: 1 };
    const oes = { ...base, id: 32, file_path: "raw/metal-etch-oes.csv", n_samples: 2 };
    const rfm = { ...base, id: 33, file_path: "raw/metal-etch-rfm.csv", n_samples: 3 };
    mocks.dataStore.experimentFiles = [machine, oes, rfm];
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;

    await vm.onPlotExperimentToggle(mocks.dataStore.experiments[0], true);
    await flushPromises();
    expect(wrapper.text()).toContain("Workflow view set:");
    expect(wrapper.text()).toContain(
      "Machine sensors (1 row), Optical emission spectra (2 rows), RF-monitor variables (3 rows)",
    );
    expect(wrapper.text()).toContain("different feature spaces");
    expect(wrapper.text()).toContain("Provider row roles: normal (2), fault (1)");
    expect(wrapper.text()).toContain("remain descriptive metadata");

    mocks.dataStore.inspectExperimentRawFiles.mockClear();
    await vm.useOnlyDataView(oes);
    await flushPromises();

    expect(mocks.dataStore.inspectExperimentRawFiles).toHaveBeenCalledWith(11, null, [oes.id]);
    expect(wrapper.text()).toContain("Optical emission spectra");
    expect(wrapper.text()).toContain("single view used for preview and workflow modeling");
  });

  it("resolves GUI-01 target authority from the current collection before workflow handoff", async () => {
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;
    const panel = wrapper.getComponent({ name: "DataContentsPanel" });
    const choice = {
      target: "assay",
      targetType: "continuous",
      targetUnits: null,
      sourceDigest: null,
      group: "",
      readiness: null,
    };
    panel.vm.$emit("analysisChoice", choice);
    mocks.dataStore.inspectExperimentRawFiles.mockClear();
    const readiness = {
      profile: { target_type: "continuous", target_fields: ["assay"] },
      decisions: [],
    };
    vi.mocked(api.post).mockResolvedValueOnce({ data: readiness });
    mocks.dataStore.inspectExperimentRawFiles.mockImplementationOnce(async () => {
      mocks.dataStore.fileInfo = { analysis_readiness: readiness };
      panel.vm.$emit("analysisChoice", { ...choice, sourceDigest: "b".repeat(64) });
      return mocks.dataStore.fileInfo;
    });
    await vm.goToWorkflow();
    expect(mocks.dataStore.inspectExperimentRawFiles).toHaveBeenCalledWith(11, null, undefined);
    const receipt = latestWorkflowReceipt();
    expect(receipt?.target_authority).toEqual(
      expect.objectContaining({
        column: "assay",
        target_type: "continuous",
        source_digest: "b".repeat(64),
      }),
    );
    expect(mocks.routerPush).toHaveBeenCalled();
    wrapper.unmount();
  });

  it.each(["resolved", "rejected", "selection-changed"])(
    "waits for the exact selected target readiness before handoff (%s)",
    async (outcome) => {
      const wrapper = mountDataContent();
      await flushPromises();
      const vm = wrapper.vm as unknown as DataContentVm;
      const panel = wrapper.getComponent({ name: "DataContentsPanel" });
      const profile = {
        primary_role: "X_spectra",
        modality: "spectra",
        technique: "NIR",
        target_type: "continuous",
        target_fields: ["assay", "weight"],
        identity_fields: [],
        group_fields: [],
        ordered_samples: false,
      };
      const choice = {
        target: "assay",
        targetType: "continuous",
        targetUnits: null,
        sourceDigest: "b".repeat(64),
        group: "",
        readiness: null,
      };
      panel.vm.$emit("analysisChoice", choice);
      mocks.dataStore.inspectExperimentRawFiles.mockImplementationOnce(async () => {
        mocks.dataStore.fileInfo = { analysis_readiness: { profile } };
        return mocks.dataStore.fileInfo;
      });
      let resolve!: (value: unknown) => void;
      let reject!: (error: Error) => void;
      const pending = new Promise((yes, no) => {
        resolve = yes;
        reject = no;
      });
      vi.mocked(api.post).mockReturnValueOnce(pending as never);
      const navigation = vm.goToWorkflow();
      await flushPromises();
      expect(mocks.routerPush).not.toHaveBeenCalled();
      expect(api.post).toHaveBeenCalledWith("/workflow-templates/compatibility-preview", {
        analysis_profile: { ...profile, target_fields: ["assay"] },
      });
      const readiness = {
        profile: { ...profile, target_fields: ["assay"] },
        counts: { compatible: 1 },
        decisions: [],
      };
      if (outcome === "selection-changed")
        panel.vm.$emit("analysisChoice", { ...choice, target: "weight" });
      if (outcome === "rejected") reject(new Error("Compatibility unavailable"));
      else resolve({ data: readiness });
      await navigation;
      if (outcome === "resolved") {
        const receipt = latestWorkflowReceipt();
        expect(receipt.analysis_readiness).toEqual(readiness);
        expect(receipt.target_authority.column).toBe("assay");
        expect(mocks.routerPush).toHaveBeenCalled();
      } else {
        expect(mocks.routerPush).not.toHaveBeenCalled();
        expect(storedWorkflowReceiptCount()).toBe(0);
      }
      wrapper.unmount();
    },
  );

  it.each(["refused", "target-removed", "source-changed"])(
    "does not carry stale GUI-01 authority when reinspection is %s",
    async (outcome) => {
      const wrapper = mountDataContent();
      await flushPromises();
      const vm = wrapper.vm as unknown as DataContentVm;
      const panel = wrapper.getComponent({ name: "DataContentsPanel" });
      panel.vm.$emit("analysisChoice", {
        target: "assay",
        targetType: "continuous",
        targetUnits: null,
        sourceDigest: "a".repeat(64),
        group: "",
        readiness: null,
      });
      mocks.routerPush.mockClear();
      mocks.dataStore.inspectExperimentRawFiles.mockImplementationOnce(async () => {
        if (outcome === "refused") throw new Error("Source could not be admitted");
        if (outcome === "target-removed")
          panel.vm.$emit("analysisChoice", {
            target: "",
            targetType: null,
            targetUnits: null,
            sourceDigest: "b".repeat(64),
            group: "",
            readiness: null,
          });
        if (outcome === "source-changed") mocks.dataStore.activeExperimentId = 12;
        return mocks.dataStore.fileInfo;
      });
      await vm.goToWorkflow();
      expect(mocks.routerPush).not.toHaveBeenCalled();
      expect(storedWorkflowReceiptCount()).toBe(0);
      wrapper.unmount();
    },
  );

  it("hands the exact selected dataset membership to the workflow workspace", async () => {
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;

    await vm.onPlotExperimentToggle(mocks.dataStore.experiments[0], true);
    vm.goToWorkflow();

    const receipt = latestWorkflowReceipt();
    expect(receipt).toEqual(
      expect.objectContaining({
        schema_version: "spectra-my-dataset-workflow-selection/3",
        receipt_id: expect.any(String),
        project_id: 3,
        datasets: [
          expect.objectContaining({
            experiment_id: 11,
            selection: "all",
            file_ids: null,
            stage: "raw",
          }),
        ],
      }),
    );
    expect(mocks.routerPush).toHaveBeenCalledWith({
      path: "/workflow",
      query: expect.objectContaining({
        fromDataSelection: "1",
        project_id: 3,
        selection: expect.any(String),
      }),
    });
  });

  it("carries the active My Dataset selection to Workflow even when it is not plotted", async () => {
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;

    vm.goToWorkflow();

    const receipt = latestWorkflowReceipt();
    expect(receipt.datasets).toEqual([
      expect.objectContaining({
        experiment_id: 11,
        dataset_name: "Wine",
        selection: "all",
        file_ids: null,
        stage: "raw",
      }),
    ]);
    expect(mocks.routerPush).toHaveBeenCalledWith({
      path: "/workflow",
      query: expect.objectContaining({
        fromDataSelection: "1",
        project_id: 3,
        selection: expect.any(String),
      }),
    });
  });

  it("does not turn previewed datasets into additional workflow inputs", async () => {
    const second = {
      id: 12,
      name: "Preview comparison",
      description: "Shown only in the shared preview",
      file_count: 1,
      created_at: "2026-05-03T00:00:00Z",
    };
    mocks.dataStore.experiments = [...mocks.dataStore.experiments, second];
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;

    await vm.onPlotExperimentToggle(mocks.dataStore.experiments[0], true);
    await vm.onPlotExperimentToggle(second, true);
    vm.goToWorkflow();

    const receipt = latestWorkflowReceipt();
    expect(receipt.datasets).toEqual([
      expect.objectContaining({ experiment_id: 11, dataset_name: "Wine" }),
    ]);
  });

  it("retains a synthetic dataset stage in the workflow selection", async () => {
    mocks.dataStore.experimentFiles = [
      {
        ...mocks.dataStore.experimentFiles[0],
        file_path: "synthetic/Synthetic_atmospheric-6.npz",
        stage: "synthetic",
      },
    ];
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;

    vm.goToWorkflow();

    const receipt = latestWorkflowReceipt();
    expect(receipt.datasets).toEqual([
      expect.objectContaining({
        experiment_id: 11,
        selection: "subset",
        file_ids: [22],
        stage: "synthetic",
      }),
    ]);
  });

  it("refuses to disguise mixed processing stages as one workflow source", async () => {
    const raw = mocks.dataStore.experimentFiles[0];
    const preprocessed = {
      ...raw,
      id: 23,
      file_path: "preprocessed/wine.csv",
      stage: "preprocessed" as const,
    };
    mocks.dataStore.experiments[0].file_count = 2;
    mocks.dataStore.experimentFiles = [raw, preprocessed];
    vi.mocked(api.post).mockResolvedValue({
      data: {
        data_role: "X_spectra",
        n_samples: 1,
        n_features: 2,
        data: [[1, 2]],
      },
    } as never);
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;

    await vm.onPlotFileToggle(raw, true);
    await vm.onPlotFileToggle(preprocessed, true);
    vm.goToWorkflow();

    expect(mocks.routerPush).not.toHaveBeenCalled();
    expect(mocks.toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        summary: "Choose one processing stage",
        detail: expect.stringContaining("more than one stage"),
      }),
    );
  });

  it("ignores a delayed definition event from a previously selected dataset", async () => {
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;
    mocks.dataStore.inspectExperimentRawFiles.mockClear();

    await vm.onCollectionDefinitionChanged({
      experiment_id: 12,
      status: "attached",
      message: "old dataset attached",
    });

    expect(mocks.toastAdd).not.toHaveBeenCalled();
    expect(mocks.dataStore.clearInspection).not.toHaveBeenCalled();
    expect(mocks.dataStore.inspectExperimentRawFiles).not.toHaveBeenCalled();
  });

  it("loads a file into Contents and persists the file deep link", async () => {
    const wrapper = mountDataContent();
    await flushPromises();
    mocks.dataStore.inspectFile.mockClear();

    const fileRows = wrapper.findAll(".file-row");
    expect(fileRows.length).toBeGreaterThan(0);

    await fileRows[fileRows.length - 1].trigger("click");
    await flushPromises();

    expect(mocks.dataStore.activateFile).toHaveBeenCalledWith(22, "raw/wine.csv");
    expect(mocks.dataStore.inspectFile).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="data-tabs"]').attributes("data-active-index")).toBe("5");
    expect(localStorage.getItem("spectra_sherpa_data_active_tab_v3_7_3")).toBe("5");
    expect(mocks.routerReplace).toHaveBeenCalledWith({
      path: "/data",
      query: {
        tab: "my-dataset",
        experiment: "11",
        fileId: "22",
      },
    });
  });

  it("shows each row-aligned sample label on hover without activating the file", async () => {
    mocks.dataStore.experiments[0].file_count = 2;
    mocks.dataStore.experimentFiles = [
      mocks.dataStore.experimentFiles[0],
      {
        id: 23,
        experiment_id: 11,
        file_path: "raw/reference.spa",
        file_size_bytes: 4096,
        stage: "raw",
        created_at: "2026-05-02T00:00:00Z",
      },
    ];
    mocks.dataStore.inspectFile.mockImplementationOnce(async (fileId: number, filePath: string) => {
      mocks.dataStore.activeFileId = fileId;
      mocks.dataStore.activeFilePath = filePath;
      mocks.dataStore.fileInfo = {
        data: [[3, 4]],
        n_samples: 1,
        n_features: 2,
        y_axis: { labels: ["NRL"] },
      };
      return mocks.dataStore.fileInfo;
    });
    vi.mocked(api.post).mockResolvedValue({
      data: {
        data: [
          [1, 2],
          [3, 4],
        ],
        n_samples: 2,
        n_features: 2,
        y_axis: { labels: ["ESL", "NRL"] },
        metadata: {
          source_member_metadata: [
            { metadata: { source_file: "wine.csv" } },
            { metadata: { source_file: "reference.spa" } },
          ],
        },
      },
    } as never);

    const wrapper = mountDataContent();
    await flushPromises();
    let rows = wrapper.findAll(".file-row");
    await rows[1].trigger("click");
    await flushPromises();

    rows = wrapper.findAll(".file-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].classes()).not.toContain("selected");
    expect(rows[0].attributes("title")).toBe("Sample label: ESL");
    expect(rows[1].attributes("title")).toBe("Sample label: NRL");
    expect(rows[1].attributes("aria-label")).toBe("reference.spa. Sample label: NRL");
  });

  it("shows an actionable refusal when scientific-asset inventory fails", async () => {
    const wrapper = mountDataContent();
    await flushPromises();
    mocks.dataStore.fileInfoError = "OPUS derivative order 1 is not independently qualified";
    mocks.dataStore.fetchFileAssets.mockRejectedValueOnce(new Error("inventory rejected"));

    const vm = wrapper.vm as unknown as DataContentVm;
    await vm.onInspectFile(mocks.dataStore.experimentFiles[0], { updateRoute: false });
    await flushPromises();

    expect(mocks.toastAdd).toHaveBeenCalledWith({
      severity: "error",
      summary: "Scientific results unavailable",
      detail: "OPUS derivative order 1 is not independently qualified",
      life: 6000,
    });
  });

  it("renders persisted-file scientific import warnings", async () => {
    const warning = "WiRE-derived MAP analysis layers were not imported";
    const wrapper = mountDataContent();
    await flushPromises();
    mocks.dataStore.fetchFileAssets.mockResolvedValueOnce({
      format_id: "wdf",
      variant: "series",
      parser_id: "spectrasherpa.native.wdf",
      parser_version: "1",
      source_sha256: "b".repeat(64),
      assets: [
        { asset_id: "spectra", title: "Depth series", shape: [40, 1015], warnings: [warning] },
      ],
    });

    const vm = wrapper.vm as unknown as DataContentVm;
    await vm.onInspectFile(mocks.dataStore.experimentFiles[0], { updateRoute: false });
    await flushPromises();

    const notice = wrapper.find('[aria-label="Scientific import warning"]');
    expect(notice.exists()).toBe(true);
    expect(notice.text()).toContain(warning);
  });

  it("requires an explicit choice for a persisted file with multiple scientific assets", async () => {
    const warning = "OPUS AB block was refused because it is not independently qualified";
    const wrapper = mountDataContent();
    await flushPromises();
    mocks.dataStore.fetchFileAssets.mockResolvedValueOnce({
      format_id: "opus",
      variant: "multi-block",
      parser_id: "spectrasherpa.native.opus",
      parser_version: "1",
      source_sha256: "c".repeat(64),
      assets: [
        { asset_id: "sm", title: "Sample spectrum", shape: [1, 1024], warnings: [warning] },
        { asset_id: "igsm", title: "Sample interferogram", shape: [1, 2048], warnings: [] },
      ],
    });
    mocks.dataStore.inspectFile.mockClear();
    mocks.dataStore.clearInspection.mockClear();

    const vm = wrapper.vm as unknown as DataContentVm;
    await vm.onInspectFile(mocks.dataStore.experimentFiles[0], { updateRoute: false });
    await flushPromises();

    expect(vm.pendingInspection).toMatchObject({
      kind: "file",
      experimentId: 11,
      file: { id: 22, file_path: "raw/wine.csv" },
    });
    expect(vm.inspectionAssets.map((asset) => asset.asset_id)).toEqual(["sm", "igsm"]);
    expect(mocks.dataStore.clearInspection).toHaveBeenCalledOnce();
    expect(mocks.dataStore.inspectFile).not.toHaveBeenCalled();
    expect(wrapper.get('[aria-label="Scientific import warning"]').text()).toContain(warning);

    vm.inspectionAssetId = "igsm";
    await vm.onInspectionAssetChange();

    expect(mocks.dataStore.inspectFile).toHaveBeenCalledWith(22, "raw/wine.csv", 11, "igsm");
  });

  it("renders staged-upload scientific import warnings", async () => {
    const warning = "WiRE-derived MAP analysis layers were not imported";
    mocks.dataStore.stageUploadBatch.mockResolvedValueOnce({
      file_count: 1,
      total_size_bytes: 4096,
      refused_count: 0,
      refusals: [],
      files: [
        {
          staging_id: "wdf-stage",
          filename: "depth.wdf",
          size_bytes: 4096,
          format_id: "wdf",
          variant: "series",
          assets: [
            { asset_id: "spectra", title: "Depth series", shape: [40, 1015], warnings: [warning] },
          ],
        },
      ],
    });
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    await vm.onFileSelect({ files: [new File(["wdf"], "depth.wdf")] });
    await flushPromises();

    const notice = wrapper.find('[aria-label="Scientific import warning"]');
    expect(notice.exists()).toBe(true);
    expect(notice.text()).toContain(warning);
  });

  it("keeps admitted files and displays an exact refusal receipt for the rest", async () => {
    mocks.dataStore.stageUploadBatch.mockResolvedValueOnce({
      file_count: 1,
      total_size_bytes: 42,
      refused_count: 2,
      refusals: [
        { source_name: "mixed.zip:notes.pdf", reason: "Unsupported file type" },
        { source_name: "mixed.zip:broken.npy", reason: "Could not inspect scientific assets" },
      ],
      files: [
        {
          staging_id: "valid-stage",
          filename: "valid.csv",
          size_bytes: 42,
          format_id: "csv",
          variant: "headered-matrix",
          assets: [],
        },
      ],
    });
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    await vm.onFileSelect({ files: [new File(["zip"], "mixed.zip")] });
    await flushPromises();

    expect(vm.stagedUploadMembers.map((member) => member.filename)).toEqual(["valid.csv"]);
    const receipt = wrapper.get(".upload-refusals");
    expect(receipt.text()).toContain("2 sources not loaded");
    expect(receipt.text()).toContain("mixed.zip:notes.pdf");
    expect(receipt.text()).toContain("Unsupported file type");
    expect(mocks.toastAdd).toHaveBeenCalledWith({
      severity: "warn",
      summary: "Sources Partly Ready",
      detail: "1 loaded; 2 not loaded. Review the receipt below.",
      life: 5000,
    });
  });

  it("adds selected reference datasets to a newly created project dataset", async () => {
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.selectedRefDatasets.add("sklearn::iris");
    vm.importDatasetName = "Iris demo";

    await vm.onImportSelectedDatasets();
    await flushPromises();

    expect(mocks.dataStore.createExperiment).toHaveBeenCalledWith("Iris demo", undefined, 3);
    expect(mocks.dataStore.selectExperiment).toHaveBeenCalledWith(33);
    expect(mocks.dataStore.importReferenceDatasets).toHaveBeenCalledWith(33, [
      { source: "sklearn", name: "iris", overrides: null },
    ]);
    expect(vm.selectedRefDatasets.size).toBe(0);
    expect(vm.importDatasetName).toBe("");
  });

  it("selects one reference at a time and previews the checked dataset", async () => {
    const lavender: ReferenceDatasetOption = {
      source: "builtin",
      name: "lavender-essential-oil-v1",
      label: "Lavender",
    };
    const iris: ReferenceDatasetOption = {
      source: "sklearn",
      name: "iris",
      label: "Iris",
    };
    mocks.dataStore.referenceCatalog.builtin = [lavender];
    mocks.dataStore.referenceCatalog.sklearn = [iris];
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;

    vm.toggleRefDataset(lavender);
    expect(Array.from(vm.selectedRefDatasets)).toEqual(["builtin::lavender-essential-oil-v1"]);
    expect(vm.previewRefKey).toBe("builtin::lavender-essential-oil-v1");

    vm.toggleRefDataset(iris);
    expect(Array.from(vm.selectedRefDatasets)).toEqual(["sklearn::iris"]);
    expect(vm.previewRefKey).toBe("sklearn::iris");

    vm.toggleRefDataset(iris);
    expect(vm.selectedRefDatasets.size).toBe(0);
    expect(vm.previewRefKey).toBeNull();
  });

  it("removes the newly created My Dataset when reference import fails", async () => {
    mocks.dataStore.referenceCatalog.sklearn = [{ source: "sklearn", name: "iris", label: "Iris" }];
    mocks.dataStore.importReferenceDatasets.mockRejectedValueOnce(
      Object.assign(new Error("preview authority failed"), { response: { status: 403 } }),
    );
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;
    vm.selectedRefDatasets.add("sklearn::iris");

    await vm.onImportSelectedDatasets();

    expect(mocks.dataStore.deleteExperiment).toHaveBeenCalledWith(33);
    expect(mocks.toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "error", summary: "Import Failed" }),
    );
  });

  it("admits the Dashboard starter and preserves its template hand-off", async () => {
    mocks.dataStore.referenceCatalog.sklearn = [{ source: "sklearn", name: "iris", label: "Iris" }];
    window.sessionStorage.setItem("sherpa:data-entry-mode", "analysis-starter");
    window.sessionStorage.setItem("sherpa:data-entry-project-id", "3");
    window.sessionStorage.setItem(
      "sherpa:data-entry-dataset-intent",
      JSON.stringify({
        schema_version: "spectra-analysis-starter-dataset-intent/1",
        project_id: 3,
        dataset_id: "sklearn:iris",
        source: "sklearn",
        name: "iris",
        label: "Iris",
        template_slug: "pca",
      }),
    );
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    // Entering Data from New Analysis admits bundled/catalog data instead of
    // leaving the project with a zero-file placeholder. The intent remains
    // available to Workflow, but records the admitted experiment.
    expect(Array.from(vm.selectedRefDatasets)).toEqual([]);
    expect(mocks.dataStore.createExperiment).toHaveBeenCalledWith("Iris", undefined, 3);
    expect(mocks.dataStore.importReferenceDatasets).toHaveBeenCalledWith(33, [
      { source: "sklearn", name: "iris", overrides: null },
    ]);
    expect(vm.importDatasetName).toBe("");

    expect(window.sessionStorage.getItem("sherpa:data-entry-mode")).toBe("analysis-starter");
    expect(
      JSON.parse(window.sessionStorage.getItem("sherpa:data-entry-dataset-intent") || "{}"),
    ).toMatchObject({
      template_slug: "pca",
      imported_experiment_id: 33,
    });
  });

  it.each([false, true])(
    "explains provider acquisition without disabling local import (pro=%s)",
    async (pro) => {
      mocks.pro = pro;
      mocks.dataStore.referenceCatalog.registered = [
        {
          source: "registered",
          name: "corn",
          label: "Eigenvector Corn",
          provider_page: "https://eigenvector.com/resources/data-sets/",
        },
      ];
      mocks.dataStore.referenceCatalog.eigenvector = [
        {
          source: "eigenvector",
          name: "diesel",
          label: "Diesel NIR",
          requires_runtime_download: true,
          download_page: "https://eigenvector.com/resources/data-sets/",
        },
      ];
      const wrapper = mountDataContent();
      await flushPromises();
      expect(wrapper.get(".reference-acquisition-help").text()).toContain(
        "not bundled or downloaded automatically",
      );
      expect(wrapper.get(".reference-acquisition-help").text()).toContain("works offline");
      const providerLinks = wrapper.findAll('a[aria-label$="provider page (opens in a new tab)"]');
      expect(providerLinks).toHaveLength(2);
      for (const link of providerLinks) {
        expect(link.attributes("href")).toBe("https://eigenvector.com/resources/data-sets/");
        expect(link.attributes("rel")).toBe("noopener noreferrer");
      }
      const importButton = wrapper
        .findAll("button")
        .find((button) => button.text() === "Import downloaded file")!;
      expect(importButton.attributes("disabled")).toBeUndefined();
      expect(mocks.dataStore.exploreCatalogDataset).not.toHaveBeenCalled();
      wrapper.unmount();
    },
  );

  it("opens the exact provider package selected by an analysis starter", async () => {
    mocks.dataStore.referenceCatalog.registered = [
      {
        source: "registered",
        name: "public-corn-m5-moisture-v1",
        label: "Eigenvector Corn M5",
        data_modality: "spectra",
        dataset_package: {
          package_id: "eigenvector-corn-v1",
          package_title: "Eigenvector Corn",
          package_description: "Three aligned NIR instrument views.",
          assembly_mode: "homogeneous_collection",
          artifact_ids: ["eigenvector-corn-archive-v1"],
          view_id: "corn-m5",
          view_label: "M5",
          instrument: "M5",
          cohort: "corn-80",
          initially_selected: true,
          relations: [],
        },
      },
    ];
    window.sessionStorage.setItem("sherpa:data-entry-mode", "analysis-starter");
    window.sessionStorage.setItem("sherpa:data-entry-project-id", "3");
    window.sessionStorage.setItem(
      "sherpa:data-entry-dataset-intent",
      JSON.stringify({
        schema_version: "spectra-analysis-starter-dataset-intent/1",
        project_id: 3,
        dataset_id: "registered:public-corn-m5-moisture-v1",
        source: "registered",
        name: "public-corn-m5-moisture-v1",
        label: "Eigenvector Corn M5",
        template_slug: "pca",
      }),
    );

    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;

    expect(vm.selectedRefDatasets.size).toBe(0);
    expect(vm.previewRefKey).toBe("registered::eigenvector-corn-v1");
    expect(vm.registeredCollapsed).toBe(false);
    const preview = wrapper.getComponent({ name: "DatasetSourcePreview" });
    expect(preview.props("title")).toBe("Eigenvector Corn M5");
    expect(preview.props("sourceRef")).toBeNull();
    expect(preview.props("acquisitionRequired")).toBe(true);
  });

  it("adds the built-in Lavender corpus through the reference selection flow", async () => {
    const lavender: ReferenceDatasetOption = {
      source: "builtin",
      name: "lavender-essential-oil-v1",
      dataset_id: "builtin:lavender-essential-oil-v1",
      label: "Lavender Essential Oil FTIR Corpus v1",
      description:
        "Thirty-three FTIR spectra in three acquisition blocks with parallel specimen, botanical-group, and reported-authenticity labels.",
      technical_summary: "33 FTIR spectra; specimen, botanical group, and authenticity labels.",
    };
    mocks.dataStore.referenceCatalog.builtin = [lavender];
    mocks.dataStore.importReferenceDatasets.mockResolvedValueOnce({
      imported: 33,
      experiment_id: 33,
      files: [
        {
          id: 44,
          experiment_id: 33,
          file_path: "raw/lavender-001.spa",
          file_size_bytes: 4096,
          stage: "raw",
          created_at: "2026-05-02T00:00:00Z",
        },
      ],
      initial_file_ids: [],
    });
    const wrapper = mountDataContent();
    await flushPromises();

    const text = wrapper.text();
    expect(text).toContain("Lavender Essential Oil FTIR Corpus v1");
    expect(text).toContain("Add to My Dataset");
    expect(text).not.toContain("Distributed with Sherpa under its stated dataset license");

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.selectedRefDatasets.add("builtin::lavender-essential-oil-v1");
    await vm.onImportSelectedDatasets();
    await flushPromises();

    expect(mocks.dataStore.createExperiment).toHaveBeenCalledWith(
      "Lavender Essential Oil FTIR Corpus v1",
      undefined,
      3,
    );
    expect(mocks.dataStore.importReferenceDatasets).toHaveBeenCalledWith(33, [
      { source: "builtin", name: "lavender-essential-oil-v1", overrides: null },
    ]);
    expect(mocks.dataStore.selectExperiment).toHaveBeenCalledWith(33);
    expect(wrapper.get('[data-testid="data-tabs"]').attributes("data-active-index")).toBe("5");
    expect(mocks.toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Import Complete" }),
    );
  });

  it("opens the existing Lavender dataset and removes the duplicate empty dataset", async () => {
    const lavender: ReferenceDatasetOption = {
      source: "builtin",
      name: "lavender-essential-oil-v1",
      label: "Lavender Essential Oil FTIR Corpus v1",
    };
    mocks.dataStore.referenceCatalog.builtin = [lavender];
    mocks.dataStore.importReferenceDatasets.mockResolvedValueOnce({
      imported: 0,
      experiment_id: 19,
      reused_existing: true,
      files: [],
    });
    const wrapper = mountDataContent();
    await flushPromises();
    const vm = wrapper.vm as unknown as DataContentVm;
    vm.selectedRefDatasets.add("builtin::lavender-essential-oil-v1");

    await vm.onImportSelectedDatasets();
    await flushPromises();

    expect(mocks.dataStore.deleteExperiment).toHaveBeenCalledWith(33);
    expect(mocks.dataStore.selectExperiment).toHaveBeenCalledWith(19);
    expect(mocks.toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "success",
        detail: "This reference is already in My Dataset. The existing dataset is open.",
      }),
    );
  });

  it("hides empty reference catalog sections", async () => {
    mocks.dataStore.referenceCatalog.builtin = [
      {
        source: "builtin",
        name: "lavender-essential-oil-v1",
        label: "Lavender Essential Oil FTIR Corpus v1",
      },
    ];

    const wrapper = mountDataContent();
    await flushPromises();

    const text = wrapper.text();
    expect(text).toContain("Lavender Essential Oil FTIR Corpus v1");
    expect(text).not.toContain("Spectra Scientific Synthetic Benchmarks");
    expect(text).not.toContain("User-acquired Eigenvector datasets");
    expect(text).not.toContain("scikit-learn datasets");
  });

  it("surfaces legacy catalog entries with honest local-file and bundled admission paths", async () => {
    mocks.dataStore.referenceCatalog = {
      builtin: [{ source: "builtin", name: "lavender", label: "Lavender" }],
      registered: [{ source: "registered", name: "corn", label: "Eigenvector Corn" }],
      synthetic: [{ source: "synthetic", name: "blend", label: "Synthetic Blend" }],
      eigenvector: [
        {
          source: "eigenvector",
          name: "legacy",
          label: "Legacy Eigenvector",
          requires_runtime_download: true,
        },
      ],
      oes: [{ source: "oes", name: "legacy-oes", label: "Legacy OES" }],
      sklearn: [{ source: "sklearn", name: "iris", label: "Iris" }],
    };
    const wrapper = mountDataContent();
    await flushPromises();

    const text = wrapper.text();
    const builtInIndex = text.indexOf("Built-in reference data");
    const syntheticIndex = text.indexOf("Spectra Scientific Synthetic Benchmarks");
    const sklearnIndex = text.indexOf("scikit-learn datasets");
    const acquiredIndex = text.indexOf("User-acquired Eigenvector datasets");
    const additionalIndex = text.indexOf("Additional scientific source catalog");
    expect(builtInIndex).toBeGreaterThanOrEqual(0);
    expect(syntheticIndex).toBeGreaterThan(builtInIndex);
    expect(sklearnIndex).toBeGreaterThan(syntheticIndex);
    expect(acquiredIndex).toBeGreaterThan(sklearnIndex);
    expect(additionalIndex).toBeGreaterThan(acquiredIndex);

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.legacyCollapsed = false;
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain("Legacy Eigenvector");
    expect(wrapper.text()).toContain("Provider file required");
    expect(wrapper.text()).toContain("Legacy OES");
    expect(wrapper.text()).toContain("available without network egress");
  });

  it("uses blue info count tags across reference catalog sections", async () => {
    mocks.dataStore.referenceCatalog = {
      builtin: [{ source: "builtin", name: "lavender", label: "Lavender" }],
      registered: [{ source: "registered", name: "corn", label: "Eigenvector Corn" }],
      synthetic: [{ source: "synthetic", name: "blend", label: "Synthetic Blend" }],
      eigenvector: [],
      oes: [],
      sklearn: [{ source: "sklearn", name: "iris", label: "Iris" }],
    };

    const wrapper = mountDataContent();
    await flushPromises();

    const referenceHeaders = wrapper.findAll(".ref-panel-header");
    expect(referenceHeaders).toHaveLength(4);
    expect(
      referenceHeaders.every(
        (header) => header.get(".tag-stub").attributes("data-severity") === "info",
      ),
    ).toBe(true);
  });

  it("keeps qualified hyperspectral references visible and imports a registered file", async () => {
    const registered = {
      source: "registered",
      name: "public-corn-m5-moisture-v1",
      label: "Eigenvector Corn M5 moisture regression",
      technique: "NIR",
      description: "Corn calibration-transfer and regression reference.",
      technical_summary:
        "M5 instrument view of 80 matched corn samples: 700 NIR wavelength variables (nm); continuous Moisture target.",
      provider: "Eigenvector Research",
      provider_page: "https://eigenvector.com/resources/data-sets/",
      download_url: "https://eigenvector.com/wp-content/uploads/2019/06/corn.mat_.zip",
      attribution: "Eigenvector Research Corn dataset.",
      no_endorsement: "Eigenvector Research does not endorse Spectra Sherpa.",
      admission: "exact_user_acquired_file",
    };
    mocks.dataStore.referenceCatalog.registered = [
      registered,
      {
        source: "registered",
        name: "public-art-image-paint-demo-v1",
        label: "Art Image Data A — Paint Demo",
        technique: "Hyperspectral image",
        data_role: "X_hsi",
        data_modality: "hsi",
        description: "Hyperspectral paint-image data for multivariate image analysis.",
        technical_summary:
          "Art Image Data A contains 19,200 observations × 207 spectral variables as hyperspectral-image data, with no declared target.",
        provider: "Eigenvector Research",
      },
    ];
    mocks.dataStore.importRegisteredReference.mockResolvedValue({ imported: 1 });
    const wrapper = mountDataContent();
    await flushPromises();

    const text = wrapper.text();
    expect(text).toContain("Import downloaded file");
    expect(text).toContain("M5 instrument view of 80 matched corn samples");
    expect(text).toContain("Art Image Data A");
    expect(text).not.toContain("Download from Eigenvector");
    expect(
      wrapper
        .find('a[href="https://eigenvector.com/wp-content/uploads/2019/06/corn.mat_.zip"]')
        .exists(),
    ).toBe(false);

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.selectRegisteredReferenceFile(registered);
    const file = new File(["exact-provider-archive"], "renamed.zip", {
      type: "application/zip",
    });
    await vm.onRegisteredReferenceSelection({
      target: { files: [file], value: "renamed.zip" },
    } as unknown as Event);
    await flushPromises();

    expect(mocks.dataStore.createExperiment).toHaveBeenCalledWith(
      "Eigenvector Corn M5 moisture regression",
      "Corn calibration-transfer and regression reference.",
      3,
      {
        source_kind: "user_acquired_registered_reference",
        reference_projection_id: "public-corn-m5-moisture-v1",
        provider: "Eigenvector Research",
      },
    );
    expect(mocks.dataStore.importRegisteredReference).toHaveBeenCalledWith(
      33,
      { projectionId: "public-corn-m5-moisture-v1" },
      [file],
    );
    expect(mocks.dataStore.selectExperiment).toHaveBeenCalledWith(33);
    expect(mocks.toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ severity: "success", summary: "Reference Verified" }),
    );
  });

  it("presents one Corn package, imports all instrument views, and starts with M5 selected", async () => {
    const relations = [
      {
        relation_id: "corn-instrument-views",
        relation_type: "same_specimens_aligned",
        view_ids: ["corn-m5", "corn-mp5", "corn-mp6"],
        row_identity: "source_row_index",
      },
    ];
    const packageBase = {
      package_id: "eigenvector-corn-v1",
      package_title: "Eigenvector Corn",
      package_description: "The same 80 corn specimens measured on three NIR instruments.",
      assembly_mode: "homogeneous_collection",
      artifact_ids: ["eigenvector-corn-archive-v1"],
      cohort: "corn-80",
      relations,
    };
    const registered = [
      ["public-corn-m5-moisture-v1", "corn-m5", "M5", true],
      ["public-corn-mp5-moisture-v1", "corn-mp5", "MP5", false],
      ["public-corn-mp6-moisture-v1", "corn-mp6", "MP6", false],
    ].map(([name, view_id, instrument, initially_selected]) => ({
      source: "registered",
      name,
      label: `Eigenvector Corn ${instrument}`,
      description: "Corn calibration-transfer reference.",
      provider: "Eigenvector Research",
      data_modality: "spectra",
      dataset_package: {
        ...packageBase,
        view_id,
        view_label: instrument,
        instrument,
        initially_selected,
      },
    }));
    mocks.dataStore.referenceCatalog.registered = registered;
    mocks.dataStore.importRegisteredReference.mockResolvedValueOnce({
      imported: 3,
      files: [
        { id: 81, file_path: "raw/corn-m5.mat", stage: "raw" },
        { id: 82, file_path: "raw/corn-mp5.mat", stage: "raw" },
        { id: 83, file_path: "raw/corn-mp6.mat", stage: "raw" },
      ],
      experiment_id: 33,
      reused_existing: false,
      initial_file_ids: [81],
    });
    vi.mocked(api.post).mockResolvedValue({
      data: {
        data_role: "X_spectra",
        n_samples: 80,
        n_features: 700,
        data: [[1, 2]],
        metadata: { is_spectra: true },
      },
    } as never);
    const wrapper = mountDataContent();
    await flushPromises();

    expect(wrapper.text().match(/Eigenvector Corn/g)?.length).toBe(1);
    expect(wrapper.text()).toContain("M5, MP5, and MP6");

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.selectRegisteredReferenceFile(
      (wrapper.vm as unknown as { visibleRegisteredReferences: ReferenceDatasetOption[] })
        .visibleRegisteredReferences[0],
    );
    const file = new File(["exact-corn-archive"], "corn.zip", { type: "application/zip" });
    await vm.onRegisteredReferenceSelection({
      target: { files: [file], value: "corn.zip" },
    } as unknown as Event);
    await flushPromises();

    expect(mocks.dataStore.createExperiment).toHaveBeenCalledWith(
      "Eigenvector Corn",
      "The same 80 corn specimens measured on three NIR instruments.",
      3,
      {
        source_kind: "user_acquired_registered_reference",
        reference_package_id: "eigenvector-corn-v1",
        provider: "Eigenvector Research",
      },
    );
    expect(mocks.dataStore.importRegisteredReference).toHaveBeenCalledWith(
      33,
      { packageId: "eigenvector-corn-v1" },
      [file],
    );
    expect(
      (wrapper.vm as unknown as { plotFileSelections: Record<number, unknown> })
        .plotFileSelections[33],
    ).toEqual([{ id: 81, file_path: "raw/corn-m5.mat", stage: "raw" }]);
  });

  it("presents Diesel as one three-cohort package with density annotations", async () => {
    const packageBase = {
      package_id: "eigenvector-diesel-d4052-v1",
      package_title: "Eigenvector Diesel D4052",
      package_description: "Three Diesel NIR cohorts with D4052 density results.",
      assembly_mode: "homogeneous_collection",
      artifact_ids: ["eigenvector-diesel-d4052-archive-v1"],
      relations: [],
    };
    mocks.dataStore.referenceCatalog.registered = [
      ["public-diesel-high-level-d4052-v1", "diesel-high-level", "High-level set", false],
      ["public-diesel-d4052-v1", "diesel-low-level-a", "Low-level set A", true],
      ["public-diesel-low-level-b-d4052-v1", "diesel-low-level-b", "Low-level set B", false],
    ].map(([name, view_id, view_label, initially_selected]) => ({
      source: "registered",
      name,
      label: `Diesel — ${view_label}`,
      description: "Diesel NIR reference.",
      provider: "Eigenvector Research",
      data_modality: "spectra",
      dataset_package: {
        ...packageBase,
        view_id,
        view_label,
        instrument: view_label,
        initially_selected,
      },
    }));
    mocks.dataStore.importRegisteredReference.mockResolvedValueOnce({
      imported: 3,
      files: [
        { id: 84, file_path: "raw/diesel-high-level.mat", stage: "raw" },
        { id: 85, file_path: "raw/diesel-low-level-a.mat", stage: "raw" },
        { id: 86, file_path: "raw/diesel-low-level-b.mat", stage: "raw" },
      ],
      experiment_id: 33,
      reused_existing: false,
      initial_file_ids: [85],
    });
    const wrapper = mountDataContent();
    await flushPromises();

    expect(wrapper.text().match(/Eigenvector Diesel D4052/g)?.length).toBe(1);
    expect(wrapper.text()).toContain("122 low-level A, 121 low-level B, and 20 high-level");
    const vm = wrapper.vm as unknown as DataContentVm;
    vm.selectRegisteredReferenceFile(
      (wrapper.vm as unknown as { visibleRegisteredReferences: ReferenceDatasetOption[] })
        .visibleRegisteredReferences[0],
    );
    const file = new File(["exact-diesel-archive"], "diesel.zip", {
      type: "application/zip",
    });
    await vm.onRegisteredReferenceSelection({
      target: { files: [file], value: "diesel.zip" },
    } as unknown as Event);
    await flushPromises();

    expect(mocks.dataStore.importRegisteredReference).toHaveBeenCalledWith(
      33,
      { packageId: "eigenvector-diesel-d4052-v1" },
      [file],
    );
    expect(
      (wrapper.vm as unknown as { plotFileSelections: Record<number, unknown> })
        .plotFileSelections[33],
    ).toEqual([{ id: 85, file_path: "raw/diesel-low-level-a.mat", stage: "raw" }]);
  });

  it("imports the three Metal Etch provider archives as one package with OES selected", async () => {
    const packageBase = {
      package_id: "eigenvector-metal-etch-v1",
      package_title: "Eigenvector Metal Etch",
      package_description: "Three complementary LAM 9600 process views.",
      assembly_mode: "heterogeneous_views",
      artifact_ids: [
        "eigenvector-metal-etch-machine-archive-v1",
        "eigenvector-metal-etch-oes-archive-v1",
        "eigenvector-metal-etch-rfm-archive-v1",
      ],
      cohort: "metal-etch",
      relations: [],
    };
    mocks.dataStore.referenceCatalog.registered = [
      ["public-metal-etch-machine-v1", "metal-etch-machine", "Machine sensors", false],
      ["public-metal-etch-oes-v1", "metal-etch-oes", "Optical emission spectra", true],
      ["public-metal-etch-rfm-v1", "metal-etch-rfm", "RF-monitor variables", false],
    ].map(([name, view_id, view_label, initially_selected]) => ({
      source: "registered",
      name,
      label: `Metal Etch — ${view_label}`,
      description: "Metal Etch process reference.",
      provider: "Eigenvector Research",
      data_modality: "features",
      dataset_package: {
        ...packageBase,
        view_id,
        view_label,
        instrument: view_label,
        initially_selected,
      },
    }));
    mocks.dataStore.importRegisteredReference.mockResolvedValueOnce({
      imported: 3,
      files: [
        { id: 91, file_path: "raw/metal-etch-machine.mat", stage: "raw" },
        { id: 92, file_path: "raw/metal-etch-oes.mat", stage: "raw" },
        { id: 93, file_path: "raw/metal-etch-rfm.mat", stage: "raw" },
      ],
      experiment_id: 33,
      reused_existing: false,
      initial_file_ids: [92],
    });
    const wrapper = mountDataContent();
    await flushPromises();

    expect(wrapper.text().match(/Eigenvector Metal Etch/g)?.length).toBe(1);
    expect(wrapper.text()).toContain("21 machine-sensor variables");
    const vm = wrapper.vm as unknown as DataContentVm;
    vm.selectRegisteredReferenceFile(
      (wrapper.vm as unknown as { visibleRegisteredReferences: ReferenceDatasetOption[] })
        .visibleRegisteredReferences[0],
    );
    const files = [
      new File(["machine"], "machine.zip"),
      new File(["oes"], "oes.zip"),
      new File(["rfm"], "rfm.zip"),
    ];
    await vm.onRegisteredReferenceSelection({ target: { files, value: "" } } as unknown as Event);
    await flushPromises();

    expect(mocks.dataStore.importRegisteredReference).toHaveBeenCalledWith(
      33,
      { packageId: "eigenvector-metal-etch-v1" },
      files,
    );
    expect(
      (wrapper.vm as unknown as { plotFileSelections: Record<number, unknown> })
        .plotFileSelections[33],
    ).toEqual([{ id: 92, file_path: "raw/metal-etch-oes.mat", stage: "raw" }]);
  });

  it("opens an existing exact registered reference and removes the duplicate empty dataset", async () => {
    const registered = {
      source: "registered",
      name: "public-corn-m5-moisture-v1",
      label: "Eigenvector Corn M5 moisture regression",
      provider: "Eigenvector Research",
    };
    mocks.dataStore.referenceCatalog.registered = [registered];
    mocks.dataStore.importRegisteredReference.mockResolvedValueOnce({
      imported: 0,
      files: [{ id: 71 }],
      experiment_id: 19,
      reused_existing: true,
    });
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.selectRegisteredReferenceFile(registered);
    await vm.onRegisteredReferenceSelection({
      target: { files: [new File(["exact"], "corn.zip")], value: "corn.zip" },
    } as unknown as Event);
    await flushPromises();

    expect(mocks.dataStore.deleteExperiment).toHaveBeenCalledWith(33);
    expect(mocks.dataStore.selectExperiment).toHaveBeenCalledWith(19);
    expect(mocks.toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "success",
        detail:
          "Eigenvector Corn M5 moisture regression was already verified. The existing dataset is open in My Dataset.",
      }),
    );
  });

  it("removes the empty dataset and shows the exact refusal when registry verification fails", async () => {
    const registered = {
      source: "registered",
      name: "public-corn-m5-moisture-v1",
      label: "Eigenvector Corn M5 moisture regression",
      provider: "Eigenvector Research",
    };
    mocks.dataStore.referenceCatalog.registered = [registered];
    mocks.dataStore.importRegisteredReference.mockRejectedValueOnce(
      Object.assign(new Error("This file does not match the registered reference file. No data was retained."), { response: { status: 422 } }),
    );
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.selectRegisteredReferenceFile(registered);
    await vm.onRegisteredReferenceSelection({
      target: { files: [new File(["wrong"], "corn.zip")], value: "corn.zip" },
    } as unknown as Event);
    await flushPromises();

    expect(mocks.dataStore.deleteExperiment).toHaveBeenCalledWith(33);
    expect(mocks.toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "error",
        summary: "Reference Refused",
        detail: "This file does not match the registered reference file. No data was retained.",
      }),
    );
  });

  it.each(["refresh", "unknown outcome"])("preserves registered data after %s failure", async (failure) => {
    const registered = { source: "registered", name: "public-corn-m5-moisture-v1", label: "Corn", provider: "Eigenvector Research" };
    mocks.dataStore.referenceCatalog.registered = [registered];
    const wrapper = mountDataContent();
    await flushPromises();
    if (failure === "refresh") {
      mocks.dataStore.importRegisteredReference.mockResolvedValueOnce({ imported: 1, experiment_id: 33, files: [], initial_file_ids: [] });
      mocks.dataStore.selectExperiment.mockRejectedValueOnce(new Error("Display refresh failed"));
    } else {
      mocks.dataStore.importRegisteredReference.mockRejectedValueOnce(new Error("Connection lost after submission"));
    }
    const vm = wrapper.vm as unknown as DataContentVm;
    vm.selectRegisteredReferenceFile(registered);
    await vm.onRegisteredReferenceSelection({ target: { files: [new File(["exact"], "corn.zip")], value: "" } } as unknown as Event);
    expect(mocks.dataStore.deleteExperiment).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("lists catalog source files without parsing archives", async () => {
    mocks.route.query = { tab: "import" };
    mocks.dataStore.referenceCatalog.sklearn = [
      {
        source: "sklearn",
        name: "iris",
        label: "Iris",
        files: ["sklearn/iris.csv", "sklearn/iris-target.csv"],
        file_path: "sklearn/iris.csv",
      },
    ];
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.previewRefKey = "sklearn::iris";
    await flushPromises();

    const filesPanel = wrapper.find(".source-files");
    expect(filesPanel.exists()).toBe(true);
    expect(filesPanel.find(".section-toggle").attributes("aria-expanded")).toBe("true");
    expect(filesPanel.text()).toContain("2 files");
    expect(filesPanel.text()).toContain("iris.csv");
    expect(filesPanel.text()).toContain("iris-target.csv");
    expect(filesPanel.findAll(".preview-file-extension").map((node) => node.text())).toEqual([
      "csv",
      "csv",
    ]);
    expect(wrapper.find(".source-plot").text()).toContain("Graph");
  });

  it("autosaves and restores Import and Library draft selections for the active project", async () => {
    mocks.dataStore.referenceCatalog.sklearn = [
      {
        source: "sklearn",
        name: "iris",
        label: "Iris",
        description: "Iris reference data",
      },
    ];
    const first = mountDataContent();
    await flushPromises();

    const firstVm = first.vm as unknown as DataContentVm;
    firstVm.selectedRefDatasets.add("sklearn::iris");
    firstVm.previewRefKey = "sklearn::iris";
    firstVm.refOverrides["sklearn::iris"] = { title: "Iris edited", x_title: "features" };
    firstVm.importDatasetName = "Saved import basket";
    firstVm.librarySource = "hitran";
    firstVm.librarySearch = "water";
    firstVm.libraryRangeMode = "common";
    firstVm.libraryResolutionCm1 = 0.5;
    firstVm.libraryWavenumberMin = 600;
    firstVm.libraryWavenumberMax = 3300;
    firstVm.libraryTemperatureK = 310;
    firstVm.libraryPressureAtm = 0.8;
    firstVm.selectedLibraryKeys.add("hitran:1");
    firstVm.selectedLibraryRows["hitran:1"] = {
      key: "hitran:1",
      source: "hitran",
      component_id: "hitran:1",
      compound_name: "Water",
      cas_number: "",
      resolution: "0.5 cm^-1",
      source_label: "HITRAN LBL",
      frozen_settings: {
        component_id: "hitran:1",
        resolution_cm1: 0.5,
        wavenumber_min: 600,
        wavenumber_max: 3300,
        temperature_k: 310,
        pressure_atm: 0.8,
      },
    };
    firstVm.libraryDatasetName = "Library_saved";
    firstVm.persistDataDraftNow();
    first.unmount();

    const restored = mountDataContent();
    await flushPromises();
    const restoredVm = restored.vm as unknown as DataContentVm;

    expect(restoredVm.selectedRefDatasets.has("sklearn::iris")).toBe(true);
    expect(restoredVm.previewRefKey).toBe("sklearn::iris");
    expect(restoredVm.refOverrides["sklearn::iris"]).toEqual({
      title: "Iris edited",
      x_title: "features",
    });
    expect(restoredVm.importDatasetName).toBe("Saved import basket");
    expect(restoredVm.librarySource).toBe("hitran");
    expect(restoredVm.librarySearch).toBe("water");
    expect(restoredVm.libraryRangeMode).toBe("common");
    expect(restoredVm.libraryResolutionCm1).toBe(0.5);
    expect(restoredVm.libraryWavenumberMin).toBe(600);
    expect(restoredVm.libraryWavenumberMax).toBe(3300);
    expect(restoredVm.libraryTemperatureK).toBe(310);
    expect(restoredVm.libraryPressureAtm).toBe(0.8);
    expect(restoredVm.selectedLibraryKeys.has("hitran:1")).toBe(true);
    expect(restoredVm.selectedLibraryRows["hitran:1"]?.compound_name).toBe("Water");
    expect(restoredVm.libraryDatasetName).toBe("Library_saved");
  });

  it("adds selected library spectra to a newly created project dataset", async () => {
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.selectedLibraryKeys.add("nist:101");
    vm.selectedLibraryRows["nist:101"] = {
      key: "nist:101",
      source: "nist",
      id: 101,
      compound_name: "Acetone",
      cas_number: "67-64-1",
      resolution: "low",
      file_path: "nist_library/acetone.jdx",
    };
    vm.libraryDatasetName = "Acetone reference";

    await vm.onImportSelectedLibraryDatasets();
    await flushPromises();

    expect(mocks.dataStore.createExperiment).toHaveBeenCalledWith(
      "Acetone reference",
      undefined,
      3,
      expect.objectContaining({
        builder_state: expect.objectContaining({
          kind: "library_basket",
          library: expect.objectContaining({
            source: "nist",
            range_mode: "widest",
          }),
        }),
      }),
    );
    expect(mocks.dataStore.selectExperiment).toHaveBeenCalledWith(33);
    expect(mocks.dataStore.importLibraryDatasets).toHaveBeenCalledWith(33, {
      source: "nist",
      library_ids: [101],
      component_ids: [],
      component_specs: [],
      spectra: [],
      range_mode: "widest",
      resolution_cm1: 0.1,
      wavenumber_min: 400,
      wavenumber_max: 4000,
    });
    expect(vm.selectedLibraryKeys.size).toBe(0);
    expect(vm.libraryDatasetName).toBe("");
  });

  it("adds all visible NIST library spectra to the library basket", async () => {
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;

    vm.onAddAllVisibleNistToBasket();
    await flushPromises();

    expect(vm.selectedLibraryKeys.has("nist:101")).toBe(true);
    expect(vm.selectedLibraryKeys.has("nist:102")).toBe(true);
    expect(vm.libraryDatasetName).toMatch(/^Library_\d{8}_\d{6}$/);
    expect(mocks.dataStore.createExperiment).not.toHaveBeenCalled();
    expect(mocks.dataStore.importLibraryDatasets).not.toHaveBeenCalled();
  });

  it("adds only filtered NIST library spectra to the basket after search", async () => {
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.librarySearch = "ethanol";

    vm.onAddAllVisibleNistToBasket();
    await flushPromises();

    expect(vm.selectedLibraryKeys.has("nist:101")).toBe(false);
    expect(vm.selectedLibraryKeys.has("nist:102")).toBe(true);
    expect(mocks.dataStore.importLibraryDatasets).not.toHaveBeenCalled();
  });

  it("keeps NIST library preview visible without showing grid controls", async () => {
    const wrapper = mountDataContentWithRenderedColumns();
    await flushPromises();

    expect(wrapper.find("#library-range-mode").exists()).toBe(false);

    const loadButton = wrapper.find('[data-action="library_load_spectrum"]');
    expect(loadButton.exists()).toBe(true);
    expect(loadButton.text()).toContain("Load spectrum");

    const addButton = wrapper.find('[data-action="library_add_to_basket"]');
    expect(addButton.exists()).toBe(true);
    expect(addButton.text()).toContain("Add to the Library Basket");

    const headers = wrapper
      .findAll(".rendered-column")
      .map((column) => column.attributes("data-header"));
    expect(headers.indexOf("Review / Basket")).toBeGreaterThan(-1);
    expect(headers.indexOf("Compound")).toBeGreaterThan(-1);
    expect(headers.indexOf("Review / Basket")).toBeLessThan(headers.indexOf("Compound"));
  });

  it("exposes HITRAN line-by-line temperature and pressure for spectrum loading", async () => {
    const wrapper = mountDataContentWithRenderedColumns();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.librarySource = "hitran";
    vm.libraryTemperatureK = 310;
    vm.libraryPressureAtm = 0.5;
    await flushPromises();

    expect(wrapper.find("#library-temperature").exists()).toBe(true);
    expect(wrapper.find("#library-pressure").exists()).toBe(true);

    const params = vm.librarySpectrumParams({
      source: "hitran",
      component_id: "hitran:1",
      key: "hitran:1",
    });
    expect(params.temperature_k).toBe(310);
    expect(params.pressure_atm).toBe(0.5);
  });

  it("sends HITRAN line-by-line temperature and pressure when importing to My Dataset", async () => {
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.librarySource = "hitran";
    vm.libraryTemperatureK = 293;
    vm.libraryPressureAtm = 1;
    vm.hitranLibraryRows = [
      {
        key: "hitran:2",
        source: "hitran",
        component_id: "hitran:2",
        compound_name: "Carbon dioxide",
        formula: "CO2",
        source_label: "HITRAN LBL",
      },
    ];
    vm.selectedLibraryKeys.add("hitran:2");
    vm.selectedLibraryRows["hitran:2"] = {
      ...vm.hitranLibraryRows[0],
      frozen_settings: {
        component_id: "hitran:2",
        resolution_cm1: 0.2,
        wavenumber_min: 2300,
        wavenumber_max: 2400,
        temperature_k: 315,
        pressure_atm: 0.75,
      },
    };

    await vm.onImportSelectedLibraryDatasets();
    await flushPromises();

    expect(mocks.dataStore.importLibraryDatasets).toHaveBeenCalledWith(33, {
      source: "hitran",
      library_ids: [],
      component_ids: ["hitran:2"],
      component_specs: [
        {
          component_id: "hitran:2",
          resolution_cm1: 0.2,
          wavenumber_min: 2300,
          wavenumber_max: 2400,
          temperature_k: 315,
          pressure_atm: 0.75,
        },
      ],
      spectra: [],
      range_mode: "widest",
      resolution_cm1: 0.1,
      wavenumber_min: 400,
      wavenumber_max: 4000,
      temperature_k: 293,
      pressure_atm: 1,
    });
  });

  it("sends loaded HITRAN basket spectra for direct My Dataset import", async () => {
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.librarySource = "hitran";
    vm.selectedLibraryKeys.add("hitran:2");
    vm.selectedLibraryRows["hitran:2"] = {
      key: "hitran:2",
      source: "hitran",
      component_id: "hitran:2",
      compound_name: "Carbon dioxide",
      formula: "CO2",
      source_label: "HITRAN LBL",
      frozen_settings: {
        component_id: "hitran:2",
        resolution_cm1: 1,
        wavenumber_min: 2300,
        wavenumber_max: 2302,
        temperature_k: 293,
        pressure_atm: 1,
      },
    };
    vm.librarySpectra["hitran:2"] = {
      component_id: "hitran:2",
      name: "Carbon dioxide",
      source: "hitran",
      wavenumber: [2300, 2301, 2302],
      intensity: [1e-22, 2e-22, 3e-22],
      y_quantity: "cross_section",
      y_units: "cm^2 molecule^-1",
      resolution_cm1: 1,
      apodization: "Voigt",
    };

    await vm.onImportSelectedLibraryDatasets();
    await flushPromises();

    const payload = mocks.dataStore.importLibraryDatasets.mock.calls.at(-1)?.[1];
    expect(payload.spectra).toEqual([
      {
        component_id: "hitran:2",
        name: "Carbon dioxide",
        source: "hitran",
        wavenumber: [2300, 2301, 2302],
        intensity: [1e-22, 2e-22, 3e-22],
        y_quantity: "cross_section",
        y_units: "cm^2 molecule^-1",
        resolution_cm1: 1,
        apodization: "Voigt",
      },
    ]);
  });

  it("adds uploaded files to a newly created project dataset", async () => {
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    const file = new File(["a,b\n1,2\n"], "features.csv", { type: "text/csv" });
    vm.selectedFile = file;
    vm.uploadDatasetName = "Feature table";
    vm.uploadStage = "raw";
    vm.uploadDataRole = "X_features";
    vm.uploadTargetColumn = "species";
    vm.uploadTargetType = "categorical";
    vm.stagedUploadMembers = [
      {
        staging_id: "abc123",
        filename: file.name,
        size_bytes: file.size,
        format_id: "csv",
        variant: "headered-matrix",
        assets: [],
      },
    ];
    vm.uploadOverrides.abc123 = {
      title: "features",
      data_role: "X_features",
      target_column: "species",
      target_type: "categorical",
    };
    vm.previewUploadId = "abc123";

    await vm.onUploadFile();
    await flushPromises();

    expect(mocks.dataStore.createExperiment).toHaveBeenCalledWith("Feature table", undefined, 3);
    expect(mocks.dataStore.selectExperiment).toHaveBeenCalledWith(33);
    expect(mocks.dataStore.commitStagedUploads).toHaveBeenCalledWith(33, "raw", [
      {
        staging_id: "abc123",
        overrides: {
          title: "features",
          data_role: "X_features",
          target_column: "species",
          target_type: "categorical",
        },
      },
    ]);
    expect(vm.selectedFile).toBeNull();
    expect(vm.stagedUploadMembers).toEqual([]);
    expect(vm.uploadDatasetName).toBe("");
  });

  it("does not upload when data upload is disabled by the demo contract", async () => {
    mocks.disabledCapabilities.add("data_upload");
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.selectedFile = new File(["a,b\n1,2\n"], "features.csv", { type: "text/csv" });

    await vm.onUploadFile();
    await flushPromises();

    expect(mocks.dataStore.createExperiment).not.toHaveBeenCalled();
    expect(mocks.dataStore.uploadFile).not.toHaveBeenCalled();
    expect(mocks.dataStore.commitStagedUploads).not.toHaveBeenCalled();
    expect(mocks.toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "warn",
        summary: "Upload Disabled",
      }),
    );
  });

  it("ignores the boot project resolution but resets Data state on a real project switch", async () => {
    // Regression: on slow managed-auth deployments the project resolves a few
    // seconds after mount (null -> id). If the user has already loaded
    // Contents during that gap, the currentProjectId watcher must NOT fire its
    // reset (clearActiveExperimentSelection + restoreActiveDataTab), which
    // would wipe the in-progress inspection and snap the tab back.
    mocks.projectStore.currentProjectId = null;
    const wrapper = mountDataContent();
    await flushPromises();
    mocks.dataStore.clearActiveExperimentSelection.mockClear();

    // Boot resolution (null -> id) is owned by onMounted — watcher skips it.
    mocks.projectStore.currentProjectId = 51;
    await flushPromises();
    expect(mocks.dataStore.clearActiveExperimentSelection).not.toHaveBeenCalled();

    // A genuine project switch (id -> id) must still reset Data state.
    mocks.projectStore.currentProjectId = 52;
    await flushPromises();
    expect(mocks.dataStore.clearActiveExperimentSelection).toHaveBeenCalled();

    wrapper.unmount();
  });
  it("shows scoped read failures and offers read-only retry without Refresh", async () => {
    mocks.dataStore.catalogError = "Dataset catalog could not be loaded.";
    mocks.dataStore.experimentsError = "Project datasets could not be loaded.";
    const wrapper = mountDataContent();
    await flushPromises();
    expect(wrapper.findAll('[role="alert"]').map((item) => item.text()).join(" ")).toContain("Project datasets could not be loaded");
    expect(wrapper.text()).not.toContain("No datasets yet");
    mocks.dataStore.fetchCatalog.mockClear();
    mocks.dataStore.fetchExperiments.mockClear();
    const buttons = wrapper.findAll("button");
    await buttons.find((button) => button.text() === "Retry catalog")!.trigger("click");
    await buttons.find((button) => button.text() === "Retry datasets")!.trigger("click");
    await flushPromises();
    expect(mocks.dataStore.fetchCatalog).toHaveBeenCalledExactlyOnceWith();
    expect(mocks.dataStore.fetchExperiments).toHaveBeenCalledExactlyOnceWith();
    expect(buttons.some((button) => button.text() === "Refresh")).toBe(false);
    wrapper.unmount();
  });

});
