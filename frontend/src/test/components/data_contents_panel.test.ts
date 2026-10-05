/* eslint-disable vue/one-component-per-file */
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, reactive } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DataContentsPanel from "@/views/data/DataContentsPanel.vue";
import api from "@/api/client";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  dataStore: {
    fileInfoLoading: false,
    fileInfoError: null as string | null,
    catalogDatasetLoading: false,
    catalogDatasetError: null as string | null,
    catalogDatasetInfo: null,
    activeFileId: null as number | null,
    activeFilePath: null as string | null,
    activeExperimentId: null as number | null,
    fileInfo: null as Record<string, unknown> | null,
    dataStoryText: null,
    dataStoryMemoryScopes: [],
    dataStoryLoading: false,
    dataStoryContext: "",
    generateDataStory: vi.fn(),
    uploadFile: vi.fn(),
    selectExperiment: vi.fn(),
    fetchCatalog: vi.fn(),
    bindDatasetAnalysisCsv: vi.fn(),
    unbindDatasetAnalysisCsv: vi.fn(),
    inspectFile: vi.fn(),
    fetchDataMatrix: vi.fn(),
  },
  sherpaStore: {
    isSyncing: false,
    isChatting: false,
  },
}));

vi.mock("@/stores/data", () => ({
  useDataStore: () => mocks.dataStore,
}));

vi.mock("@/stores/sherpa", () => ({
  useSherpaStore: () => mocks.sherpaStore,
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    isFeatureEnabled: () => false,
  }),
}));

vi.mock("@/api/client", () => ({
  default: {
    get: mocks.apiGet,
    post: mocks.apiPost,
    patch: vi.fn().mockResolvedValue({ data: { status: "ok" } }),
  },
}));

vi.mock("primevue/datatable", () => ({
  default: defineComponent({ name: "DataTable", template: "<div><slot /></div>" }),
}));

vi.mock("primevue/column", () => ({
  default: defineComponent({ name: "Column", template: "<div />" }),
}));

vi.mock("primevue/dropdown", () => ({
  default: defineComponent({
    name: "Dropdown",
    props: {
      modelValue: { type: String, default: "" },
      options: { type: Array, default: () => [] },
      disabled: { type: Boolean, default: false },
      optionDisabled: { type: String, default: "" },
    },
    template:
      "<span>{{ modelValue }}<span v-for='option in options' :key='option.value'><slot name='option' :option='option' /></span></span>",
  }),
}));

vi.mock("primevue/inputswitch", () => ({
  default: defineComponent({ name: "InputSwitch", template: "<input type='checkbox' />" }),
}));

vi.mock("primevue/progressspinner", () => ({
  default: defineComponent({ name: "ProgressSpinner", template: "<div />" }),
}));

vi.mock("primevue/tag", () => ({
  default: defineComponent({
    name: "Tag",
    props: { value: { type: [String, Number], default: "" } },
    template: "<span>{{ value }}</span>",
  }),
}));

vi.mock("primevue/textarea", () => ({
  default: defineComponent({ name: "PrimeTextareaStub", template: "<textarea />" }),
}));

vi.mock("primevue/button", () => ({
  default: defineComponent({ name: "PrimeButtonStub", template: "<button />" }),
}));

vi.mock("@/components/MemoryAttribution.vue", () => ({
  default: defineComponent({ name: "MemoryAttribution", template: "<div />" }),
}));

vi.mock("@/components/PlotlyChart.vue", () => ({
  default: defineComponent({
    name: "PlotlyChart",
    props: {
      data: { type: Array, default: () => [] },
      layout: { type: Object, default: () => ({}) },
    },
    template: "<div data-testid='plotly-chart' />",
  }),
}));

vi.mock("@/views/data/DataQualityPanel.vue", () => ({
  default: defineComponent({
    name: "DataQualityPanel",
    template: "<div data-testid='data-quality' />",
  }),
}));

function resetDataStore() {
  mocks.dataStore.fileInfoLoading = false;
  mocks.dataStore.fileInfoError = null;
  mocks.dataStore.catalogDatasetLoading = false;
  mocks.dataStore.catalogDatasetError = null;
  mocks.dataStore.catalogDatasetInfo = null;
  mocks.dataStore.activeFileId = null;
  mocks.dataStore.activeFilePath = null;
  mocks.dataStore.activeExperimentId = null;
  mocks.dataStore.fileInfo = null;
  mocks.dataStore.dataStoryText = null;
  mocks.dataStore.dataStoryMemoryScopes = [];
  mocks.dataStore.dataStoryLoading = false;
  mocks.dataStore.dataStoryContext = "";
  mocks.dataStore.uploadFile.mockReset();
  mocks.dataStore.selectExperiment.mockReset();
  mocks.dataStore.selectExperiment.mockResolvedValue(undefined);
  mocks.dataStore.fetchCatalog.mockReset();
  mocks.dataStore.fetchCatalog.mockResolvedValue(undefined);
  mocks.dataStore.bindDatasetAnalysisCsv.mockReset();
  mocks.dataStore.bindDatasetAnalysisCsv.mockResolvedValue({ status: "bound" });
  mocks.dataStore.unbindDatasetAnalysisCsv.mockReset();
  mocks.dataStore.unbindDatasetAnalysisCsv.mockResolvedValue({ status: "unbound" });
  mocks.dataStore.inspectFile.mockReset();
  mocks.dataStore.fetchDataMatrix.mockReset();
  mocks.dataStore.inspectFile.mockResolvedValue(null);
  mocks.apiGet.mockReset();
  mocks.apiPost.mockReset();
  vi.mocked(api.patch).mockClear();
}

function sourceCollection(fileCount: number, manifestDigest = "a".repeat(64)) {
  return {
    schema_version: "spectrasherpa-source-collection/1",
    file_count: fileCount,
    manifest_digest: manifestDigest,
    files: Array.from({ length: fileCount }, (_, index) => ({
      file_name: `raw/source-${index + 1}.spa`,
      size_bytes: 100 + index,
      sha256: `${((index + 1) % 16).toString(16)}`.repeat(64),
      prepared_data_sha256: "f".repeat(64),
    })),
  };
}

