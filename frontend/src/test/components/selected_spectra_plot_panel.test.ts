import { mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { describe, expect, it, vi } from "vitest";

import SelectedSpectraPlotPanel from "@/views/data/SelectedSpectraPlotPanel.vue";
import type { DatasetPlotSource, SherpaDatasetDict } from "@/types";

vi.mock("@/views/workflow-builder/node-detail/panels/SampleMetadataStyleControls.vue", () => ({
  default: defineComponent({
    name: "SampleMetadataStyleControls",
    emits: ["update:colorValue"],
    template: "<div />",
  }),
}));

vi.mock("@/components/PlotlyChart.vue", () => ({
  default: defineComponent({
    name: "PlotlyChart",
    props: { data: Array, layout: Object, config: Object },
    template: "<div data-testid='plotly-chart' />",
  }),
}));

vi.mock("primevue/progressspinner", () => ({
  default: defineComponent({ name: "ProgressSpinner", template: "<div />" }),
}));

vi.mock("primevue/tag", () => ({
  default: defineComponent({
    name: "Tag",
    props: { value: [String, Number] },
    template: "<span>{{ value }}</span>",
  }),
}));

vi.mock("primevue/button", () => ({
  default: defineComponent({
    name: "PrimeButton",
    props: { label: String },
    emits: ["click"],
    template: "<button @click='$emit(\"click\")'>{{ label }}</button>",
  }),
}));

function dataset(label: string, quantity = "Absorbance"): SherpaDatasetDict {
  return {
    data_role: "X_spectra",
    n_samples: 1,
    n_features: 3,
    data: [[0.1, 0.2, 0.3]],
    x_axis: { data: [1800, 1200, 600], title: "Wavenumber", units: "cm-1" },
    y_axis: { labels: [label], sample_table: { specimen_id: [label.split("_").at(-1)] } },
    domain: { data_quantity: quantity },
    units: quantity === "Absorbance" ? "absorbance" : "percent",
  };
}

function source(
  experimentId: number,
  name: string,
  members: Array<{ id: number; name: string; dataset: SherpaDatasetDict }>,
  totalFileCount = members.length,
): DatasetPlotSource {
  return {
    experimentId,
    name,
    members: members.map((member) => ({
      fileId: member.id,
      fileName: member.name,
      dataset: member.dataset,
    })),
    selectedFileCount: members.length,
    totalFileCount,
  };
}

describe("SelectedSpectraPlotPanel", () => {
  function retainedSource(): DatasetPlotSource {
    const full = dataset("A");
    full.n_samples = 3;
    full.data = [
      [1, 2, 3],
      [4, 5, 6],
      [7, 8, 9],
    ];
    full.y_axis = { labels: ["A", "B", "C"], sample_table: { group: ["red", "blue", "green"] } };
    full.metadata = {
      source_member_metadata: ["a.spa", "b.spa", "c.spa"].map((file_name) => ({ file_name })),
    };
    return {
      ...source(1, "Collection", [{ id: 1, name: "All files", dataset: full }], 3),
      selectedFileNames: ["b.spa"],
      selectedFileCount: 1,
    };
  }

  it("filters the actual single-dataset curves and hover identities from the retained source", async () => {
    const selected = retainedSource();
    const wrapper = mount(SelectedSpectraPlotPanel, {
      props: { plotDatasetCount: 1, plotFileCount: 1, plotDatasets: [selected] },
    });
    const chart = wrapper.getComponent({ name: "PlotlyChart" });
    expect(chart.props("data")).toHaveLength(1);
    expect(chart.props("data")[0]).toMatchObject({
      name: "B",
      y: [4, 5, 6],
      customdata: [
        ["B", "b.spa"],
        ["B", "b.spa"],
        ["B", "b.spa"],
      ],
    });
    await wrapper.setProps({
      plotDatasets: [{ ...selected, selectedFileNames: ["a.spa", "c.spa"] }],
      plotFileCount: 2,
    });
    expect(
      chart.props("data").map((trace: { name: string; y: number[] }) => [trace.name, trace.y]),
    ).toEqual([
      ["A", [1, 2, 3]],
      ["C", [7, 8, 9]],
    ]);
    expect(selected.members[0].dataset.data).toHaveLength(3);
  });

  it("filters metadata-styled curves with their matching groups and filenames", async () => {
    const wrapper = mount(SelectedSpectraPlotPanel, {
      props: { plotDatasetCount: 1, plotFileCount: 1, plotDatasets: [retainedSource()] },
    });
    wrapper
      .getComponent({ name: "SampleMetadataStyleControls" })
      .vm.$emit("update:colorValue", "group");
    await wrapper.vm.$nextTick();
    const traces = wrapper.getComponent({ name: "PlotlyChart" }).props("data");
    const curves = traces.filter((trace: { customdata?: unknown }) => trace.customdata);
    expect(curves).toHaveLength(1);
    expect(curves[0]).toMatchObject({ name: "B", y: [4, 5, 6] });
    expect(curves[0].customdata[0]).toEqual(["B", "blue", "None", "b.spa"]);
  });

  it("applies each dataset's own selection independently in a multi-dataset overlay", async () => {
    const first = retainedSource();
    const second = retainedSource();
    second.experimentId = 2;
    second.name = "Second collection";
    second.selectedFileNames = ["a.spa", "c.spa"];
    second.selectedFileCount = 2;
    second.members[0].dataset.data = [
      [11, 12, 13],
      [14, 15, 16],
      [17, 18, 19],
    ];
    const wrapper = mount(SelectedSpectraPlotPanel, {
      props: { plotDatasetCount: 2, plotFileCount: 3, plotDatasets: [first, second] },
    });
    const chart = wrapper.getComponent({ name: "PlotlyChart" });
    const curves = () =>
      chart
        .props("data")
        .map((trace: { y: number[]; customdata: string[][] }) => [
          trace.y,
          trace.customdata[0].slice(0, 3),
        ]);
    expect(curves()).toEqual([
      [
        [4, 5, 6],
        ["B", "Collection", "b.spa"],
      ],
      [
        [11, 12, 13],
        ["A", "Second collection", "a.spa"],
      ],
      [
        [17, 18, 19],
        ["C", "Second collection", "c.spa"],
      ],
    ]);
    await wrapper.setProps({ plotDatasets: [{ ...first, selectedFileNames: ["c.spa"] }, second] });
    expect(curves()).toEqual([
      [
        [7, 8, 9],
        ["C", "Collection", "c.spa"],
      ],
      [
        [11, 12, 13],
        ["A", "Second collection", "a.spa"],
      ],
      [
        [17, 18, 19],
        ["C", "Second collection", "c.spa"],
      ],
    ]);
    await wrapper.setProps({
      plotDatasets: [{ ...first, selectedFileNames: undefined }, second],
      plotFileCount: 5,
    });
    expect(chart.props("data")).toHaveLength(5);
    expect(curves().slice(-2)).toEqual([
      [
        [11, 12, 13],
        ["A", "Second collection", "a.spa"],
      ],
      [
        [17, 18, 19],
        ["C", "Second collection", "c.spa"],
      ],
    ]);
  });

  it("does not fall back to plotting all rows when selection identity is unavailable", () => {
    const selected = retainedSource();
    selected.selectedFileNames = ["unknown.spa"];
    const wrapper = mount(SelectedSpectraPlotPanel, {
      props: { plotDatasetCount: 1, plotDatasets: [selected] },
    });
    expect(wrapper.findComponent({ name: "PlotlyChart" }).exists()).toBe(false);
    expect(wrapper.get("[role='alert']").text()).toContain("no exact row-to-file projection");
  });

  it("filters feature-table rows, sample labels, and targets together", () => {
    const selected = retainedSource();
    const full = selected.members[0].dataset;
    full.data_role = "X_features";
    full.x_axis = { labels: ["one", "two", "three"] };
    full.target = [10, 20, 30];
    const wrapper = mount(SelectedSpectraPlotPanel, {
      props: { plotDatasetCount: 1, plotFileCount: 1, plotDatasets: [selected] },
    });
    expect(wrapper.text()).toContain("First 1 of 1 rows");
    expect(wrapper.findAll("tbody tr")).toHaveLength(1);
    expect(wrapper.get("tbody tr").text()).toBe("B45620");
    const traces = wrapper.getComponent({ name: "PlotlyChart" }).props("data");
    const points = traces.filter((trace: { type: string }) => trace.type === "scattergl");
    expect(points).toHaveLength(6);
    expect(points[0].customdata).toEqual([["B", "20"]]);
  });

  it("shows a concise empty state before any plot choice is made", () => {
    const wrapper = mount(SelectedSpectraPlotPanel);

    expect(wrapper.text()).toContain("Choose datasets or files above");
    expect(wrapper.findComponent({ name: "PlotlyChart" }).exists()).toBe(false);
  });

  it("plots only selected file members and removes the incomplete legend", () => {
    const wrapper = mount(SelectedSpectraPlotPanel, {
      props: {
        plotDatasetCount: 2,
        plotFileCount: 3,
        plotDatasets: [
          source(1, "YF block", [{ id: 11, name: "YF_ESL.spa", dataset: dataset("YF_ESL") }]),
          source(
            2,
            "JF",
            [
              { id: 21, name: "JF_ESL.spa", dataset: dataset("JF2_ESL") },
              { id: 22, name: "JF_PL.spa", dataset: dataset("JF1_PL") },
            ],
            6,
          ),
        ],
      },
    });

    const chart = wrapper.getComponent({ name: "PlotlyChart" });
    expect(wrapper.text()).toContain("3 files · 2 datasets");
    expect(chart.props("data")).toHaveLength(3);
    expect(chart.props("layout")).toEqual(expect.objectContaining({ showlegend: false }));
    expect(
      (chart.props("data") as Array<Record<string, unknown>>).map((trace) => trace.name),
    ).toEqual(["YF_ESL", "JF2_ESL", "JF1_PL"]);
  });

  it("shows a bounded labeled table for a feature dataset", () => {
    const featureTable: SherpaDatasetDict = {
      data_role: "X_features",
      n_samples: 2,
      n_features: 2,
      data: [
        [5.1, 3.5],
        [6.4, 3.2],
      ],
      x_axis: { labels: ["sepal length (cm)", "sepal width (cm)"], title: "Feature" },
      sample_axis: { labels: ["Iris 001", "Iris 002"] },
      y_axis: { labels: ["legacy-row-1", "legacy-row-2"] },
      target: [0, 2],
      target_context: {
        target_type: "categorical",
        target_name: "Species",
        class_names: ["setosa", "versicolor", "virginica"],
      },
    };
    const wrapper = mount(SelectedSpectraPlotPanel, {
      props: {
        plotDatasetCount: 1,
        plotFileCount: 1,
        plotDatasets: [source(3, "Iris", [{ id: 31, name: "iris.csv", dataset: featureTable }])],
      },
    });

    expect(wrapper.text()).toContain("Comparison preview");
    expect(wrapper.text()).toContain("does not change the active workflow source");
    expect(wrapper.text()).toContain("First 2 of 2 rows · 2 features");
    expect(wrapper.text()).toContain("sepal length (cm)");
    expect(wrapper.text()).toContain("Iris 001");
    expect(wrapper.text()).not.toContain("legacy-row-1");
    expect(wrapper.text()).toContain("setosa");
    expect(wrapper.text()).toContain("virginica");
    const chart = wrapper.getComponent({ name: "PlotlyChart" });
    const traces = chart.props("data") as Array<Record<string, unknown>>;
    expect(traces.filter((trace) => trace.type === "histogram")).toHaveLength(4);
    expect(traces.filter((trace) => trace.type === "scattergl")).toHaveLength(4);
    expect(traces.find((trace) => trace.type === "scattergl" && trace.name === "setosa")).toMatchObject({
      x: [3.5],
      y: [5.1],
      customdata: [["Iris 001", "setosa"]],
      hovertemplate: expect.stringContaining("Target: %{customdata[1]}"),
    });
    expect(chart.props("layout").grid).toEqual({ rows: 2, columns: 2, pattern: "independent" });
    // Every left-column panel names its row feature. The row-0 panel is the
    // diagonal, so titling it "Count" left the top row of scatter panels
    // with no feature label at all.
    const layout = chart.props("layout") as Record<string, Record<string, unknown>>;
    expect(layout.yaxis.title).toBe("sepal length (cm)");
    expect(layout.yaxis3.title).toBe("sepal width (cm)");
    expect(wrapper.find("[role='alert']").exists()).toBe(false);
  });

  it("uses the exact member filename in single-file hover text", () => {
    const singleFileDataset = dataset("JF2_ESL");
    singleFileDataset.y_axis = { labels: ["JF2_ESL"] };
    const wrapper = mount(SelectedSpectraPlotPanel, {
      props: {
        plotDatasetCount: 1,
        plotFileCount: 1,
        activeExperimentId: 2,
        activeFileName: "EO_Lavender_001_JF_ESL.spa",
        plotDatasets: [
          source(2, "JF", [
            {
              id: 21,
              name: "EO_Lavender_001_JF_ESL.spa",
              dataset: singleFileDataset,
            },
          ]),
        ],
      },
    });

    const trace = wrapper.getComponent({ name: "PlotlyChart" }).props("data")[0] as Record<
      string,
      unknown
    >;
    expect((trace.customdata as string[][])[0]).toEqual(["JF2_ESL", "EO_Lavender_001_JF_ESL.spa"]);
    expect(trace.hovertemplate).toContain("Filename: %{customdata[1]}");
    expect(trace.line).toEqual(expect.objectContaining({ width: 3.2 }));
  });

  it("preserves the viewport revision when only the active curve changes", async () => {
    const selected = source(2, "JF", [
      { id: 21, name: "first.spa", dataset: dataset("First") },
      { id: 22, name: "second.spa", dataset: dataset("Second") },
    ]);
    const wrapper = mount(SelectedSpectraPlotPanel, {
      props: {
        plotDatasetCount: 1,
        plotFileCount: 2,
        activeExperimentId: 2,
        activeFileName: "first.spa",
        plotDatasets: [selected],
      },
    });
    const chart = wrapper.getComponent({ name: "PlotlyChart" });
    const revision = chart.props("layout").uirevision;

    await wrapper.setProps({ activeFileName: "second.spa" });

    expect(chart.props("layout").uirevision).toBe(revision);
    expect(chart.props("data")[1].line).toEqual(expect.objectContaining({ width: 3.2 }));
  });

  it("preserves both axes while the selected file subset changes", async () => {
    const first = { id: 21, name: "first.spa", dataset: dataset("First") };
    const second = { id: 22, name: "second.spa", dataset: dataset("Second") };
    const third = { id: 23, name: "third.spa", dataset: dataset("Third") };
    const wrapper = mount(SelectedSpectraPlotPanel, {
      props: {
        plotDatasetCount: 1,
        plotFileCount: 3,
        plotDatasets: [source(2, "JF", [first, second, third])],
      },
    });
    const chart = wrapper.getComponent({ name: "PlotlyChart" });
    const revision = chart.props("layout").uirevision;

    expect(chart.props("layout").xaxis).not.toHaveProperty("autorange");
    expect(chart.props("layout").yaxis).not.toHaveProperty("autorange");

    await wrapper.setProps({
      plotFileCount: 2,
      plotDatasets: [source(2, "JF", [first, second], 3)],
    });

    expect(chart.props("layout").uirevision).toBe(revision);
    expect(chart.props("layout").xaxis).not.toHaveProperty("autorange");
    expect(chart.props("layout").yaxis).not.toHaveProperty("autorange");
  });

  it("refuses incompatible selected ordinate quantities", () => {
    const wrapper = mount(SelectedSpectraPlotPanel, {
      props: {
        plotDatasetCount: 2,
        plotFileCount: 2,
        plotDatasets: [
          source(1, "Absorbance", [{ id: 1, name: "a.spa", dataset: dataset("A") }]),
          source(2, "Transmittance", [
            { id: 2, name: "t.spa", dataset: dataset("T", "Transmittance") },
          ]),
        ],
      },
    });

    expect(wrapper.get("[role='alert']").text()).toContain("incompatible ordinate quantities");
    expect(wrapper.findComponent({ name: "PlotlyChart" }).exists()).toBe(false);
  });

  it("offers the recorded harmonization node when collection admission names it", async () => {
    const wrapper = mount(SelectedSpectraPlotPanel, {
      props: {
        plotDatasetCount: 1,
        plotDatasetsError:
          "Feature grids differ; use preprocess.wavenumber_align with an explicit reference grid.",
      },
    });

    await wrapper.get("button").trigger("click");

    expect(wrapper.text()).toContain("Open Wavenumber Align");
    expect(wrapper.emitted("harmonize")).toHaveLength(1);
  });
});
