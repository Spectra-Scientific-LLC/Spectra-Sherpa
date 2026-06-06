/* eslint-disable vue/one-component-per-file */
import { mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DataContentsPanel from "@/views/data/DataContentsPanel.vue";

const mocks = vi.hoisted(() => ({
  dataStore: {
    fileInfoLoading: false,
    fileInfoError: null as string | null,
    catalogDatasetLoading: false,
    catalogDatasetError: null as string | null,
    catalogDatasetInfo: null,
    activeFileId: null as number | null,
    activeFilePath: null as string | null,
    fileInfo: null as Record<string, unknown> | null,
    dataStoryText: null,
    dataStoryMemoryScopes: [],
    dataStoryLoading: false,
    dataStoryContext: "",
    generateDataStory: vi.fn(),
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
  default: defineComponent({ name: "Dropdown", template: "<input />" }),
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
  default: defineComponent({ name: "DataQualityPanel", template: "<div data-testid='data-quality' />" }),
}));

function resetDataStore() {
  mocks.dataStore.fileInfoLoading = false;
  mocks.dataStore.fileInfoError = null;
  mocks.dataStore.catalogDatasetLoading = false;
  mocks.dataStore.catalogDatasetError = null;
  mocks.dataStore.catalogDatasetInfo = null;
  mocks.dataStore.activeFileId = null;
  mocks.dataStore.activeFilePath = null;
  mocks.dataStore.fileInfo = null;
  mocks.dataStore.dataStoryText = null;
  mocks.dataStore.dataStoryMemoryScopes = [];
  mocks.dataStore.dataStoryLoading = false;
  mocks.dataStore.dataStoryContext = "";
}

describe("DataContentsPanel", () => {
  beforeEach(() => {
    resetDataStore();
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

    expect(wrapper.text()).toContain("Dataset Metadata");
    expect(wrapper.text()).toContain("Files");
    expect(wrapper.text()).toContain("3");
    expect(wrapper.text()).toContain("178");
    expect(wrapper.text()).toContain("13");
    expect(wrapper.find("[data-testid='data-quality']").exists()).toBe(true);
  });

  it("plots two-column library CSV contents as one spectrum using the spectral x-axis", () => {
    mocks.dataStore.activeFileId = 7;
    mocks.dataStore.activeFilePath = "raw/library_hitran_Methane.csv";
    mocks.dataStore.fileInfo = {
      title: "library_hitran_Methane",
      data_role: "X_spectra",
      n_samples: 1,
      n_features: 3,
      x_axis: {
        data: [600, 600.5, 601],
        labels: ["600", "600.5", "601"],
        title: "Wavenumber",
        units: "cm-1",
      },
      y_axis: { labels: ["Methane"] },
      data: [[0.01, 0.2, 0.03]],
      metadata: {
        data_role: "X_spectra",
        is_spectra: true,
        x_title: "Wavenumber",
        x_units: "cm-1",
        data_quantity: "Absorbance coefficient",
      },
    };

    const wrapper = mount(DataContentsPanel);
    const chart = wrapper.findComponent({ name: "PlotlyChart" });

    expect(wrapper.text()).not.toContain("Property Distributions");
    expect(chart.props("layout")).toEqual(expect.objectContaining({
      title: expect.objectContaining({ text: "Spectra Preview" }),
    }));
    expect(chart.props("data")).toEqual([
      expect.objectContaining({
        x: [600, 600.5, 601],
        y: [0.01, 0.2, 0.03],
        mode: "lines",
      }),
    ]);
  });
});
