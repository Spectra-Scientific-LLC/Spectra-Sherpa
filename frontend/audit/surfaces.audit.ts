// Diagnostic characterizations of the pinned baseline; these intentionally
// assert observed defects. They are excluded from the product regression suite.
import { mount } from "@vue/test-utils";
import { describe, it, expect, vi, afterEach } from "vitest";
import { nextTick } from "vue";
import oofFixture from "./oof-fixture.json";
import DataTableModal from "@/views/workflow-builder/modals/DataTableModal.vue";
import DataQualityPanel from "@/views/data/DataQualityPanel.vue";
import QuickPlotModal from "@/views/workflow-builder/modals/QuickPlotModal.vue";
import DataMatrixGrid from "@/views/data/DataMatrixGrid.vue";
import {
  buildCategoryCountsPlot,
  buildClassificationResponsesPlot,
  buildOutOfFoldEvidencePlot,
  buildConfusionMatrixPlot,
} from "@/utils/scientificPlots";

const stubs = {
  Dialog: { template: "<div><slot /></div>" },
  Dropdown: true,
  InputText: true,
  Button: true,
  DataTable: true,
  Column: true,
  PlotlyChart: true,
  Paginator: true,
  Tag: true,
};
const mounted: any[] = [];
function table(nodeOutput: any) {
  const w = mount(DataTableModal, {
    props: { modelValue: true, nodeOutput, nodeType: "output.plot", nodeLabel: "Synthetic audit" },
    global: { stubs },
  });
  mounted.push(w);
  return w;
}
async function csv(w: any) {
  let captured: Blob | undefined;
  vi.spyOn(URL, "createObjectURL").mockImplementation((b: any) => {
    captured = b;
    return "blob:audit";
  });
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  w.vm.exportCSV();
  return captured!.text();
}
afterEach(() => {
  mounted.splice(0).forEach((w) => w.unmount());
  vi.restoreAllMocks();
});
describe("Pinned GUI authority audit observations (not acceptance tests)", () => {
  it("GSC-01: ordinary multitrace table and CSV retain only the first trace", async () => {
    const w = table({
      data: [
        { type: "scatter", name: "A", x: [500, 501], y: [1, 2] },
        { type: "scatter", name: "B", x: [500, 501], y: [31, 32] },
      ],
      metadata: {},
    });
    expect(w.vm.displayedData).toEqual([
      [500, 1],
      [501, 2],
    ]);
    expect(await csv(w)).not.toContain("31");
  });
  it("GSC-02: first 100 of 120 rows suppresses the truncation warning", () => {
    const w = table({ data: Array.from({ length: 120 }, (_, i) => [i]), metadata: {} });
    expect(w.vm.tableData).toHaveLength(100);
    expect(w.text()).not.toContain("Showing first");
    expect(w.vm.dataShape.rows).toBe(120);
  });
  it("GSC-02: search cannot find a sample outside the initial 100 rows", async () => {
    const w = table({
      data: Array.from({ length: 120 }, (_, i) => [i]),
      metadata: { sample_labels: Array.from({ length: 120 }, (_, i) => `S${i}`) },
    });
    w.vm.searchQuery = "S119";
    await nextTick();
    expect(w.vm.tableData).toHaveLength(0);
  });
  it("GSC-03: CSV rounds distinct physical coordinates into duplicate headers", async () => {
    const w = table({ data: [[1, 2]], metadata: { wavenumbers: [500.001, 500.004] } });
    expect((await csv(w)).split("\n")[0]).toBe("Index,500.00,500.00");
  });
  it("GSC-03: feature-table CSV drops authoritative feature names", async () => {
    const w = table({
      data: [[1, 2]],
      metadata: { feature_names: ["mass", "temperature"], data_role: "X_features" },
    });
    expect((await csv(w)).split("\n")[0]).toBe("Index,Col_1,Col_2");
  });
  it("GSC-04: categorical class names are counted as multiple target properties", () => {
    const w = mount(DataQualityPanel, {
      props: {
        datasetDict: {
          data: [[1], [2], [3]],
          n_samples: 3,
          n_features: 1,
          target: ["A", "B", "C"],
          target_context: { target_type: "categorical", class_names: ["A", "B", "C"] },
          metadata: {},
        } as any,
      },
      global: { stubs },
    });
    mounted.push(w);
    expect(w.text()).toContain("0 / 3");
    expect(w.text()).toContain("all 3 target properties");
    expect(w.text()).toContain("Multi-target regression");
  });
  it("GSC-05 provisional generic renderer (not DBSCAN): sentinel-coded categories receive a normal Class Assignment Counts plot", () => {
    const p = buildCategoryCountsPlot([-1, -1, -1]);
    expect(p.data[0].x).toEqual(["-1"]);
    expect(p.layout.title.text).toBe("Class Assignment Counts");
  });
  it("GSC-06 malformed input: missing response class authority is replaced with invented class names", () => {
    const p = buildClassificationResponsesPlot([[0.1, 0.9]], {});
    expect(p.data[0].x).toEqual(["Class 1", "Class 2"]);
  });
  it("GSC-06 malformed input: confusion-matrix class mismatch is also replaced without refusal", () => {
    const p = buildConfusionMatrixPlot(
      [
        [2, 0],
        [0, 3],
      ],
      { classes: ["A"] },
    );
    expect(p.data[0].x).toEqual(["Class 1", "Class 2"]);
  });
  it("GSC-07: OOF plot omits retained fold assignments and OOF claim from the figure", () => {
    const p = buildOutOfFoldEvidencePlot(oofFixture);
    expect(p.data[0].x).toEqual([1, 2, 3, 4]);
    expect(p.data[0].text).toBeUndefined();
    expect(p.data[0].customdata).toBeUndefined();
    expect(p.layout.xaxis.title).toBe("Actual");
    expect(p.layout.title.text).toBe("Predicted vs Actual");
  });
  it("GSC-08 historical/malformed input: missing values blank the entire typed response plot with generic advice", () => {
    const w = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        embedded: true,
        nodeType: "model.pls_da",
        nodeLabel: "Synthetic missing response",
        nodeOutput: {
          data: [[null, null]],
          presentation_value: [[null, null]],
          metadata: {
            scientific_presentation: {
              schema_version: "spectrasherpa-node-presentation/1",
              contract_digest: "a".repeat(64),
              presentation_id: "responses",
              source_port: "responses",
              source_ports: ["responses"],
              modes: ["plot", "table"],
              kind: "classification_responses",
            },
          },
        },
      },
      global: { stubs },
    });
    mounted.push(w);
    expect(w.text()).toContain("No data to display");
    expect(w.text()).toContain("No retained table is available");
  });
  it("GSC-09: PNG button silently returns when no global Plotly is installed", () => {
    const w = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        embedded: true,
        nodeType: "output.plot",
        nodeLabel: "Synthetic",
        nodeOutput: { data: [], metadata: {} },
      },
      global: { stubs },
    });
    mounted.push(w);
    expect((window as any).Plotly).toBeUndefined();
    const before = w.text();
    w.vm.downloadPlot();
    expect(w.text()).toBe(before);
  });
  it("GSC-10 contextual gap: matrix displays null cells as blanks without a legend", () => {
    const w = mount(DataMatrixGrid, {
      props: {
        matrix: {
          rows_shown: 1,
          cols_shown: 3,
          total_rows: 1,
          total_cols: 3,
          truncated: false,
          row_labels: ["A"],
          col_labels: ["x", "y", "z"],
          matrix: [[null, null, null]],
        } as any,
      },
    });
    mounted.push(w);
    expect(w.findAll("tbody td").map((c) => c.text())).toEqual(["", "", ""]);
    expect(w.text()).not.toMatch(/missing|nonfinite|invalid/i);
  });
  it("GSC-14: typed spectral-dataset overlay silently takes the first 50 of 80 samples", () => {
    const data = Array.from({ length: 80 }, (_, i) => [i, i + 1]);
    const w = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        embedded: true,
        nodeType: "data.source",
        nodeLabel: "80 spectra",
        nodeOutput: {
          data,
          presentation_value: { data },
          metadata: {
            data_role: "X_spectra",
            wavenumbers: [500, 501],
            sample_labels: Array.from({ length: 80 }, (_, i) => `S${i}`),
            scientific_presentation: {
              schema_version: "spectrasherpa-node-presentation/1",
              contract_digest: "a".repeat(64),
              presentation_id: "data",
              source_port: "data",
              source_ports: ["data"],
              modes: ["plot", "table"],
              kind: "spectral_dataset",
            },
          },
        },
      },
      global: { stubs },
    });
    mounted.push(w);
    expect(w.vm.plotData).toHaveLength(50);
    expect(w.find(".plot-sampling-disclosure").exists()).toBe(false);
  });
});
