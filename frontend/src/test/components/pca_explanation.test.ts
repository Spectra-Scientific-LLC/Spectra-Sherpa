import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import PcaExplanation from "@/components/PcaExplanation.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import type { PcaExplanationDetail, ReviewRow } from "@/utils/sampleReview";
function evidence(): PcaExplanationDetail {
  return {
    schema_version: "spectrasherpa-pca-explanations/1",
    model_digest: "model",
    feature_identity: "axis",
    reference_digest: "ref",
    reference_count: 30,
    formula: "signed additive",
    space: "Centered model space",
    preprocessing: ["preprocess.derivative"],
    feature_count: 3,
    feature_labels: ["Same", "Same", "Third"],
    feature_values: [0, 1, 2],
    feature_units: "nm",
    top_per_statistic: 1,
    loadings: [
      [0.5, 0.5, 0.7],
      [0.7, -0.7, 0],
    ],
    loadings_unavailable_reason: null,
    rows: {
      a: {
        variables: [
          [0, 4, -2],
          [1, 3, 5],
        ],
        q_total: 9,
        t2_total: 4,
        omitted_q: 2,
        omitted_t2: 1,
        omitted_t2_absolute: 3,
      },
      b: {
        variables: [[1, 1, 2]],
        q_total: 3,
        t2_total: 5,
        omitted_q: 2,
        omitted_t2: 3,
        omitted_t2_absolute: 3,
      },
    },
  };
}
const rows: ReviewRow[] = [
  { id: "a", role: "calibration", group: "A", scores: [1, 2], q: 9, t2: 4 },
  { id: "b", role: "excluded_projected", group: "A", scores: [3, 4], q: 3, t2: 5 },
];
function view(selected = ["a"]) {
  return mount(PcaExplanation, {
    props: { evidence: evidence(), selected, rows, runId: 10, components: 2, stale: false },
    global: {
      stubs: {
        PlotlyChart: {
          props: ["data", "layout", "selectedPointIds"],
          template: "<div class='chart' />",
        },
      },
    },
  });
}
describe("PCA explanation focus", () => {
  it("links exact feature IDs to loadings without conflating duplicate labels or observation IDs", async () => {
    const w = view();
    const charts = w.findAllComponents(PlotlyChart);
    expect(w.text()).toContain("Omitted absolute T² mass: 3.0000");
    expect(w.text()).toContain("negative distances");
    expect(charts[1].props("data")[0].y).toEqual([-2, 5]);
    charts[2].vm.$emit("selected", {
      points: [{ customdata: "axis:1" }, { customdata: "a" }, { pointIndex: 0 }],
    });
    await flushPromises();
    expect(charts[0].props("selectedPointIds")).toEqual(["axis:1"]);
    expect(w.emitted("advisor-selection")?.at(-1)?.[0]).toEqual({variables:["axis:1"],response:0,sample:"a"});
    expect(
      (w.get('input[aria-label="Highlight variable 2"]').element as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (w.get('input[aria-label="Highlight variable 1"]').element as HTMLInputElement).checked,
    ).toBe(false);
    expect(w.emitted()).not.toHaveProperty("selected");
    await w.get('input[aria-label="Highlight variable 1"]').setValue(true);
    expect(charts[2].props("selectedPointIds")).toEqual(["axis:1", "axis:0"]);
    await w.get('select[aria-label="Loading component"]').setValue("1");
    expect(charts[2].props("data")[0].y).toEqual([0.7, -0.7, 0]);
    expect(charts[1].props("data")[0].y).toEqual([-2, 5]);
    const oldChart = w.findAllComponents(PlotlyChart)[0].vm;
    await w.get("button").trigger("click");
    expect(w.findAllComponents(PlotlyChart)[0].vm).not.toBe(oldChart);
    expect(w.findAllComponents(PlotlyChart)[0].props("selectedPointIds")).toEqual([]);
    expect(
      (w.get('select[aria-label="Sample to explain"]').element as HTMLSelectElement).value,
    ).toBe("a");
    w.unmount();
  });
  it("explains one chosen observation, preserves sample roles and discloses sparse omissions", async () => {
    const w = view(["a", "b"]);
    await w.get('select[aria-label="Sample to explain"]').setValue("b");
    expect(w.text()).toContain("Excluded — projected into this fit");
    w.findAllComponents(PlotlyChart)[2].vm.$emit("selected", {
      points: [{ customdata: "axis:2" }],
    });
    await flushPromises();
    expect(w.text()).toContain("1 variables highlighted; 1 are outside");
    expect(w.text()).toContain("Showing 1 of 3 variables");
    await w.setProps({ selected: [] });
    expect(w.text()).toContain("Select an observation");
    w.unmount();
  });
  it("clears model and variable focus on rerun and hides stale evidence", async () => {
    const w = view();
    await w.get('input[aria-label="Highlight variable 1"]').setValue(true);
    await w.setProps({ runId: 11, evidence: { ...evidence(), model_digest: "new" } });
    expect(w.text()).toContain("0 variables highlighted");
    await w.setProps({ stale: true });
    expect(w.findAllComponents(PlotlyChart)).toHaveLength(0);
    expect(w.text()).toContain("Previous-fit explanations are hidden");
    w.unmount();
  });
  it("keeps historical and unavailable projections readable without guessing", async () => {
    const w = view();
    await w.setProps({ evidence: undefined });
    expect(w.text()).toContain("Rerun to enable");
    await w.setProps({ evidence: { unavailable_reason: "Budget exceeded" } });
    expect(w.text()).toContain("Budget exceeded");
    const e = evidence();
    delete e.rows.b;
    e.loadings = null;
    e.loadings_unavailable_reason = "Loadings budget";
    await w.setProps({
      evidence: e,
      selected: ["b"],
      rows: [{ ...rows[1], scores: null, projection_error: "Exact scale missing" }],
    });
    expect(w.text()).toContain("Exact scale missing");
    expect(w.text()).toContain("Loadings budget");
    w.unmount();
  });
});
