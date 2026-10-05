import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DatasetSourcePreview from "@/views/data/DatasetSourcePreview.vue";

const mocks = vi.hoisted(() => ({
  fetchDataMatrix: vi.fn(),
}));

vi.mock("@/stores/data", () => ({
  useDataStore: () => ({ fetchDataMatrix: mocks.fetchDataMatrix }),
}));

vi.mock("primevue/inputtext", () => ({
  default: defineComponent({ name: "InputText", template: "<input />" }),
}));

vi.mock("primevue/dropdown", () => ({
  default: defineComponent({ name: "Dropdown", template: "<select />" }),
}));

vi.mock("primevue/progressspinner", () => ({
  default: defineComponent({ name: "ProgressSpinner", template: "<div />" }),
}));

vi.mock("@/components/PlotlyChart.vue", () => ({
  default: defineComponent({ name: "PlotlyChart", template: "<div data-testid='plot' />" }),
}));

vi.mock("@/views/data/DataMatrixGrid.vue", () => ({
  default: defineComponent({
    name: "DataMatrixGrid",
    template: "<div data-testid='matrix-grid' />",
  }),
}));

vi.mock("@/views/data/DataStatsTable.vue", () => ({
  default: defineComponent({
    name: "DataStatsTable",
    template: "<div data-testid='stats-table' />",
  }),
}));

describe("DatasetSourcePreview n-D projection boundary", () => {
  beforeEach(() => {
    mocks.fetchDataMatrix.mockReset();
  });

  it("explains registered provider acquisition without calling an unsupported preview source", async () => {
    const wrapper = mount(DatasetSourcePreview, {
      props: {
        title: "Eigenvector Corn M5",
        sourceRef: null,
        acquisitionRequired: true,
      },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("Eigenvector Corn M5");
    expect(wrapper.text()).toContain("Provider file required");
    expect(wrapper.text()).toContain("Import the downloaded provider ZIP");
    expect(mocks.fetchDataMatrix).not.toHaveBeenCalled();
  });

  it("keeps a native n-D source shape and requires explicit projection", async () => {
    mocks.fetchDataMatrix.mockResolvedValue({
      kind: "nd_dataset",
      shape: [2, 3, 4],
      rank: 3,
      shape_label: "2 × 3 × 4",
      dimension_roles: ["sample", "mode-2", "feature"],
      projection_required: true,
      projection_message: "Use Dimension Projection before applying 2-D operations.",
      dataset_preview: { version: "3.0" },
      x_title: "Wavenumber",
      x_units: "cm-1",
      y_title: "Absorbance",
      data_role: "X_spectra",
      data_modality: "spectral_cube",
      is_spectra: true,
      row_start: 0,
      col_start: 0,
      rows_shown: 0,
      cols_shown: 0,
      total_rows: 2,
      total_cols: 4,
      truncated: false,
      row_labels: [],
      col_labels: [],
      matrix: [],
      target: null,
      stats: {
        per_column: [],
        summary: {
          n_samples: 2,
          n_features: 4,
          global_min: 0,
          global_max: 23,
          global_mean: 11.5,
          total_missing_pct: 0,
        },
      },
    });

    const wrapper = mount(DatasetSourcePreview, {
      props: {
        title: "PLS Toolbox image DSO",
        sourceRef: { kind: "staged", staging_id: "a".repeat(32), asset_id: "calibration" },
      },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("2 × 3 × 4");
    expect(wrapper.text()).toContain("Native 3-D dataset");
    expect(wrapper.text()).toContain("Use Dimension Projection before applying 2-D operations.");
    expect(wrapper.text()).toContain("mode-2");
    expect(wrapper.text()).toContain(
      "Project explicit inner dimensions before requesting a 2-D graph.",
    );
    expect(wrapper.find("[data-testid='matrix-grid']").exists()).toBe(false);
    expect(wrapper.find("[data-testid='stats-table']").exists()).toBe(false);
    expect(wrapper.find("[data-testid='plot']").exists()).toBe(false);
  });

  it("shows the supplier-neutral CSV interpretation selected by inspection", async () => {
    mocks.fetchDataMatrix.mockResolvedValue({
      kind: "dataset",
      shape: [1, 3],
      rank: 2,
      shape_label: "1 × 3",
      dimension_roles: ["sample", "feature"],
      projection_required: false,
      dataset_preview: { version: "3.0" },
      x_title: "Wavenumber",
      x_units: "cm-1",
      y_title: "Absorbance",
      data_role: "X_spectra",
      data_modality: "spectrum",
      is_spectra: true,
      row_start: 0,
      col_start: 0,
      rows_shown: 1,
      cols_shown: 3,
      total_rows: 1,
      total_cols: 3,
      truncated: false,
      row_labels: ["supplier-export"],
      col_labels: ["4000", "3999", "3998"],
      matrix: [[0.1, 0.2, 0.3]],
      target: null,
      stats: {
        per_column: [],
        summary: {
          n_samples: 1,
          n_features: 3,
          global_min: 0.1,
          global_max: 0.3,
          global_mean: 0.2,
          total_missing_pct: 0,
        },
      },
    });

    const wrapper = mount(DatasetSourcePreview, {
      props: {
        title: "Supplier CSV",
        sourceRef: { kind: "staged", staging_id: "b".repeat(32) },
        csvPlan: {
          layout: "headerless_two_column_spectrum",
          layout_label: "Headerless two-column spectrum",
          confidence: "high",
          role_sequence: "WY",
          shape: { rows: 3, columns: 2, samples: 1, features: 3 },
          axis: { column: "column 1", title: "Wavenumber", units: "cm-1" },
          target: {},
          columns: [],
          warnings: ["Confirm the interpretation before import."],
          recommended_layout: "headerless_two_column_spectrum",
          layout_options: [
            {
              value: "headerless_two_column_spectrum",
              label: "Headerless X/Y spectrum",
              description: "One coordinate and one signal column.",
            },
          ],
          requires_confirmation: true,
          delimiter: ",",
          decimal: ".",
        },
      },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("CSV Inspector");
    expect(wrapper.text()).toContain("supplier-neutral interpretation");
    expect(wrapper.text()).toContain("Headerless two-column spectrum");
  });
});
