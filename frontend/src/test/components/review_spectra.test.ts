import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import ReviewSpectra from "@/components/ReviewSpectra.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import type { ReviewRow } from "@/utils/sampleReview";

describe("Exact spectral curve identity", () => {
  it("keeps a late selected identity visible in a 5,000-row view", () => {
    const rows: ReviewRow[] = Array.from({ length: 5000 }, (_, i) => ({
      id: `s${i}`,
      role: "calibration",
      group: "Batch",
      scores: null,
      t2: null,
      q: null,
    }));
    const wrapper = mount(ReviewSpectra, {
      props: {
        rows,
        selected: ["s4999"],
        marked: [],
        masked: [],
        colors: new Map([["Batch", "#123456"]]),
        spectra: {
          x: [100, 300],
          units: "cm^-1",
          variable_count: 2,
          display_count: 2,
          rows: Object.fromEntries(rows.map((r) => [r.id, [1, 2]])),
        },
      },
      global: { stubs: { PlotlyChart: { props: ["data"], template: "<div/>" } } },
    });
    const chart = wrapper.findComponent(PlotlyChart);
    expect(chart.props("data")).toHaveLength(32);
    expect(chart.props("data")[0].customdata).toEqual(["s4999", "s4999"]);
    expect(wrapper.text()).toContain("0 selected observations are outside this view");
    wrapper.unmount();
  });
  it("prioritizes selected curves, bounds view, preserves group colours and shows overflow", async () => {
    const rows: ReviewRow[] = Array.from({ length: 150 }, (_, i) => ({
      id: `s${i}`,
      role: "calibration",
      group: "Batch",
      scores: null,
      t2: null,
      q: null,
    }));
    const wrapper = mount(ReviewSpectra, {
      props: {
        rows,
        selected: ["s149"],
        marked: ["s149"],
        masked: [],
        colors: new Map([["Batch", "#123456"]]),
        spectra: {
          x: [100, 300],
          units: "cm^-1",
          variable_count: 1000,
          display_count: 2,
          rows: Object.fromEntries(rows.map((r) => [r.id, [1, 2]])),
        },
      },
      global: {
        stubs: { PlotlyChart: { props: ["data", "selectedPointIds"], template: "<div/>" } },
      },
    });
    const chart = wrapper.findComponent(PlotlyChart);
    expect(chart.props("data")).toHaveLength(32);
    expect(chart.props("data")[0]).toMatchObject({
      customdata: ["s149", "s149"],
      line: { width: 1, color: "#123456" },
      marker: { symbol: "diamond-open" },
    });
    expect(wrapper.text()).toContain("Display is sampled");
    await wrapper.setProps({ selected: rows.map((r) => r.id) });
    expect(wrapper.text()).toContain("118 selected observations are outside this view");
    chart.vm.$emit("selected", { points: [{ customdata: "s149" }] });
    expect(wrapper.emitted("selected")?.[0][0]).toEqual({ points: [{ customdata: "s149" }] });
    wrapper.unmount();
  });
  it("omits missing model-input curves while preserving selected sample identity", () => {
    const rows: ReviewRow[] = ["a", "b"].map((id) => ({
      id,
      role: "calibration",
      group: "Batch",
      scores: null,
      t2: null,
      q: null,
    }));
    const wrapper = mount(ReviewSpectra, {
      props: {
        title: "Linked model-input spectra",
        rows,
        selected: ["b"],
        marked: [],
        masked: [],
        colors: new Map([["Batch", "#123456"]]),
        spectra: {
          x: [100],
          units: "nm",
          variable_count: 1,
          display_count: 1,
          rows: { a: [0.5] },
          missing_ids: ["b"],
          signal_units: "scaled absorbance",
        },
      },
      global: { stubs: { PlotlyChart: { props: ["data", "layout"], template: "<div/>" } } },
    });
    const chart = wrapper.findComponent(PlotlyChart);
    expect(chart.props("data")).toHaveLength(1);
    expect(chart.props("data")[0].name).toBe("a");
    expect(chart.props("layout").yaxis.title).toBe("scaled absorbance");
    expect(wrapper.text()).toContain("1 observations have no retained curves");
    wrapper.unmount();
  });
});


it("renders bounded spectral labels but looks up values and selects with full IDs", () => {
  const rows: ReviewRow[] = ["id-a", "id-b"].map((id) => ({ id, display_label: "Same <&>", role: "calibration", group: "Batch", scores: null, t2: null, q: null }));
  const w = mount(ReviewSpectra, { props: { rows, selected: [], marked: [], masked: [], colors: new Map([["Batch", "#123456"]]),
    spectra: { x: [100], units: "nm", variable_count: 1, display_count: 1, rows: { "id-a": [1], "id-b": [2] } } },
    global: { stubs: { PlotlyChart: { props: ["data"], template: "<div/>" } } } });
  const traces = w.findComponent(PlotlyChart).props("data");
  expect(traces.map((trace: { name: string }) => trace.name)).toEqual(["Same &lt;&amp;&gt;", "Same &lt;&amp;&gt;"]);
  expect(traces.map((trace: { customdata: string[] }) => trace.customdata)).toEqual([["id-a"], ["id-b"]]);
  expect(traces.map((trace: { y: number[] }) => trace.y)).toEqual([[1], [2]]);
  w.unmount();
});
