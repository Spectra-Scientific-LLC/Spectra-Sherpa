/* eslint-disable vue/one-component-per-file */
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, reactive } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DataContent from "@/views/data/DataContent.vue";

const mocks = vi.hoisted(() => ({
  route: { query: {} as Record<string, string> },
  routerPush: vi.fn(),
  routerReplace: vi.fn(),
  toastAdd: vi.fn(),
  dataStore: {
    availableDatasets: { experiments: [], library: [], builder: [] },
    catalogLoading: false,
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
    activeFileId: null as number | null,
    activeFilePath: null as string | null,
    fileInfo: null as Record<string, unknown> | null,
    fileInfoLoading: false,
    fileInfoError: null as string | null,
    referenceCatalog: { synthetic: [], eigenvector: [], oes: [], spectrochempy: [], sklearn: [] },
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
    inspectFile: vi.fn().mockImplementation(async (fileId: number, filePath: string) => {
      mocks.dataStore.activeFileId = fileId;
      mocks.dataStore.activeFilePath = filePath;
      mocks.dataStore.fileInfo = { label: "Wine", n_samples: 178, n_features: 13 };
      return mocks.dataStore.fileInfo;
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
    deleteStagedUpload: vi.fn(),
    commitStagedUploads: vi.fn(),
    importReferenceDatasets: vi.fn(),
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

vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
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
  default: defineComponent({ name: "DataContentsPanel", template: "<div data-testid='contents-panel' />" }),
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
  },
  emits: ["click"],
  template: `
    <button type="button" :title="title" @click="$emit('click', $event)">
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
  template: "<div><slot /></div>",
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
        FileUpload: PassiveStub,
        Panel: PassiveStub,
        ProgressSpinner: PassiveStub,
        Tag: PassiveStub,
        InputSwitch: PassiveStub,
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
        FileUpload: PassiveStub,
        Panel: PassiveStub,
        ProgressSpinner: PassiveStub,
        Tag: PassiveStub,
        InputSwitch: PassiveStub,
      },
    },
  });
}

type DataContentVm = {
  selectedRefDatasets: Set<string>;
  previewRefKey: string | null;
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
  onImportSelectedLibraryDatasets: () => Promise<void>;
  onAddAllVisibleNistToBasket: () => void;
  librarySpectrumParams: (entry: Record<string, unknown>) => Record<string, string | number>;
  persistDataDraftNow: () => void;
  onUploadFile: () => Promise<void>;
};

describe("DataContent file inspection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mocks.route.query = {};
    mocks.projectStore.currentProjectId = 3;
    mocks.dataStore.activeExperimentId = 11;
    mocks.dataStore.activeFileId = null;
    mocks.dataStore.activeFilePath = null;
    mocks.dataStore.fileInfo = null;
    mocks.dataStore.referenceCatalog = { synthetic: [], eigenvector: [], oes: [], spectrochempy: [], sklearn: [] };
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
    mocks.dataStore.stageUploadFile.mockResolvedValue({
      staging_id: "abc123",
      filename: "features.csv",
      size_bytes: 12,
    });
    mocks.dataStore.commitStagedUploads.mockResolvedValue({ imported: 1, files: [44] });
    mocks.dataStore.importReferenceDatasets.mockResolvedValue({ imported: 1 });
    mocks.dataStore.importLibraryDatasets.mockResolvedValue({ imported: 1, files: [55] });
    mocks.dataStore.fetchDataMatrix.mockResolvedValue(null);
    mocks.disabledCapabilities.clear();
  });

  it("loads a file into Contents and persists the file deep link", async () => {
    const wrapper = mountDataContent();
    await flushPromises();

    const fileRows = wrapper.findAll(".file-row");
    expect(fileRows.length).toBeGreaterThan(0);

    await fileRows[fileRows.length - 1].trigger("click");
    await flushPromises();

    expect(mocks.dataStore.inspectFile).toHaveBeenCalledWith(22, "raw/wine.csv", 11);
    expect(wrapper.find('[data-testid="data-tabs"]').attributes("data-active-index")).toBe("4");
    expect(localStorage.getItem("spectra_sherpa_data_active_tab_v2_7_3")).toBe("4");
    expect(mocks.routerReplace).toHaveBeenCalledWith({
      path: "/data",
      query: {
        tab: "my-dataset",
        experiment: "11",
        fileId: "22",
      },
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

  it("lists the source files for the Import preview", async () => {
    mocks.dataStore.referenceCatalog.spectrochempy = [
      {
        source: "spectrochempy",
        name: "irdata/OPUS",
        label: "FTIR OPUS Test Spectra",
        technique: "FTIR",
        files: [
          "irdata/OPUS/test.0000",
          "irdata/OPUS/test.0001",
          "irdata/OPUS/test.0002",
          "irdata/OPUS/test.0003",
        ],
        file_count: 4,
        entry_type: "bundle",
      },
    ];
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.previewRefKey = "spectrochempy::irdata/OPUS";
    await flushPromises();

    const filesPanel = wrapper.find(".source-files");
    expect(filesPanel.exists()).toBe(true);
    expect(filesPanel.find(".section-toggle").attributes("aria-expanded")).toBe("false");
    expect(filesPanel.text()).toContain("Files");
    expect(filesPanel.text()).toContain("4 files");
    expect(filesPanel.text()).toContain("test.0000");
    expect(filesPanel.text()).toContain("0000");
    expect(filesPanel.text()).toContain("test.0003");
    expect(filesPanel.text()).toContain("0003");
  });

  it("lists Eigenvector catalog source files without parsing archives", async () => {
    mocks.dataStore.referenceCatalog.eigenvector = [
      {
        source: "eigenvector",
        name: "diesel_nir",
        label: "Diesel NIR",
        technique: "NIR",
        files: ["diesel_csv/diesel_spec.csv", "diesel_csv/diesel_prop.csv"],
        file_path: "diesel_csv/diesel_spec.csv",
      },
    ];
    const wrapper = mountDataContent();
    await flushPromises();

    const vm = wrapper.vm as unknown as DataContentVm;
    vm.previewRefKey = "eigenvector::diesel_nir";
    await flushPromises();

    const filesPanel = wrapper.find(".source-files");
    expect(filesPanel.exists()).toBe(true);
    expect(filesPanel.find(".section-toggle").attributes("aria-expanded")).toBe("false");
    expect(filesPanel.text()).toContain("2 files");
    expect(filesPanel.text()).toContain("diesel_spec.csv");
    expect(filesPanel.text()).toContain("diesel_prop.csv");
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
    expect(restoredVm.refOverrides["sklearn::iris"]).toEqual({ title: "Iris edited", x_title: "features" });
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

    const headers = wrapper.findAll(".rendered-column").map((column) => column.attributes("data-header"));
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
    vm.stagedUploadMembers = [{ staging_id: "abc123", filename: file.name, size_bytes: file.size }];
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
});