describe("DataContentsPanel", () => {
  beforeEach(() => {
    resetDataStore();
  });

  it.each([["iris", 150, 4], ["wine", 178, 13], ["breast_cancer", 569, 30]] as const)(
    "does not interpret %s specimen labels as an empty file selection", async (name, rows, columns) => {
      mocks.dataStore.fileInfo = {
        n_samples: rows, n_features: columns,
        data: Array.from({ length: rows }, () => Array(columns).fill(1)),
        y_axis: { labels: Array.from({ length: rows }, (_, i) => `Specimen ${i + 1}`) },
        metadata: { contents_file_count: 1 },
      };
      const wrapper = mount(DataContentsPanel, { props: { selectedFileNames: [`${name}.npz`] } });
      await flushPromises();
      const sampleRow = wrapper.findAll(".meta-row").find(row => row.find(".meta-key").text() === "Samples");
      expect(sampleRow?.find(".meta-val").text()).toBe(String(rows));
      wrapper.unmount();
    },
  );

  it("retrieves the persisted source matrix when technical details open", async () => {
    mocks.dataStore.activeExperimentId = 44;
    mocks.dataStore.activeFileId = 103;
    mocks.dataStore.fileInfo = { n_samples: 1, n_features: 1, data: [[1]], metadata: {} };
    mocks.dataStore.fetchDataMatrix.mockRejectedValue(new Error("test retrieval"));
    const wrapper = mount(DataContentsPanel);
    const details = wrapper.find("details.technical-details");
    expect(details).toBeDefined();
    (details!.element as HTMLDetailsElement).open = true;
    await details!.trigger("toggle");
    await flushPromises();
    expect(mocks.dataStore.fetchDataMatrix).toHaveBeenCalledWith({ kind: "experiment_file", experiment_id: 44, file_id: 103 });
    expect(wrapper.text()).not.toContain("Select one source file to inspect its data matrix.");
    wrapper.unmount();
  });

  it("refreshes GUI-01 authority when only the selected source digest changes", async () => {
    mocks.dataStore = reactive(mocks.dataStore);
    mocks.dataStore.fileInfo = {
      n_samples: 4,
      n_features: 2,
      y_axis: {
        labels: ["C01", "C02", "T01", "T02"],
        sample_table: { assay: [1, 1, 2, 3] },
      },
      metadata: { source_collection: sourceCollection(1) },
    };
    const wrapper = mount(DataContentsPanel, { props: { initialAnalysisTarget: "assay" } });
    await flushPromises();
    expect(wrapper.emitted("analysisChoice")?.at(-1)?.[0]).toEqual(
      expect.objectContaining({
        target: "assay",
        targetType: "continuous",
        sourceDigest: "a".repeat(64),
      }),
    );
    (mocks.dataStore.fileInfo.metadata as Record<string, unknown>).source_collection =
      sourceCollection(1, "b".repeat(64));
    await flushPromises();
    expect(wrapper.emitted("analysisChoice")?.at(-1)?.[0]).toEqual(
      expect.objectContaining({
        target: "assay",
        targetType: "continuous",
        sourceDigest: "b".repeat(64),
      }),
    );
    mocks.dataStore.fileInfoLoading = true;
    await flushPromises();
    expect(wrapper.emitted("analysisChoice")?.at(-1)?.[0]).toEqual(
      expect.objectContaining({ sourceDigest: null }),
    );
    mocks.dataStore.fileInfoLoading = false;
    await flushPromises();
    expect(wrapper.emitted("analysisChoice")?.at(-1)?.[0]).toEqual(
      expect.objectContaining({ sourceDigest: "b".repeat(64) }),
    );
    wrapper.unmount();
  });

  it.each(["continuous", "categorical"] as const)(
    "keeps a declared %s native target available beside a valid sample table",
    async (targetType) => {
      mocks.dataStore.fileInfo = {
        n_samples: 4,
        n_features: 2,
        target: targetType === "continuous" ? [1, 1, 2, 3] : [0, 1, 0, 1],
        target_context: { target_type: targetType, target_name: "assay", target_names: ["assay"] },
        y_axis: {
          labels: ["C01", "C02", "T01", "T02"],
          sample_table: { specimen_id: ["C01", "C02", "T01", "T02"] },
        },
        metadata: { source_collection: sourceCollection(1) },
        analysis_readiness: {
          profile: {
            primary_role: "X_features",
            modality: "feature",
            technique: "Unknown",
            target_fields: ["assay"],
            target_type: targetType,
            identity_fields: ["specimen_id"],
            group_fields: [],
            ordered_samples: false,
          },
          counts: {
            compatible: 0,
            needs_target: 0,
            needs_source: 0,
            incompatible: 0,
            pending: 0,
            unavailable: 0,
          },
          decisions: [],
          diagnostics: [],
        },
      };
      mocks.apiPost.mockResolvedValue({ data: mocks.dataStore.fileInfo.analysis_readiness });
      const wrapper = mount(DataContentsPanel, { props: { initialAnalysisTarget: "assay" } });
      await flushPromises();
      expect(wrapper.emitted("analysisChoice")?.at(-1)?.[0]).toEqual(
        expect.objectContaining({ target: "assay", targetType, sourceDigest: "a".repeat(64) }),
      );
      const axis = mocks.dataStore.fileInfo.y_axis as { sample_table: Record<string, unknown> };
      axis.sample_table.assay = mocks.dataStore.fileInfo.target;
      await flushPromises();
      expect(wrapper.emitted("analysisChoice")?.at(-1)?.[0]).toEqual(
        expect.objectContaining({ target: "assay", targetType }),
      );
      wrapper.unmount();
    },
  );

  it("sends native target units only for the selected native response", async () => {
    mocks.dataStore.fileInfo = {
      n_samples: 4,
      n_features: 2,
      target: [1, 2, 3, 4],
      target_context: {
        target_type: "continuous",
        target_name: "assay",
        target_names: ["assay"],
        target_units: "mg/L",
      },
      y_axis: {
        labels: ["C01", "C02", "T01", "T02"],
        sample_table: {
          specimen_id: ["C01", "C02", "T01", "T02"],
          protein: [0.1, 0.2, 0.3, 0.4],
        },
      },
      metadata: { source_collection: sourceCollection(1) },
      analysis_readiness: {
        profile: {
          primary_role: "X_features",
          modality: "feature",
          technique: "Unknown",
          target_fields: ["assay"],
          target_type: "continuous",
          identity_fields: ["specimen_id"],
          group_fields: [],
          ordered_samples: false,
        },
        counts: {
          compatible: 0,
          needs_target: 0,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [],
        diagnostics: [],
      },
    };
    mocks.apiPost.mockResolvedValue({ data: mocks.dataStore.fileInfo.analysis_readiness });

    const alternate = mount(DataContentsPanel, { props: { initialAnalysisTarget: "protein" } });
    await flushPromises();
    expect(alternate.emitted("analysisChoice")?.at(-1)?.[0]).toEqual(
      expect.objectContaining({ target: "protein", targetUnits: null }),
    );
    alternate.unmount();

    const native = mount(DataContentsPanel, { props: { initialAnalysisTarget: "assay" } });
    await flushPromises();
    expect(native.emitted("analysisChoice")?.at(-1)?.[0]).toEqual(
      expect.objectContaining({ target: "assay", targetUnits: "mg/L" }),
    );
    native.unmount();
  });

  it("uses the exact single-file preview rows despite provider-specific sample labels", async () => {
    mocks.dataStore.activeFilePath = "raw/calibration.mat";
    mocks.dataStore.fileInfo = {
      n_samples: 4,
      n_features: 2,
      y_axis: {
        labels: ["C01", "C02", "C03", "C04"],
        sample_table: { assay: [1, 1, 2, 3] },
      },
      metadata: { contents_file_count: 1 },
      analysis_readiness: {
        profile: {
          primary_role: "X_spectra",
          modality: "spectral",
          technique: "NIR",
          target_fields: ["assay"],
          target_type: "continuous",
          identity_fields: [],
          group_fields: [],
          ordered_samples: false,
        },
        counts: {
          compatible: 0,
          needs_target: 0,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [],
        diagnostics: [],
      },
    };
    mocks.apiPost.mockResolvedValue({ data: mocks.dataStore.fileInfo.analysis_readiness });
    const wrapper = mount(DataContentsPanel, {
      props: { selectedFileNames: ["raw/calibration.mat"] },
    });
    await flushPromises();
    const options = wrapper
      .get("[aria-label='Analysis readiness']")
      .findAllComponents({ name: "Dropdown" })[0]
      .props("options");
    expect(options).toContainEqual(
      expect.objectContaining({
        value: "assay",
        detail: expect.stringContaining("4 non-empty numeric values, 3 distinct"),
      }),
    );
    wrapper.unmount();
  });

  it("restores display controls without writing metadata and still saves user edits", async () => {
    vi.useFakeTimers();
    mocks.dataStore.activeExperimentId = 12;
    mocks.dataStore.activeFilePath = "raw/example.csv";
    mocks.dataStore.fileInfo = {
      n_samples: 2,
      n_features: 2,
      data: [
        [1, 2],
        [3, 4],
      ],
      metadata: { x_title: "Wavelength", x_units: "nm", data_quantity: "Absorbance" },
    };
    const wrapper = mount(DataContentsPanel);
    try {
      await flushPromises();
      const editor = wrapper.getComponent({ name: "MetadataEditor" });
      expect(editor.props("xTitle")).toBe("Wavelength");
      expect(editor.props("xUnits")).toBe("nm");
      await vi.advanceTimersByTimeAsync(600);
      expect(api.patch).not.toHaveBeenCalled();
      editor.vm.$emit("update:xTitle", "Feature");
      await flushPromises();
      await vi.advanceTimersByTimeAsync(600);
      expect(api.patch).toHaveBeenCalledTimes(1);
      expect(api.patch).toHaveBeenCalledWith(
        "/builder/file-metadata",
        expect.objectContaining({
          x_title: "Feature",
          experiment_id: 12,
        }),
      );
      editor.vm.$emit("update:xTitle", "Pending edit");
      await flushPromises();
      wrapper.unmount();
      mocks.dataStore.activeExperimentId = 13;
      mocks.dataStore.fileInfo = { metadata: { x_title: "Next dataset" } };
      await vi.advanceTimersByTimeAsync(600);
      expect(api.patch).toHaveBeenCalledTimes(2);
      expect(api.patch).toHaveBeenLastCalledWith(
        "/builder/file-metadata",
        expect.objectContaining({
          x_title: "Pending edit",
          experiment_id: 12,
        }),
      );
      expect(mocks.dataStore.fileInfo.metadata).toEqual({ x_title: "Next dataset" });
    } finally {
      wrapper.unmount();
      vi.useRealTimers();
    }
  });

  it("shows file-count metadata and data quality for tabular dataset-level contents", () => {
    mocks.dataStore.fileInfo = {
      title: "Wine bundle",
      n_samples: 178,
      n_features: 13,
      x_axis: { labels: ["alcohol", "malic acid"] },
      data: [
        [14.23, 1.71],
        [13.2, 1.78],
      ],
      metadata: {
        contents_file_count: 3,
        contents_title: "Wine bundle",
        x_title: "Feature",
        data_quantity: "Value",
      },
    };

    const wrapper = mount(DataContentsPanel);

    const displaySettings = wrapper.get(".global-display-metadata");
    const activeDataset = wrapper.get(".focused-dataset-details");
    expect(displaySettings.text()).toContain("Display Settings");
    expect(
      displaySettings.element.compareDocumentPosition(activeDataset.element) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(activeDataset.find(".global-display-metadata").exists()).toBe(false);
    expect(wrapper.text()).toContain("Dataset Metadata");
    expect(wrapper.text()).toContain("Files");
    expect(wrapper.text()).toContain("3");
    expect(wrapper.text()).toContain("178");
    expect(wrapper.text()).toContain("13");
    expect(wrapper.find("[data-testid='data-quality']").exists()).toBe(true);
  });

  it("shows runtime readiness and can remove a saved target binding", async () => {
    mocks.dataStore.activeExperimentId = 12;
    mocks.dataStore.activeFileId = 41;
    mocks.dataStore.activeFilePath = "raw/bound.csv";
    mocks.dataStore.fileInfo = {
      title: "Bound spectra",
      n_samples: 24,
      n_features: 100,
      data: [[1, 2]],
      analysis_binding: {
        revision: "a".repeat(64),
        sample_table_file_id: 73,
        selected_target: "species",
        target_type: "categorical",
      },
      analysis_readiness: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "ready",
        profile: {
          primary_role: "X_spectra",
          modality: "spectra",
          technique: "FTIR",
          target_type: "categorical",
          target_fields: ["species"],
          identity_fields: ["sample_id"],
          group_fields: ["batch"],
          ordered_samples: false,
        },
        template_count: 2,
        counts: {
          compatible: 2,
          needs_target: 0,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [
          {
            template_slug: "pca",
            template_name: "PCA",
            category: "exploratory",
            display_status: "compatible",
            status: "compatible",
            reason_codes: [],
            reasons: [],
          },
          {
            template_slug: "classification-plsda",
            template_name: "PLS-DA Classification",
            category: "classification",
            display_status: "compatible",
            status: "compatible",
            reason_codes: [],
            reasons: [],
          },
        ],
        diagnostics: [],
      },
    };
    mocks.apiPost.mockResolvedValue({
      data: mocks.dataStore.fileInfo.analysis_readiness,
    });

    const wrapper = mount(DataContentsPanel, {
      props: {
        initialAnalysisTarget: "species",
        initialAnalysisGroup: "batch",
        analysisSelectionHydrated: true,
        analysisSelectionStatus: "saved",
      },
    });
    await flushPromises();

    const readiness = wrapper.get("[aria-label='Analysis readiness']");
    expect(readiness.attributes("open")).toBeDefined();
    expect(readiness.text()).toContain("species");
    const readinessDropdowns = readiness.findAllComponents({ name: "Dropdown" });
    expect(readinessDropdowns[0].props("options")).toEqual(
      expect.arrayContaining([expect.objectContaining({ value: "species" })]),
    );
    expect(readinessDropdowns[1].props("options")).toEqual(
      expect.arrayContaining([expect.objectContaining({ value: "batch" })]),
    );
    expect(readinessDropdowns[0].props("modelValue")).toBe("species");
    expect(readinessDropdowns[1].props("modelValue")).toBe("batch");
    expect(readiness.text()).toContain("Saved with this dataset.");
    expect(readiness.text()).toContain("2Available");
    const available = readiness.findAll(".analysis-readiness__count")[0];
    expect(available.attributes("title")).toBe("PCA\nPLS-DA Classification");
    const readinessButtons = readiness.findAllComponents({ name: "PrimeButtonStub" });
    await readinessButtons.at(-1)!.trigger("click");
    await flushPromises();
    expect(mocks.dataStore.unbindDatasetAnalysisCsv).toHaveBeenCalledWith(41, "a".repeat(64));
    expect(mocks.dataStore.inspectFile).toHaveBeenCalledWith(41, "raw/bound.csv", 12);
  });

  it("never renders stale file readiness beside catalog exploration", () => {
    mocks.dataStore.catalogDatasetInfo = {
      label: "Catalog dataset",
      description: "Catalog authority",
    } as never;
    mocks.dataStore.fileInfo = {
      title: "Stale inspected file",
      analysis_readiness: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "unavailable",
        profile: null,
        template_count: 0,
        counts: {
          compatible: 0,
          needs_target: 0,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [],
        diagnostics: [],
      },
    };

    const wrapper = mount(DataContentsPanel);

    expect(wrapper.text()).toContain("Catalog dataset");
    expect(wrapper.find("[aria-label='Analysis readiness']").exists()).toBe(false);
    expect(wrapper.find(".focused-dataset-details").exists()).toBe(false);
  });

  it("renders exact collection identity and its aligned sample table", () => {
    const manifestDigest = "a".repeat(64);
    mocks.dataStore.fileInfo = {
      title: "Exact oil collection",
      data_role: "X_spectra",
      n_samples: 4,
      n_features: 3,
      x_axis: { data: [1800, 1200, 600], title: "Wavenumber", units: "cm-1" },
      y_axis: {
        labels: ["A__B1", "B__B1", "A__B2", "B__B2"],
        sample_table: {
          sample_id: ["A__B1", "B__B1", "A__B2", "B__B2"],
          specimen_id: ["A", "B", "A", "B"],
          block: [1, 1, 2, 2],
          analysis_role: ["model", "model", "model", "model"],
        },
      },
      data: [
        [0.1, 0.2, 0.3],
        [0.2, 0.3, 0.4],
        [0.11, 0.21, 0.31],
        [0.22, 0.32, 0.42],
      ],
      metadata: {
        contents_file_count: 4,
        contents_title: "Exact oil collection",
        source_collection: sourceCollection(4, manifestDigest),
      },
    };

    const wrapper = mount(DataContentsPanel);
    expect(wrapper.get("[aria-label='Collection identity']").text()).toContain(
      "4 exact source files",
    );
    expect(wrapper.get("[aria-label='Collection identity']").text()).toContain(manifestDigest);
    expect(wrapper.get("[aria-label='Collection sample table']").text()).toContain(
      "4 rows · 4 columns",
    );
    expect(wrapper.get("[aria-label='Collection sample table']").text()).toContain("specimen id");
    expect(wrapper.get("[aria-label='Collection sample table']").text()).toContain("A__B2");
    expect(wrapper.text()).toContain("Active dataset: Exact oil collection");
  });

  it("keeps a constant selected-subset target available for exploratory labeling", async () => {
    mocks.dataStore.activeExperimentId = 12;
    mocks.dataStore.fileInfo = {
      title: "Lavender collection",
      data_role: "X_spectra",
      n_samples: 4,
      n_features: 2,
      x_axis: { data: [1800, 600] },
      y_axis: {
        labels: ["A__B1", "B__B1", "A__B2", "B__B2"],
        sample_table: {
          sample_id: ["A__B1", "B__B1", "A__B2", "B__B2"],
          specimen_id: ["A", "B", "A", "B"],
          block: [1, 1, 2, 2],
        },
      },
      data: [
        [0.1, 0.2],
        [0.2, 0.3],
        [0.3, 0.4],
        [0.4, 0.5],
      ],
      metadata: {
        source_collection: sourceCollection(4),
        source_member_metadata: Array.from({ length: 4 }, (_, index) => ({ file_name: `source-${index + 1}.spa` })),
      },
      analysis_readiness: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "ready",
        profile: {
          primary_role: "X_spectra",
          modality: "spectra",
          technique: "FTIR",
          target_type: null,
          target_fields: ["specimen_id"],
          identity_fields: ["sample_id"],
          group_fields: ["block"],
          ordered_samples: false,
        },
        template_count: 0,
        counts: {
          compatible: 0,
          needs_target: 0,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [],
        diagnostics: [],
      },
    };

    const wrapper = mount(DataContentsPanel, {
      props: {
        selectedFileNames: ["source-1.spa", "source-2.spa", "source-3.spa", "source-4.spa"],
      },
    });
    const readiness = wrapper.get("[aria-label='Analysis readiness']");
    const dropdowns = readiness.findAllComponents({ name: "Dropdown" });
    dropdowns[0].vm.$emit("update:modelValue", "specimen_id");
    dropdowns[1].vm.$emit("update:modelValue", "block");
    await flushPromises();

    await wrapper.setProps({ selectedFileNames: ["source-1.spa"] });
    await flushPromises();

    const updated = wrapper
      .get("[aria-label='Analysis readiness']")
      .findAllComponents({ name: "Dropdown" });
    expect(updated[0].props("modelValue")).toBe("specimen_id");
    expect(updated[0].props("options")).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ value: "specimen_id", type: "categorical", disabled: false }),
      ]),
    );
    expect(wrapper.get("[aria-label='Analysis readiness']").text()).toContain(
      "supervised analyses require variation",
    );
    expect(updated[1].props("modelValue")).toBe("");
    expect(updated[1].props("disabled")).toBe(false);
    expect(updated[1].props("options")).toEqual(
      expect.arrayContaining([expect.objectContaining({ value: "block", disabled: true })]),
    );
  });

  it("offers every numeric response without choosing one and recognizes repeated specimens", () => {
    mocks.dataStore.activeExperimentId = 12;
    mocks.dataStore.fileInfo = {
      title: "Corn collection",
      data_role: "X_spectra",
      n_samples: 4,
      n_features: 2,
      x_axis: { data: [900, 800] },
      y_axis: {
        labels: ["corn-1-m5", "corn-2-m5", "corn-1-mp5", "corn-2-mp5"],
        sample_table: {
          sample_id: ["corn-1-m5", "corn-2-m5", "corn-1-mp5", "corn-2-mp5"],
          specimen_id: ["corn-1", "corn-2", "corn-1", "corn-2"],
          moisture: [10.1, 11.2, 10.1, 11.2],
          oil: [4.2, 5.1, 4.2, 5.1],
        },
      },
      data: [
        [0.1, 0.2],
        [0.2, 0.3],
        [0.3, 0.4],
        [0.4, 0.5],
      ],
      metadata: { source_collection: sourceCollection(3) },
      analysis_readiness: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "ready",
        profile: {
          primary_role: "X_spectra",
          modality: "spectra",
          technique: "NIR",
          target_type: null,
          target_fields: [],
          identity_fields: ["sample_id"],
          group_fields: ["specimen_id"],
          ordered_samples: false,
        },
        template_count: 0,
        counts: {
          compatible: 0,
          needs_target: 0,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [],
        diagnostics: [],
      },
    };

    const wrapper = mount(DataContentsPanel);
    const dropdowns = wrapper
      .get("[aria-label='Analysis readiness']")
      .findAllComponents({ name: "Dropdown" });
    const targetOptions = dropdowns[0].props("options");

    expect(targetOptions).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ value: "moisture", type: "continuous", disabled: false }),
        expect.objectContaining({ value: "oil", type: "continuous", disabled: false }),
      ]),
    );
    expect(dropdowns[0].props("modelValue")).toBe("");
    expect(dropdowns[1].props("options")).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ value: "specimen_id", label: "Specimen Identity: 2" }),
      ]),
    );
  });

  it("refuses declared identity fields as targets and counts empties honestly", () => {
    mocks.dataStore.activeExperimentId = 21;
    mocks.dataStore.fileInfo = {
      title: "Corn-like projection with a sparse analyte",
      data_role: "X_spectra",
      n_samples: 4,
      n_features: 2,
      x_axis: { data: [1100, 1102], title: "Wavelength", units: "nm" },
      y_axis: {
        labels: ["s-1", "s-2", "s-3", "s-4"],
        sample_table: {
          sample_id: ["s-1", "s-2", "s-3", "s-4"],
          // Declared identity below; a model fitted on it would predict the
          // row's own name, so it must never be offered as a target.
          specimen_id: ["c-1", "c-2", "c-3", "c-4"],
          instrument: ["M5", "M5", "MP5", "MP5"],
          // One blank and one repeat, so the two counts differ: 3 non-empty
          // values across 2 distinct levels, out of 4 rows.
          Moisture: [10.5, "", 11.2, 10.5],
        },
      },
      data: [
        [0.1, 0.2],
        [0.2, 0.3],
        [0.3, 0.4],
        [0.4, 0.5],
      ],
      metadata: { source_collection: sourceCollection(1) },
      analysis_readiness: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "ready",
        profile: {
          primary_role: "X_spectra",
          modality: "spectra",
          technique: "NIR",
          target_type: "continuous",
          target_fields: ["Moisture"],
          identity_fields: ["sample_id", "specimen_id"],
          group_fields: ["instrument"],
          ordered_samples: false,
        },
        template_count: 0,
        counts: {
          compatible: 0,
          needs_target: 0,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [],
        diagnostics: [],
      },
    };

    const wrapper = mount(DataContentsPanel, {
      props: {
        selectedFileNames: ["Corn-like projection with a sparse analyte"],
      },
    });

    const targetOptions = wrapper
      .get("[aria-label='Analysis readiness']")
      .findAllComponents({ name: "Dropdown" })[0]
      .props("options") as Array<{ value: string; detail?: string }>;

    // The declared identity fields are absent from the target choices, because
    // this profile does not declare them as targets. The Lavender corpus does
    // declare specimen_id, and the case below proves that one is still offered.
    expect(targetOptions.map((option) => option.value)).not.toContain("specimen_id");
    expect(targetOptions.map((option) => option.value)).not.toContain("sample_id");

    // The count reports non-empty values, not distinct levels, and says so.
    const moisture = targetOptions.find((option) => option.value === "Moisture");
    expect(moisture?.detail).toContain("3 non-empty numeric values");
    expect(moisture?.detail).toContain("2 distinct");
  });

  it("still offers a repeated identity column when the profile declares it a target", () => {
    // Shaped after builtin:lavender-essential-oil-v1, where specimen_id is both
    // an identity and a declared target: 2 specimens across 2 acquisition
    // blocks, so the class has replicates and the question is answerable.
    mocks.dataStore.activeExperimentId = 22;
    mocks.dataStore.fileInfo = {
      title: "Lavender-shaped corpus with replicated specimens",
      data_role: "X_spectra",
      n_samples: 4,
      n_features: 2,
      x_axis: { data: [1000, 1002], title: "Wavenumber", units: "cm-1" },
      y_axis: {
        labels: ["a-1", "a-2", "b-1", "b-2"],
        sample_table: {
          sample_id: ["a-1", "a-2", "b-1", "b-2"],
          specimen_id: ["spec-a", "spec-a", "spec-b", "spec-b"],
          block: ["1", "2", "1", "2"],
        },
      },
      data: [
        [0.1, 0.2],
        [0.2, 0.3],
        [0.3, 0.4],
        [0.4, 0.5],
      ],
      metadata: { source_collection: sourceCollection(1) },
      analysis_readiness: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "ready",
        profile: {
          primary_role: "X_spectra",
          modality: "spectra",
          technique: "FTIR",
          target_type: "categorical",
          target_fields: ["specimen_id"],
          identity_fields: ["sample_id", "specimen_id"],
          group_fields: ["block"],
          ordered_samples: false,
        },
        template_count: 0,
        counts: {
          compatible: 0,
          needs_target: 0,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [],
        diagnostics: [],
      },
    };

    const wrapper = mount(DataContentsPanel, {
      props: {
        selectedFileNames: ["Lavender-shaped corpus with replicated specimens"],
      },
    });

    const targetOptions = wrapper
      .get("[aria-label='Analysis readiness']")
      .findAllComponents({ name: "Dropdown" })[0]
      .props("options") as Array<{ value: string }>;

    // Declared, so retained even though it is also an identity field.
    expect(targetOptions.map((option) => option.value)).toContain("specimen_id");
    // Not declared, so still withheld.
    expect(targetOptions.map((option) => option.value)).not.toContain("sample_id");
  });

  it("withholds a declared identity target that does not actually repeat", () => {
    // Same declaration as the Lavender-shaped case above, but the data gives
    // every row its own specimen. A declaration cannot make a per-row label
    // learnable, so the column is withheld despite being declared.
    mocks.dataStore.activeExperimentId = 23;
    mocks.dataStore.fileInfo = {
      title: "Mis-declared corpus with one specimen per row",
      data_role: "X_spectra",
      n_samples: 3,
      n_features: 2,
      x_axis: { data: [1000, 1002], title: "Wavenumber", units: "cm-1" },
      y_axis: {
        labels: ["a-1", "b-1", "c-1"],
        sample_table: {
          sample_id: ["a-1", "b-1", "c-1"],
          specimen_id: ["spec-a", "spec-b", "spec-c"],
          grade: ["high", "high", "low"],
        },
      },
      data: [
        [0.1, 0.2],
        [0.2, 0.3],
        [0.3, 0.4],
      ],
      metadata: { source_collection: sourceCollection(1) },
      analysis_readiness: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "ready",
        profile: {
          primary_role: "X_spectra",
          modality: "spectra",
          technique: "FTIR",
          target_type: "categorical",
          target_fields: ["specimen_id", "grade"],
          identity_fields: ["sample_id", "specimen_id"],
          group_fields: [],
          ordered_samples: false,
        },
        template_count: 0,
        counts: {
          compatible: 0,
          needs_target: 0,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [],
        diagnostics: [],
      },
    };

    const wrapper = mount(DataContentsPanel, {
      props: {
        selectedFileNames: ["Mis-declared corpus with one specimen per row"],
      },
    });

    const targetOptions = wrapper
      .get("[aria-label='Analysis readiness']")
      .findAllComponents({ name: "Dropdown" })[0]
      .props("options") as Array<{ value: string }>;

    // Declared, but one specimen per row: withheld.
    expect(targetOptions.map((option) => option.value)).not.toContain("specimen_id");
    // An ordinary categorical annotation that repeats is unaffected.
    expect(targetOptions.map((option) => option.value)).toContain("grade");
  });

  it("keeps provider annotations when one selected Data View has a different internal source name", () => {
    mocks.dataStore.activeExperimentId = 12;
    mocks.dataStore.fileInfo = {
      title: "NIR Shootout calibration instrument 1",
      data_role: "X_spectra",
      n_samples: 3,
      n_features: 2,
      x_axis: { data: [600, 602], title: "Wavelength", units: "nm" },
      y_axis: {
        labels: ["sample-1", "sample-2", "sample-3"],
        sample_table: {
          sample_id: ["sample-1", "sample-2", "sample-3"],
          source_label: ["1", "2", "3"],
          Weight: [1.1, 1.2, 1.3],
          Hardness: [40, 42, 44],
          Assay: [98.1, 99.2, 100.3],
        },
      },
      data: [
        [0.1, 0.2],
        [0.2, 0.3],
        [0.3, 0.4],
      ],
      metadata: { source_collection: sourceCollection(1) },
      analysis_readiness: {
        schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
        scope: "structural",
        status: "ready",
        profile: {
          primary_role: "X_spectra",
          modality: "spectra",
          technique: "NIR",
          target_type: null,
          target_fields: ["Weight", "Hardness", "Assay"],
          identity_fields: ["sample_id"],
          group_fields: [],
          ordered_samples: false,
        },
        template_count: 0,
        counts: {
          compatible: 0,
          needs_target: 0,
          needs_source: 0,
          incompatible: 0,
          pending: 0,
          unavailable: 0,
        },
        decisions: [],
        diagnostics: [],
      },
    };

    const wrapper = mount(DataContentsPanel, {
      props: {
        selectedFileNames: ["Calibration · Instrument 1"],
      },
    });
    const targetOptions = wrapper
      .get("[aria-label='Analysis readiness']")
      .findAllComponents({ name: "Dropdown" })[0]
      .props("options");

    expect(targetOptions).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          value: "Weight",
          type: "continuous",
          detail:
            "3 non-empty numeric values, 3 distinct, in the selected subset; treated as a continuous response.",
        }),
        expect.objectContaining({ value: "Hardness", type: "continuous" }),
        expect.objectContaining({ value: "Assay", type: "continuous" }),
      ]),
    );
  });

  it("waits for the saved target and reuses readiness on page return", async () => {
    const baseReadiness = {
      schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
      scope: "structural",
      status: "ready",
      profile: {
        primary_role: "X_spectra",
        modality: "spectra",
        technique: "IR",
        target_type: null,
        target_fields: ["species"],
        identity_fields: ["sample_id"],
        group_fields: ["block"],
        ordered_samples: false,
      },
      template_count: 2,
      counts: {
        compatible: 0,
        needs_target: 2,
        needs_source: 0,
        incompatible: 0,
        pending: 0,
        unavailable: 0,
      },
      decisions: [],
      diagnostics: [],
    };
    const selectedReadiness = {
      ...baseReadiness,
      profile: { ...baseReadiness.profile, target_type: "categorical", target_fields: ["species"] },
      counts: { ...baseReadiness.counts, compatible: 1, needs_target: 1 },
      decisions: [
        {
          template_slug: "classification-plsda",
          template_name: "Classification (PLS-DA)",
          category: "classification",
          display_status: "compatible",
          status: "compatible",
          reason_codes: [],
          reasons: [],
        },
        {
          template_slug: "pls-regression",
          template_name: "PLS Regression",
          category: "calibration",
          display_status: "needs_target",
          status: "needs_input",
          reason_codes: ["continuous_target_missing"],
          reasons: [
            {
              code: "continuous_target_missing",
              message: "Requires a numeric target.",
              role: "Y_reference",
            },
          ],
        },
      ],
    };
    mocks.apiPost.mockResolvedValue({ data: selectedReadiness });
    mocks.dataStore.activeExperimentId = 12;
    mocks.dataStore.fileInfo = {
      title: "Categorical collection",
      n_samples: 3,
      n_features: 2,
      data: [
        [1, 2],
        [2, 3],
        [3, 4],
      ],
      y_axis: {
        labels: ["a", "b", "c"],
        sample_table: {
          sample_id: ["a", "b", "c"],
          species: ["alpha", "beta", "gamma"],
          block: [1, 2, 3],
        },
      },
      metadata: { source_collection: sourceCollection(3) },
      analysis_readiness: baseReadiness,
    };

    const loadedContents = mocks.dataStore.fileInfo;
    mocks.dataStore = reactive(mocks.dataStore);
    mocks.dataStore.fileInfo = null;
    const wrapper = mount(DataContentsPanel, {
      props: { analysisSelectionHydrated: false, initialAnalysisTarget: "species" },
    });
    await flushPromises();
    expect(mocks.apiPost).not.toHaveBeenCalled();
    await wrapper.setProps({ analysisSelectionHydrated: true });
    await flushPromises();
    mocks.dataStore.fileInfo = loadedContents;
    await flushPromises();

    expect(mocks.apiPost).toHaveBeenCalledWith(
      "/workflow-templates/compatibility-preview",
      expect.objectContaining({
        analysis_profile: expect.objectContaining({
          target_type: "categorical",
          target_fields: ["species"],
        }),
      }),
    );
    expect(wrapper.get("[aria-label='Analysis readiness']").text()).toContain("1Available");
    expect(wrapper.emitted("analysisChoice")?.at(-1)?.[0]).toEqual(
      expect.objectContaining({
        target: "species",
        targetType: "categorical",
        readiness: selectedReadiness,
      }),
    );
    expect(mocks.apiPost).toHaveBeenCalledTimes(1);
    wrapper.unmount();
    const returned = mount(DataContentsPanel, { props: { initialAnalysisTarget: "species" } });
    await flushPromises();
    expect(mocks.apiPost).toHaveBeenCalledTimes(1);
    expect(returned.emitted("analysisChoice")?.at(-1)?.[0]).toEqual(
      expect.objectContaining({ target: "species", readiness: selectedReadiness }),
    );
    const target = returned
      .get("[aria-label='Analysis readiness']")
      .findAllComponents({ name: "Dropdown" })[0];
    target.vm.$emit("update:modelValue", "");
    await flushPromises();
    expect(mocks.apiPost).toHaveBeenCalledTimes(1);
    expect(returned.emitted("analysisChoice")?.at(-1)?.[0]).toEqual(
      expect.objectContaining({ target: "", readiness: baseReadiness }),
    );
    returned.unmount();
  });

  it("does not approve supervised analysis until one target is explicitly selected", async () => {
    const baseReadiness = {
      schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
      scope: "structural",
      status: "ready",
      profile: {
        primary_role: "X_spectra",
        modality: "spectra",
        technique: "FTIR",
        target_type: "continuous",
        target_fields: ["acetone", "methane"],
        identity_fields: ["sample_id"],
        group_fields: [],
        ordered_samples: false,
      },
      template_count: 1,
      counts: {
        compatible: 1,
        needs_target: 0,
        needs_source: 0,
        incompatible: 0,
        pending: 0,
        unavailable: 0,
      },
      decisions: [],
      diagnostics: [],
    };
    const untargetedReadiness = {
      ...baseReadiness,
      profile: { ...baseReadiness.profile, target_type: null, target_fields: [] },
      counts: { ...baseReadiness.counts, compatible: 0, needs_target: 1 },
      decisions: [
        {
          template_slug: "pls-regression",
          template_name: "PLS Regression",
          category: "calibration",
          display_status: "needs_target",
          status: "needs_input",
          reason_codes: ["continuous_target_missing"],
          reasons: [
            {
              code: "continuous_target_missing",
              message: "Requires a numeric target.",
              role: "Y_reference",
            },
          ],
        },
      ],
    };
    mocks.apiPost.mockResolvedValue({ data: untargetedReadiness });
    mocks.dataStore.activeExperimentId = 143;
    mocks.dataStore.fileInfo = {
      title: "Synthetic_atmospheric-6",
      n_samples: 50,
      n_features: 5401,
      data: [
        [0.1, 0.2],
        [0.2, 0.3],
      ],
      target_context: {
        target_type: "continuous",
        target_names: ["acetone", "methane"],
      },
      metadata: { source_collection: sourceCollection(50) },
      analysis_readiness: baseReadiness,
    };

    const wrapper = mount(DataContentsPanel);
    await flushPromises();

    expect(mocks.apiPost).toHaveBeenCalledWith("/workflow-templates/compatibility-preview", {
      analysis_profile: expect.objectContaining({
        target_type: null,
        target_fields: [],
      }),
    });
    expect(wrapper.emitted("analysisChoice")?.at(-1)?.[0]).toEqual(
      expect.objectContaining({ target: "", targetType: null, readiness: untargetedReadiness }),
    );
  });

  it("does not display untargeted counts when a target preview fails", async () => {
    const failedBaseReadiness = {
      schema_version: "spectra-sherpa-dataset-analysis-readiness/1",
      scope: "structural",
      status: "ready",
      profile: {
        primary_role: "X_spectra",
        modality: "spectra",
        technique: "IR",
        target_type: null,
        target_fields: ["species"],
        identity_fields: ["sample_id"],
        group_fields: [],
        ordered_samples: false,
      },
      template_count: 1,
      counts: {
        compatible: 0,
        needs_target: 1,
        needs_source: 0,
        incompatible: 0,
        pending: 0,
        unavailable: 0,
      },
      decisions: [],
      diagnostics: [],
    };
    mocks.apiPost.mockRejectedValue(new Error("preview service unavailable"));
    mocks.dataStore.activeExperimentId = 12;
    mocks.dataStore.fileInfo = {
      title: "Categorical collection",
      n_samples: 3,
      n_features: 2,
      data: [
        [1, 2],
        [2, 3],
        [3, 4],
      ],
      y_axis: {
        labels: ["a", "b", "c"],
        sample_table: {
          sample_id: ["a", "b", "c"],
          species: ["alpha", "beta", "gamma"],
        },
      },
      metadata: { source_collection: sourceCollection(3) },
      analysis_readiness: failedBaseReadiness,
    };

    const wrapper = mount(DataContentsPanel);
    const target = wrapper
      .get("[aria-label='Analysis readiness']")
      .findAllComponents({ name: "Dropdown" })[0];
    target.vm.$emit("update:modelValue", "species");
    await flushPromises();

    const readiness = wrapper.get("[aria-label='Analysis readiness']");
    expect(readiness.text()).toContain("Target-choice preview unavailable");
    expect(readiness.text()).toContain("preview service unavailable");
    expect(readiness.findAll(".analysis-readiness__count")).toHaveLength(0);
    expect(wrapper.emitted("analysisChoice")?.at(-1)?.[0]).toEqual(
      expect.objectContaining({ target: "species", readiness: null }),
    );
  });

  it("uses aligned axis labels as identity without requiring a duplicate sample_id column", () => {
    mocks.dataStore.fileInfo = {
      title: "Native SPA collection",
      data_role: "X_spectra",
      n_samples: 2,
      n_features: 2,
      x_axis: { data: [2, 1] },
      y_axis: {
        labels: ["JF2_ESL", "JF1_ELF"],
        sample_table: { specimen_id: ["ESL", "ELF"], block: ["JF", "JF"] },
      },
      data: [
        [0.1, 0.2],
        [0.3, 0.4],
      ],
      metadata: { source_collection: sourceCollection(2) },
    };

    const wrapper = mount(DataContentsPanel);
    expect(wrapper.text()).not.toContain("missing required sample_id identity");
    expect(wrapper.get("[aria-label='Collection sample table']").text()).toContain("specimen id");
    expect(wrapper.get("[aria-label='Collection sample table']").text()).toContain("ESL");
  });

  it("refuses reordered collection identity instead of coloring the wrong spectrum", () => {
    mocks.dataStore.fileInfo = {
      title: "Misaligned collection",
      data_role: "X_spectra",
      n_samples: 2,
      n_features: 2,
      x_axis: { data: [2, 1] },
      y_axis: {
        labels: ["A__B1", "B__B1"],
        sample_table: {
          sample_id: ["B__B1", "A__B1"],
          specimen_id: ["B", "A"],
          block: [1, 1],
        },
      },
      data: [
        [0.1, 0.2],
        [0.3, 0.4],
      ],
      metadata: { source_collection: sourceCollection(2) },
    };

    const wrapper = mount(DataContentsPanel);

    expect(wrapper.text()).toContain(
      "Sample-table identity at row 1 does not match its retained spectrum label",
    );
  });

  it("keeps typed sample-table identities distinct", () => {
    mocks.dataStore.fileInfo = {
      title: "Typed collection",
      data_role: "X_spectra",
      n_samples: 4,
      n_features: 1,
      x_axis: { data: [1] },
      y_axis: {
        labels: ["one-number", "one-text", "true-boolean", "true-text"],
        sample_table: {
          sample_id: ["one-number", "one-text", "true-boolean", "true-text"],
          specimen_id: [1, "1", true, "true"],
          block: [1, 1, 1, 1],
        },
      },
      data: [[1], [2], [3], [4]],
      metadata: { source_collection: sourceCollection(4) },
    };

    const wrapper = mount(DataContentsPanel);
    const table = wrapper.get("[aria-label='Collection sample table']");
    expect(table.text()).toContain("one-number");
    expect(table.text()).toContain("one-text");
    expect(table.text()).toContain("true-boolean");
    expect(table.text()).toContain("true-text");
  });

  it("refuses grouping values that cannot cross the JSON wire losslessly", () => {
    mocks.dataStore.fileInfo = {
      title: "Unsafe integer collection",
      data_role: "X_spectra",
      n_samples: 2,
      n_features: 1,
      x_axis: { data: [1] },
      y_axis: {
        labels: ["unsafe-a", "unsafe-b"],
        sample_table: {
          sample_id: ["unsafe-a", "unsafe-b"],
          specimen_id: [Number.MAX_SAFE_INTEGER + 1, Number.MAX_SAFE_INTEGER + 2],
          block: [1, 1],
        },
      },
      data: [[1], [2]],
      metadata: { source_collection: sourceCollection(2) },
    };

    const wrapper = mount(DataContentsPanel);

    expect(wrapper.text()).toContain("non-lossless value");
  });

  it("exposes DSO axis-set inventory and source provenance", () => {
    mocks.dataStore.fileInfo = {
      title: "DSO sample",
      version: "3.0",
      shape: [2, 3],
      ndim: 2,
      data_role: "X_spectra",
      n_samples: 2,
      n_features: 3,
      x_axis: {
        axis_class: "SpectralAxis",
        data: [1000, 900, 800],
        title: "Wavenumber",
        units: "cm-1",
        labels: ["v1", "v2", "v3"],
        alternate_scales: [
          {
            name: "Wavelength",
            values: [10000, 11111.111, 12500],
            title: "Wavelength",
            units: "nm",
            source_set_index: 1,
          },
        ],
        alternate_label_sets: [
          { name: "Channels", values: ["D1", "D2", "D3"], source_set_index: 1 },
        ],
        alternate_title_sets: [
          { name: "Instrument", title: "Detector response", source_set_index: 1 },
        ],
      },
      y_axis: {
        labels: ["sample-1", "sample-2"],
        alternate_label_sets: [
          { name: "Display names", values: ["Lavender", "Lemon"], source_set_index: 1 },
        ],
        class_sets: [
          {
            name: "Species",
            values: [1, 2],
            levels: [
              { code: 1, label: "Lavender" },
              { code: 2, label: "Lemon" },
            ],
            source_set_index: 0,
          },
        ],
      },
      data: [
        [1, 2, 3],
        [4, 5, 6],
      ],
      descriptive: {
        authors: ["Jane Scientist"],
        description: "Imported Eigenvector DataSet Object.",
        created_at: "2026-08-25T00:00:00Z",
      },
      source_identity: { source_format: "matlab-v7.3", object_name: "juice" },
      source_history: { entries: ["Imported"], storage_order: "column-major" },
      layout: { kind: "dso", source_shape: [2, 3], mode_roles: ["samples", "variables"] },
      manifest: { scientific_digest: "f".repeat(64) },
      metadata: {},
    };

    const wrapper = mount(DataContentsPanel);
    expect(wrapper.get("[aria-label='Dataset dimensions and axis sets']").text()).toContain(
      "Coordinate scales2",
    );
    expect(wrapper.get("[aria-label='Dataset dimensions and axis sets']").text()).toContain(
      "Class sets1",
    );
    expect(wrapper.get("[aria-label='Source scientific context and provenance']").text()).toContain(
      "Jane Scientist",
    );
    expect(wrapper.get("[aria-label='Source scientific context and provenance']").text()).toContain(
      "matlab-v7.3",
    );
  });

  it("shows every n-D mode and requires explicit dimension projection", () => {
    mocks.dataStore.fileInfo = {
      title: "Hyperspectral cube",
      shape: [2, 4, 3],
      ndim: 3,
      data_role: "X_spectra",
      n_samples: 2,
      n_features: 3,
      y_axis: { axis_class: "SampleAxis", labels: ["a", "b"] },
      inner_axes: {
        "1": { axis_class: "SpatialAxis", data: [0, 1, 2, 3], title: "Pixel row" },
      },
      x_axis: { axis_class: "SpectralAxis", data: [1000, 900, 800], title: "Wavenumber" },
      data: [
        [
          [1, 2, 3],
          [4, 5, 6],
          [7, 8, 9],
          [10, 11, 12],
        ],
        [
          [13, 14, 15],
          [16, 17, 18],
          [19, 20, 21],
          [22, 23, 24],
        ],
      ],
      metadata: {},
    };

    const wrapper = mount(DataContentsPanel);
    expect(wrapper.text()).toContain("3-D dataset retained");
    expect(wrapper.text()).toContain("selection.dimension_project");
    expect(wrapper.get("[aria-label='Dataset dimensions and axis sets']").text()).toContain(
      "Dimension 1 · Inner mode 1",
    );
    expect(wrapper.findComponent({ name: "PlotlyChart" }).exists()).toBe(false);
  });

  it("refuses malformed sample-table grouping instead of inferring identity from row order", () => {
    mocks.dataStore.fileInfo = {
      title: "Malformed collection",
      data_role: "X_spectra",
      n_samples: 2,
      n_features: 2,
      x_axis: { data: [2, 1] },
      y_axis: {
        labels: ["declared-1", "declared-2"],
        sample_table: { specimen_id: ["only-one"], block: [1, 2] },
      },
      data: [
        [0.1, 0.2],
        [0.3, 0.4],
      ],
      metadata: {},
    };

    const wrapper = mount(DataContentsPanel);

    expect(wrapper.text()).toContain(
      "Sample-table column specimen_id does not match the 2 retained spectra",
    );
  });

  it("bounds the visible sample-table projection", () => {
    const rowCount = 101;
    const columns = Object.fromEntries(
      Array.from({ length: 25 }, (_, column) => [
        `column_${column + 1}`,
        Array.from({ length: rowCount }, (_, row) => `${column + 1}:${row + 1}`),
      ]),
    );
    mocks.dataStore.fileInfo = {
      title: "Large metadata table",
      n_samples: rowCount,
      n_features: 1,
      x_axis: { labels: ["value"] },
      y_axis: { sample_table: columns },
      data: [[1]],
      metadata: {},
    };

    const wrapper = mount(DataContentsPanel);
    const table = wrapper.get("[aria-label='Collection sample table']");

    expect(table.text()).toContain("101 rows · 25 columns");
    expect(table.text()).toContain("Preview omits 1 additional columns and 1 additional rows.");
    expect(table.findAll("thead th")).toHaveLength(24);
    expect(table.findAll("tbody tr")).toHaveLength(100);
  });

  it("shows a bounded preview truthfully and retrieves the complete owner-scoped table", async () => {
    const previewLabels = ["S001", "S052"];
    const scientificIdentity = {
      scientific_collection_schema_version: "spectrasherpa-scientific-collection/2",
      source_manifest_sha256: "a".repeat(64),
      collection_definition_sha256: "b".repeat(64),
      scientific_dataset_projection_sha256: "e".repeat(64),
      scientific_collection_sha256: "c".repeat(64),
    };
    mocks.apiGet.mockResolvedValueOnce({
      data: {
        schema_version: "spectrasherpa-collection-sample-table/1",
        complete: true,
        row_count: 4,
        columns: ["sample_id", "specimen_id", "block"],
        labels: ["S001", "S002", "S003", "S004"],
        sample_table: {
          sample_id: ["S001", "S002", "S003", "S004"],
          specimen_id: ["A", "A", "B", "B"],
          block: [1, 2, 1, 2],
        },
        source_collection: {
          schema_version: "spectrasherpa-source-collection/1",
          file_count: 4,
          manifest_digest: "a".repeat(64),
          ...scientificIdentity,
        },
      },
    } as never);
    mocks.dataStore.fileInfo = {
      dataset_id: "owner-handle",
      title: "Bounded collection",
      data_role: "X_spectra",
      n_samples: 4,
      n_features: 3000,
      x_axis: { data: [3000, 2000, 1000] },
      y_axis: {
        labels: previewLabels,
        sample_table: {
          sample_id: previewLabels,
          specimen_id: ["A", "B"],
          block: [1, 1],
        },
      },
      data: [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
      ],
      metadata: {
        source_collection: { ...sourceCollection(4), ...scientificIdentity },
        preview_shape: [2, 3],
        api_serialization: {
          mode: "bounded_preview",
          full_dataset_handle: "owner-handle",
        },
      },
    };

    const wrapper = mount(DataContentsPanel);
    expect(wrapper.text()).not.toContain("malformed");
    await flushPromises();

    expect(mocks.apiGet).toHaveBeenCalledWith("/datasets/owner-handle/sample-table");
    expect(wrapper.get("[aria-label='Collection sample table']").text()).toContain(
      "Complete · 4 rows · 3 columns",
    );
    expect(wrapper.get("[aria-label='Collection sample table']").text()).toContain("S004");
    wrapper.unmount();
    const returned = mount(DataContentsPanel);
    await flushPromises();
    expect(mocks.apiGet).toHaveBeenCalledTimes(1);
    expect(returned.get("[aria-label='Collection sample table']").text()).toContain("S004");
    returned.unmount();
  });

  it("refuses a complete table whose scientific identity differs from its preview", async () => {
    const scientificIdentity = {
      scientific_collection_schema_version: "spectrasherpa-scientific-collection/2",
      source_manifest_sha256: "a".repeat(64),
      collection_definition_sha256: "b".repeat(64),
      scientific_dataset_projection_sha256: "e".repeat(64),
      scientific_collection_sha256: "c".repeat(64),
    };
    mocks.apiGet.mockResolvedValueOnce({
      data: {
        schema_version: "spectrasherpa-collection-sample-table/1",
        complete: true,
        row_count: 1,
        columns: ["sample_id", "specimen_id", "block"],
        labels: ["S001"],
        sample_table: { sample_id: ["S001"], specimen_id: ["A"], block: [1] },
        source_collection: {
          schema_version: "spectrasherpa-source-collection/1",
          file_count: 1,
          manifest_digest: "a".repeat(64),
          ...scientificIdentity,
          scientific_collection_sha256: "d".repeat(64),
        },
      },
    } as never);
    mocks.dataStore.fileInfo = {
      dataset_id: "owner-handle",
      title: "Bounded collection",
      data_role: "X_spectra",
      n_samples: 1,
      n_features: 3000,
      x_axis: { data: [3000] },
      y_axis: {
        labels: ["S001"],
        sample_table: { sample_id: ["S001"], specimen_id: ["A"], block: [1] },
      },
      data: [[0.1]],
      metadata: {
        source_collection: { ...sourceCollection(1), ...scientificIdentity },
        preview_shape: [1, 1],
        api_serialization: { mode: "bounded_preview", full_dataset_handle: "owner-handle" },
      },
    };

    const wrapper = mount(DataContentsPanel);
    await flushPromises();

    expect(wrapper.text()).toContain("retrieved complete sample table failed identity validation");
  });

  it("makes an unsupported collection schema visible", () => {
    mocks.dataStore.fileInfo = {
      title: "Unsupported collection",
      n_samples: 1,
      n_features: 1,
      x_axis: { labels: ["value"] },
      data: [[1]],
      metadata: {
        source_collection: { ...sourceCollection(1), schema_version: "unknown/9" },
      },
    };

    const wrapper = mount(DataContentsPanel);
    expect(wrapper.text()).toContain("project collection identity is incomplete or unsupported");
  });

  it("shows an auditable save receipt and warns that existing workflows remain pinned", async () => {
    mocks.dataStore.activeExperimentId = 12;
    mocks.dataStore.activeFileId = 41;
    mocks.dataStore.activeFilePath = "raw/corn.mat";
    mocks.dataStore.fileInfo = {
      title: "Corn M5",
      n_samples: 80,
      n_features: 700,
      data: [[0.1, 0.2]],
      metadata: { labels: ["sample-1"] },
      analysis_binding: {
        revision: "b".repeat(64),
        sample_table_file_id: 65,
        selected_target: "moisture",
        target_type: "continuous",
      },
    };
    mocks.dataStore.uploadFile.mockResolvedValue({
      id: 73,
      file_path: "preprocessed/corn-sample-table.csv",
      stage: "preprocessed",
      created_at: "2026-08-20T00:00:00Z",
    });
    const wrapper = mount(DataContentsPanel);
    const editor = wrapper.findComponent({ name: "SampleTableEditor" });

    editor.vm.$emit("save", {
      file: new File(["sample table"], "corn-sample-table.csv", { type: "text/csv" }),
      expectedRevision: "b".repeat(64),
      targetColumn: "moisture",
      targetType: "continuous",
      summary: {
        sourceFileId: 41,
        totalSamples: 80,
        includedSamples: 50,
        selectedTargetValues: 50,
        targetColumns: [{ name: "moisture", type: "continuous" }],
        targetValueCounts: { moisture: 50 },
        groupColumns: ["batch"],
        plateFormatId: "plate-96",
        plateFormatLabel: "96-well plate",
        assignedWells: 80,
        plateCount: 1,
      },
    });
    await flushPromises();

    expect(mocks.dataStore.uploadFile).toHaveBeenCalledWith(
      12,
      expect.any(File),
      "preprocessed",
      expect.objectContaining({ refresh: false }),
    );
    expect(mocks.dataStore.bindDatasetAnalysisCsv).toHaveBeenCalledWith({
      sourceFileId: 41,
      sampleTableFileId: 73,
      expectedRevision: "b".repeat(64),
      selectedTarget: "moisture",
      targetType: "continuous",
    });
    expect(mocks.dataStore.selectExperiment).toHaveBeenCalledWith(12);
    expect(mocks.dataStore.fetchCatalog).toHaveBeenCalledOnce();
    expect(mocks.dataStore.inspectFile).toHaveBeenCalledWith(41, "raw/corn.mat", 12);
    expect(wrapper.text()).toContain("Measured samples saved");
    expect(wrapper.text()).toContain("preprocessed/corn-sample-table.csv");
    expect(wrapper.text()).toContain("file #73");
    expect(wrapper.text()).toContain("50/80 included");
    expect(wrapper.text()).toContain("50 moisture values");
    expect(wrapper.text()).toContain("80 wells on 1 96-well plate");
    expect(wrapper.text()).toContain("moisture (continuous; 50 values)");
    expect(wrapper.text()).toContain("batch");
    expect(wrapper.text()).toContain("Existing workflows remain bound to their previous file IDs");
  });
});
