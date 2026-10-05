// GSC-13 acceptance: local display populations remain explicit.
import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, vi } from "vitest";
import DatasetSourcePreview from "@/views/data/DatasetSourcePreview.vue";
const { fetchDataMatrix } = vi.hoisted(() => ({ fetchDataMatrix: vi.fn() }));
vi.mock("@/stores/data", () => ({ useDataStore: () => ({ fetchDataMatrix }) }));
describe("Local source preview transformations", () => {
  it.each([
    { rows: 80, cols: 2, spectral: true, expected: 50 },
    { rows: 4, cols: 45, spectral: false, expected: 40 },
    { rows: 4, cols: 2, spectral: false, expected: 2 },
    { rows: 80, cols: 2, spectral: true, expected: 50, totalRows: 800 },
  ])(
    "GSC-13: local crop is disclosed for $rows by $cols source",
    async ({ rows, cols, spectral, expected, totalRows = rows }) => {
      fetchDataMatrix.mockResolvedValue({
        kind: "dataset",
        shape: [rows, cols],
        rank: 2,
        shape_label: `${rows} × ${cols}`,
        dimension_roles: ["sample", "feature"],
        projection_required: false,
        dataset_preview: { version: "3.0" },
        x_title: "Feature",
        x_units: "",
        y_title: "Value",
        data_role: spectral ? "X_spectra" : "X_features",
        is_spectra: spectral,
        row_start: 0,
        col_start: 0,
        rows_shown: rows,
        cols_shown: cols,
        total_rows: totalRows,
        total_cols: cols,
        truncated: totalRows !== rows,
        row_labels: Array.from({ length: rows }, (_, i) => `S${i}`),
        col_labels: Array.from({ length: cols }, (_, i) => `${500 + i}`),
        matrix: Array.from({ length: rows }, (_, i) =>
          Array.from({ length: cols }, (_, j) =>
            !spectral && ((i === 0 && j === 0) || (i > 0 && i < 3 && j === 1)) ? null : i + j,
          ),
        ),
        target: null,
        stats: {
          per_column: [],
          summary: {
            n_samples: rows,
            n_features: cols,
            global_min: 0,
            global_max: rows + cols - 2,
            global_mean: 1,
            total_missing_pct: 0,
          },
        },
      });
      const w = mount(DatasetSourcePreview, {
        props: {
          title: "Synthetic complete source",
          sourceRef: { kind: "staged", staging_id: "a".repeat(32), asset_id: "synthetic" },
        },
        global: {
          stubs: {
            InputText: true,
            Dropdown: true,
            ProgressSpinner: true,
            PlotlyChart: true,
            DataMatrixGrid: true,
            DataStatsTable: true,
          },
        },
      });
      await flushPromises();
      expect((w.vm as any).previewPlotData).toHaveLength(expected);
      expect(w.find(".truncate-note").exists()).toBe(totalRows !== rows);
      expect(w.get(".plot-population-disclosure").text()).toContain(`${totalRows} source rows`);
      expect(w.get(".plot-population-disclosure").text()).toContain(
        spectral
          ? `first ${expected} of ${rows} available preview rows`
          : `first ${expected} of ${cols} preview features`,
      );
      expect(w.text()).toContain(`first ${expected}`);
      if (!spectral) {
        expect((w.vm as any).previewPlotData[0].name).toContain("(n=3)");
        expect((w.vm as any).previewPlotData[1].name).toContain("(n=2)");
        expect(w.get(".plot-population-disclosure").text()).toContain(
          "3 missing/nonfinite cells omitted",
        );
      }
      w.unmount();
    },
  );
});
