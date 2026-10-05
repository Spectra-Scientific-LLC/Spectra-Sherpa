import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { nextTick } from "vue";

import QuickPlotModal from "@/views/workflow-builder/modals/QuickPlotModal.vue";
import { buildNodeOutput } from "@/utils/nodeOutput";
import { scientificPlotRefusal } from "@/utils/scientificPlotState";

/* eslint-disable @typescript-eslint/no-explicit-any */

describe("QuickPlotModal", () => {
  const scientificPresentation = (kind: string) => ({
    schema_version: "spectrasherpa-node-presentation/1",
    contract_digest: "a".repeat(64),
    presentation_id: "result",
    source_port: "result",
    source_ports: ["result"],
    modes: ["plot", "table"],
    kind,
  });

  const globalStubs = {
    Dialog: { template: "<div><slot /></div>" },
    Dropdown: true,
    Button: true,
    DataTable: true,
    Column: true,
    PlotlyChart: true,
    Paginator: true,
  };

  it("selects table columns without reporting a mixed-unit overall range", async () => {
    const wrapper = mount(QuickPlotModal, { props: {
      modelValue: true, nodeType: "output.data_table", nodeLabel: "Peaks",
      nodeOutput: { data: [[1200, 3], [null, 4]], metadata: {
        column_names: ["peak_position_1", "magnitude_at_group_position_1"],
        column_units: { peak_position_1: "nm" },
      } },
    }, global: { stubs: globalStubs } });
    const vm = wrapper.vm as any;
    expect(vm.availablePlots).toHaveLength(2);
    expect(wrapper.text()).toContain("Column");
    expect(wrapper.text()).not.toContain("Range:");
    expect(vm.displayPlotData[0].y).toEqual([1200, null]);
    vm.selectedPlotKey = "table_column:1";
    await nextTick();
    expect(vm.displayPlotData[0].y).toEqual([3, 4]);
    wrapper.unmount();
  });

  it.each(["preprocess.scale", "baseline.asls", "normalize.vector", "smooth.savgol", "time_series.resample", "selection.variable_select", "data.filter_samples"])("stacks immediate input and shape-changing output for %s", async (nodeType) => {
    const input = { value: { data: [[1, 2, 3], [4, 5, 6]],
      x_axis: { data: [1200, 1100, 1000], title: "Wavenumber", units: "cm-1" },
      y_axis: { labels: ["input A", "input B"] } } };
    const wrapper = mount(QuickPlotModal, {
      props: { modelValue: true, nodeType, nodeLabel: "Transform", nodeInputs: { X: input },
        nodeOutput: { data: [[20, 30]], presentation_value: { data: [[20, 30]],
          x_axis: { data: [1100, 1000], title: "Wavenumber", units: "cm-1" },
          y_axis: { labels: ["input B"] } }, metadata: { scientific_presentation: scientificPresentation("spectral_dataset") } } },
      global: { stubs: globalStubs },
    });
    const vm = wrapper.vm as any;
    expect(vm.availablePlots.map((p: any) => p.label)).toEqual(["Data Overlay", "Heatmap"]);
    expect(vm.displayPlotData.map((t: any) => [t.xaxis, t.name, t.x, t.y])).toEqual([
      ["x", "input A", [1200, 1100, 1000], [1, 2, 3]],
      ["x", "input B", [1200, 1100, 1000], [4, 5, 6]],
      ["x2", "input B", [1100, 1000], [20, 30]],
    ]);
    expect(vm.displayPlotLayout.xaxis.matches).toBeUndefined();
    expect(vm.displayPlotLayout.xaxis.title).toBe("Wavenumber (cm-1)");
    vm.selectedPlotKey = "spectra_heatmap";
    await nextTick();
    expect(vm.displayPlotData.map((t: any) => [t.type, t.x, t.y, t.z])).toEqual([
      ["heatmap", [1200, 1100, 1000], ["input A", "input B"], [[1, 2, 3], [4, 5, 6]]],
      ["heatmap", [1100, 1000], ["input B"], [[20, 30]]],
    ]);
    expect(vm.displayPlotLayout.yaxis.domain[0]).toBeGreaterThan(vm.displayPlotLayout.yaxis2.domain[1]);
    wrapper.unmount();
  });

  it.each(["transfer.ds", "transfer.pds", "transfer.sws"])("compares the transformed secondary input for %s", (nodeType) => {
    const wrapper = mount(QuickPlotModal, { props: { modelValue: true, nodeType, nodeLabel: "Transfer",
      nodeInput: { data: [[999]] }, nodeInputs: { X_primary: { data: [[999]] }, X_secondary: { data: [[1]] } },
      nodeOutput: { data: [[2]], metadata: {} } }, global: { stubs: globalStubs } });
    expect((wrapper.vm as any).displayPlotData.map((t: any) => t.y)).toEqual([[1], [2]]);
    wrapper.unmount();
  });

  it("does not substitute reference data or output for an unavailable immediate X input", async () => {
    const wrapper = mount(QuickPlotModal, { props: { modelValue: true, nodeType: "preprocess.align", nodeLabel: "Align",
      nodeInput: { data: [[999]] }, nodeInputs: { X: null, reference: { data: [[999]] } },
      nodeOutput: { data: [[1, 2]], metadata: {} } }, global: { stubs: globalStubs } });
    const vm = wrapper.vm as any;
    for (const key of ["spectra_overlay", "spectra_heatmap"]) {
      vm.selectedPlotKey = key;
      await nextTick();
      expect(wrapper.text()).toContain("Comparison unavailable: immediate node input");
      expect(vm.displayPlotData).toHaveLength(1);
      expect(vm.displayPlotData[0].xaxis).toBe("x2");
    }
    wrapper.unmount();
  });

  it("discloses independent sampling and preserves feature and masked sample labels", async () => {
    const data = Array.from({ length: 60 }, (_, i) => [i, i + 1]);
    const wrapper = mount(QuickPlotModal, { props: { modelValue: true, nodeType: "preprocess.scale", nodeLabel: "Scale",
      nodeInputs: { X: { value: { data, x_axis: { labels: ["a", "b"] }, y_axis: { labels: data.map((_, i) => `s${i}`), include_mask: data.map((_, i) => i !== 0) } }, metadata: { data_role: "X_features" } } },
      nodeOutput: { data: [[2, 3]], metadata: { data_role: "X_features", feature_names: ["a", "b"], sample_labels: ["s1"] } } }, global: { stubs: globalStubs } });
    const vm = wrapper.vm as any;
    expect(wrapper.text()).toContain("50 of 59 active rows shown; first 50 rows, 9 unplotted; 1 rows");
    expect(wrapper.text()).toContain("Preprocessed: 1 of 1 active rows shown");
    expect(vm.displayPlotData[0].name).toBe("s1");
    expect(vm.displayPlotData[0].x).toEqual(["a", "b"]);
    vm.selectedPlotKey = "spectra_heatmap";
    await nextTick();
    expect(vm.displayPlotData[0].y).toHaveLength(59);
    expect(vm.displayPlotData[0].x).toEqual(["a", "b"]);
    expect(wrapper.text()).not.toContain("unplotted");
    wrapper.unmount();
  });

  it("discloses sampled output.plot traces and labels its table as plotted data", async () => {
    const traces = Array.from({ length: 50 }, (_, index) => ({
      type: "scatter", name: `sample-${index}`, x: [600, 602], y: [index, index + 1],
    }));
    const metadata = { n_samples: 460, n_features: 2, shown_traces: 50, subsampled: true };
    const wrapper = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        nodeType: "output.plot",
        nodeLabel: "Spectral Plot",
        nodeOutput: buildNodeOutput(
          { visualization: { plot_type: "spectra", data: traces, layout: {}, metadata } },
          [{ name: "visualization", type_ref: "spectrasherpa://types/Visualization/1.0", required: true, label: "Plot" }],
        ),
      },
      global: { stubs: globalStubs },
    });

    const disclosure = wrapper.find(".plot-sampling-disclosure");
    expect(disclosure.text()).toContain("50 of 460 source spectra (10.9%)");
    expect(disclosure.text()).toContain("410 are unplotted");
    expect(disclosure.text()).toContain("evenly spaced source rows");
    expect(wrapper.html()).toContain("View Plotted Data");
    expect((wrapper.vm as any).dataPreview).toHaveLength(50);

    (wrapper.vm as any).toggleViewMode();
    await nextTick();
    expect((wrapper.vm as any).dataPreviewSummary).toBe(
      "50 plotted traces of 460 source spectra; full source matrix is not in this view",
    );
    wrapper.unmount();
  });

  it("does not invent a sampling disclosure for an unsampled plot", () => {
    const wrapper = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        nodeType: "output.plot",
        nodeLabel: "Spectral Plot",
        nodeOutput: { data: [{ x: [600], y: [1] }], metadata: { n_samples: 1, shown_traces: 1 } },
      },
      global: { stubs: globalStubs },
    });
    expect(wrapper.find(".plot-sampling-disclosure").exists()).toBe(false);
    expect(wrapper.html()).toContain("View Data");
    wrapper.unmount();
  });

  it("describes sampled feature-table rows as samples rather than spectra", () => {
    const traces = Array.from({ length: 50 }, (_, index) => ({
      type: "bar", name: `machine-${index}`, x: ["sensor-a"], y: [index],
    }));
    const metadata = { n_samples: 80, n_features: 1, shown_traces: 50, subsampled: true, data_role: "X_features" };
    const wrapper = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        nodeType: "output.plot",
        nodeLabel: "Feature Plot",
        nodeOutput: {
          data: traces,
          metadata,
          ports: { visualization: { value: { plot_type: "features", data: traces, layout: {}, metadata } } },
        },
      },
      global: { stubs: globalStubs },
    });

    const disclosure = wrapper.find(".plot-sampling-disclosure").text();
    expect(disclosure).toContain("50 of 80 source samples (62.5%)");
    expect(disclosure).not.toContain("spectra");
    wrapper.unmount();
  });

  it("uses the shared paginated table for a table-only retained matrix", async () => {
    const wrapper = mount(QuickPlotModal, {
      props: { embedded: true, tableOnly: true, modelValue: true, nodeType: "model.load_apply", nodeLabel: "Applied result",
        nodeOutput: { data: [[2.5], [4]], presentation_value: [[2.5], [4]], metadata: {
          sample_labels: ["sample-a", "sample-b"], scientific_presentation: { ...scientificPresentation("numeric_matrix"), modes: ["table"] },
        } } },
      global: { stubs: globalStubs },
    });
    const vm = wrapper.vm as any;
    expect(vm.viewMode).toBe("data");
    expect(vm.dataPreview[0]).toMatchObject({ _label: "sample-a", col_0: "2.5" });
    expect(wrapper.find('.plot-type-dropdown').exists()).toBe(false);
    await wrapper.setProps({ modelValue: false });
    await wrapper.setProps({ modelValue: true });
    expect(vm.viewMode).toBe("data");
    wrapper.unmount();
  });

  it("pages retained rows and feature columns without losing their absolute labels", async () => {
    const wrapper = mount(QuickPlotModal, {
      props: { embedded: true, modelValue: true, nodeType: "preprocess.scale", nodeLabel: "Centered",
        nodeOutput: { data: Array.from({ length: 120 }, (_, i) => Array.from({ length: 12 }, (_, j) => i * 100 + j)),
          metadata: { sample_labels: Array.from({ length: 120 }, (_, i) => `sample${i}`), feature_names: Array.from({ length: 12 }, (_, i) => `feature${i}`) } } },
      global: { stubs: globalStubs },
    });
    const vm = wrapper.vm as any;
    vm.previewFirst = 100;
    vm.featureOffset = 10;
    await nextTick();
    expect(vm.dataPreview).toHaveLength(20);
    expect(vm.dataPreview[0]).toMatchObject({ _index: 101, _label: "sample100", col_10: "10010" });
    expect(vm.dataPreviewColumns.some((column: any) => column.header === "feature10")).toBe(true);
    wrapper.unmount();
  });

  it("keeps physical feature coordinates in the VIP table", () => {
    const wrapper = mount(QuickPlotModal, {
      props: { embedded: true, modelValue: true, nodeType: "model.fitted_pls", nodeLabel: "PLS",
        nodeOutput: { data: [0.4, 1.2], presentation_value: [0.4, 1.2], metadata: {
          scientific_presentation: scientificPresentation("variable_profile"),
          wavenumbers: [600, 1400], feature_names: ["band-a", "band-b"], data_role: "X_spectra",
        } } },
      global: { stubs: globalStubs },
    });
    expect((wrapper.vm as any).dataPreview[0]).toMatchObject({ x: 600, y: 0.4 });
    expect((wrapper.vm as any).dataPreview[1]).toMatchObject({ x: 1400, y: 1.2 });
    wrapper.unmount();
  });

  it("shows loading coordinates rather than scores after selecting the loadings plot", async () => {
    const wrapper = mount(QuickPlotModal, {
      props: { embedded: true, modelValue: true, nodeType: "model.pca", nodeLabel: "PCA",
        nodeOutput: { data: [[100, 200]], metadata: { type: "PCA", isPCA: true,
          loadings: [[0.1, 0.2, 0.3], [0.3, 0.2, 0.1]], wavenumbers: [600, 700, 800], explained_variance_ratio: [0.6, 0.3] } } },
      global: { stubs: globalStubs },
    });
    const vm = wrapper.vm as any;
    vm.selectedPlotKey = "pca_loadings";
    await nextTick();
    expect(vm.dataPreview[0]).toMatchObject({ x: 600, y: 0.1 });
    expect(vm.dataPreview[0]).not.toHaveProperty("col_0");
    wrapper.unmount();
  });

  it("exposes plotted coordinates when a visualization has no separate data matrix", () => {
    const wrapper = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        nodeType: "analysis.peak_finding",
        nodeLabel: "Peak Finding",
        nodeOutput: {
          data: [],
          plots: { peak_finding: {
            data: [{ type: "scatter", name: "Sample A", x: [1200, 1100], y: [0.2, 0.4] }],
            layout: {},
          } },
        },
      },
      global: { stubs: globalStubs },
    });
    expect((wrapper.vm as any).dataPreview).toEqual([
      { _index: 1, series: "Sample A", x: 1200, y: 0.2 },
      { _index: 2, series: "Sample A", x: 1100, y: 0.4 },
    ]);
    expect((wrapper.vm as any).dataPreviewSummary).toBe("2 of 2 plotted points");
  });

  it("preserves an inspection-height dendrogram inside the scrollable plot viewport", () => {
    const wrapper = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        nodeType: "model.hca",
        nodeLabel: "Hierarchical Clustering",
        nodeOutput: {
          data: [0, 1, 2],
          metadata: { type: "HCA" },
          plots: {
            dendrogram: {
              data: [
                {
                  type: "scatter",
                  mode: "lines",
                  x: [0, 1],
                  y: [5, 5],
                },
              ],
              layout: {
                height: 1000,
                xaxis: { title: "Distance" },
                yaxis: { title: "Sample" },
              },
            },
          },
        },
      },
      global: {
        stubs: {
          Dialog: { template: "<div><slot /></div>" },
          Dropdown: true,
          Button: true,
          DataTable: true,
          Column: true,
          PlotlyChart: true,
        },
      },
    });

    expect((wrapper.vm as any).plotCanvasStyle).toEqual({
      height: "1000px",
      minHeight: "1000px",
    });
  });

  it("uses latent-variable and variance-domain labels in the explained-variance table", () => {
    const wrapper = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        nodeType: "classification.plsda",
        nodeLabel: "Train PLS-DA Classifier",
        nodeOutput: {
          data: [
            [0.31, 0.32],
            [0.32, 0.05],
          ],
          metadata: {
            sample_labels: ["CL__B1", "ML__B1"],
            scientific_presentation: {
              schema_version: "spectrasherpa-node-presentation/1",
              contract_digest: "a".repeat(64),
              kind: "pls_explained_variance",
              presentation_id: "explained_variance",
              source_port: "explained_variance",
              source_ports: ["explained_variance"],
              modes: ["plot", "table"],
            },
          },
        },
      },
      global: {
        stubs: {
          Dialog: { template: "<div><slot /></div>" },
          Dropdown: true,
          Button: true,
          DataTable: true,
          Column: true,
          PlotlyChart: true,
        },
      },
    });

    expect((wrapper.vm as any).dataPreviewColumns.map((column: any) => column.header)).toEqual([
      "#",
      "Latent Variable",
      "X variance",
      "Y variance",
    ]);
    expect((wrapper.vm as any).dataPreview.map((row: any) => row._label_full)).toEqual([
      "LV 1",
      "LV 2",
    ]);
  });

  it.each([
    ["model.pca", "pca_loadings"],
    ["model.fitted_pls", "pls_loadings"],
    ["classification.plsda", "plsda_loadings"],
  ])("uses variable-axis labels for %s loading columns", (nodeType, kind) => {
    const wrapper = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        nodeType,
        nodeLabel: "Fit Model",
        nodeOutput: {
          data: [
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
          ],
          presentation_value: {
            x_axis: { labels: ["mean radius", "mean texture", "mean perimeter"] },
          },
          metadata: {
            type: "PCA",
            pc_labels: ["PC1", "PC2"],
            sample_labels: ["PC1", "PC2"],
            feature_names: ["stale feature 1", "stale feature 2", "stale feature 3"],
            scientific_presentation: scientificPresentation(kind),
          },
        },
      },
      global: { stubs: globalStubs },
    });

    expect((wrapper.vm as any).dataPreviewColumns.map((column: any) => column.header)).toEqual([
      "#",
      "Label",
      "mean radius",
      "mean texture",
      "mean perimeter",
    ]);
  });

  it("retains principal-component headers for a PCA score table", () => {
    const wrapper = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        nodeType: "model.pca",
        nodeLabel: "Fit PCA",
        nodeOutput: {
          data: [
            [1.2, -0.5],
            [-0.8, 0.7],
          ],
          metadata: {
            type: "PCA",
            pc_labels: ["PC1 (44.3%)", "PC2 (19.0%)"],
            sample_labels: ["sample 1", "sample 2"],
            feature_names: ["mean radius", "mean texture"],
            scientific_presentation: scientificPresentation("pca_scores"),
          },
        },
      },
      global: { stubs: globalStubs },
    });

    expect((wrapper.vm as any).dataPreviewColumns.map((column: any) => column.header)).toEqual([
      "#",
      "Label",
      "PC1 (44.3%)",
      "PC2 (19.0%)",
    ]);
  });

  it("renders uncolored PCA scores while explaining refused metadata grouping", () => {
    const scores = [[1.2, -0.5], [-0.8, 0.7]];
    const scoreValue = {
      type: "SherpaDataset",
      data: scores,
      y_axis: {
        labels: ["sample 1", "sample 2"],
        sample_table: { sample_id: ["sample 2", "sample 1"] },
      },
    };
    const wrapper = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        nodeType: "model.pca",
        nodeLabel: "Fit PCA",
        nodeOutput: {
          data: scores,
          presentation_value: scoreValue,
          primary_port: "scores",
          ports: { scores: { data: scores, metadata: {}, value: scoreValue } },
          metadata: {
            type: "PCA",
            pc_labels: ["PC1", "PC2"],
            sample_classes: ["malignant", "benign"],
            label_categories: ["malignant", "benign"],
            scientific_presentation: scientificPresentation("pca_scores"),
          },
        },
      },
      global: { stubs: globalStubs },
    });

    expect(wrapper.text()).toContain(
      "Metadata grouping refused: sample IDs do not exactly match score-row labels.",
    );
    expect(wrapper.text()).not.toContain("No data to display");
    expect((wrapper.vm as any).displayPlotData).toHaveLength(1);
    expect((wrapper.vm as any).displayPlotData[0]).toMatchObject({
      type: "scatter",
      x: [1.2, -0.8],
      y: [-0.5, 0.7],
    });
    expect((wrapper.vm as any).displayPlotData[0].name).toBeUndefined();
    expect((wrapper.vm as any).displayPlotLayout.showlegend).toBe(false);
    expect(scientificPlotRefusal((wrapper.vm as any).displayPlotLayout)).toBeNull();
    expect((wrapper.vm as any).displayPlotLayout.meta.metadata_grouping_notice).toContain(
      "sample IDs do not exactly match score-row labels",
    );
    wrapper.unmount();
  });

  it("starts each newly opened quick plot in plot view", async () => {
    const wrapper = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        nodeType: "model.pca",
        nodeLabel: "Fit PCA",
        nodeOutput: {
          data: [[1, 2]],
          metadata: {},
        },
      },
      global: { stubs: globalStubs },
    });

    (wrapper.vm as any).toggleViewMode();
    expect((wrapper.vm as any).viewMode).toBe("data");

    await wrapper.setProps({ modelValue: false });
    await wrapper.setProps({ modelValue: true });
    await nextTick();

    expect((wrapper.vm as any).viewMode).toBe("plot");
  });

it("does not round micro-scale range or tabular values to zero",()=>{
  const wrapper=mount(QuickPlotModal,{props:{embedded:true,modelValue:true,nodeType:"",nodeLabel:"micro",nodeOutput:{data:[[1e-8,2e-8]],metadata:{}}},global:{stubs:globalStubs}});
  expect(wrapper.text()).toContain("1e-8");
  expect((wrapper.vm as any).dataPreview[0].col_0).toBe("1e-8");
  wrapper.unmount();
});

});
