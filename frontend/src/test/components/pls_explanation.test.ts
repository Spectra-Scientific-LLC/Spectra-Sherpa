import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import PlsExplanation from "@/components/PlsExplanation.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import type { PlsExplanationDetail, ReviewRow } from "@/utils/sampleReview";
function evidence(): PlsExplanationDetail {
  const a = {
    variables: [
      [0, -2],
      [1, 5],
    ] as [number, number][],
    prediction: 14,
    contribution_total: 4,
    omitted_signed: 1,
    omitted_absolute: 3,
  };
  const b = {
    variables: [[1, 7]] as [number, number][],
    prediction: 30,
    contribution_total: 10,
    omitted_signed: 3,
    omitted_absolute: 3,
  };
  return {
    schema_version: "spectrasherpa-pls-explanations/1",
    model_digest: "model",
    feature_identity: "axis",
    reference_digest: "ref",
    reference_count: 30,
    response_identity: { names: ["Protein", "Moisture"], units: ["%", "g/L"] },
    baseline: [10, 20],
    formula: "additive",
    preprocessing: ["preprocess.derivative"],
    internal_scale: true,
    feature_count: 3,
    feature_labels: ["Same", "Same", "Third"],
    feature_values: [0, 1, 2],
    feature_units: "nm",
    signal_units: "absorbance",
    top_per_response: 2,
    coefficients: [
      [1, 2, 3],
      [4, 5, 6],
    ],
    loadings: [
      [0.5, 0.2, 0.3],
      [-0.1, 0.6, 0.7],
    ],
    vip: [1, 2, 3],
    profiles_unavailable_reason: null,
    rows: { a: [a, b], b: [a, b], c: [a, b] },
  };
}
const rows: ReviewRow[] = [
  {
    id: "a",
    role: "calibration",
    group: "A",
    scores: null,
    q: null,
    t2: null,
    reference: [15, 31],
    predicted: [14, 30],
    residual: [1, 1],
  },
  { id: "b", role: "excluded_projected", group: "A", scores: null, q: null, t2: null },
  { id: "c", role: "held_out_test", group: "Test", scores: null, q: null, t2: null },
];
function view(selected = ["a"]) {
  return mount(PlsExplanation, {
    props: { evidence: evidence(), selected, rows, runId: 10, stale: false },
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
describe("PLS exact-fit explanations", () => {
  it("switches response contributions, baseline, units and coefficients without changing sample", async () => {
    const w = view();
    expect(w.text()).toContain("10.000 %");
    expect(w.text()).toContain("not the residual error");
    expect(w.text()).toContain("omitted absolute mass: 3.0000");
    expect(w.findAllComponents(PlotlyChart)[0].props("data")[0].y).toEqual([-2, 5]);
    await w.get('select[aria-label="Explanation response"]').setValue("1");
    expect(w.text()).toContain("20.000 g/L");
    expect(w.emitted("advisor-selection")?.at(-1)?.[0]).toEqual({variables:[],response:1,sample:"a"});
    expect(w.findAllComponents(PlotlyChart)[0].props("data")[0].y).toEqual([7]);
    expect(w.findAllComponents(PlotlyChart)[1].props("data")[0].y).toEqual([4, 5, 6]);
    expect(w.text()).toContain("per absorbance");
    expect(
      (w.get('select[aria-label="Sample to explain"]').element as HTMLSelectElement).value,
    ).toBe("a");
    expect(w.emitted()).not.toHaveProperty("selected");
    w.unmount();
  });
  it("links exact variable IDs, preserves signed terms across profiles and resets charts", async () => {
    const w = view();
    let charts = w.findAllComponents(PlotlyChart);
    charts[1].vm.$emit("selected", {
      points: [{ customdata: "axis:1" }, { customdata: "a" }, { pointIndex: 0 }],
    });
    await flushPromises();
    expect(charts[0].props("selectedPointIds")).toEqual(["axis:1"]);
    expect(
      (w.get('input[aria-label="Highlight variable 2"]').element as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (w.get('input[aria-label="Highlight variable 1"]').element as HTMLInputElement).checked,
    ).toBe(false);
    await w.get('input[aria-label="Highlight variable 1"]').setValue(true);
    await w.get('select[aria-label="Fitted variable profile"]').setValue("loadings");
    await w.get('select[aria-label="Loading component"]').setValue("1");
    expect(charts[1].props("data")[0].y).toEqual([-0.1, 0.6, 0.7]);
    expect(charts[0].props("data")[0].y).toEqual([-2, 5]);
    await w.get('select[aria-label="Fitted variable profile"]').setValue("vip");
    expect(w.text()).toContain("all fitted responses");
    expect(charts[1].props("data")[0].y).toEqual([1, 2, 3]);
    const old = charts[0].vm;
    await w.get("button").trigger("click");
    charts = w.findAllComponents(PlotlyChart);
    expect(charts[0].vm).not.toBe(old);
    expect(charts[0].props("selectedPointIds")).toEqual([]);
    w.unmount();
  });
  it("labels heldout inspection and excluded projection, resetting and hiding stale fits", async () => {
    const w = view(["a", "b", "c"]);
    await w.get('select[aria-label="Sample to explain"]').setValue("c");
    expect(w.text()).toContain("Every original test observation remains");
    await w.get('select[aria-label="Sample to explain"]').setValue("b");
    expect(w.text()).toContain("not used to fit it");
    await w.get('input[aria-label="Highlight variable 1"]').setValue(true);
    await w.setProps({ runId: 11, evidence: { ...evidence(), model_digest: "new" } });
    expect(w.text()).toContain("0 variables highlighted");
    await w.setProps({ stale: true });
    expect(w.findAllComponents(PlotlyChart)).toHaveLength(0);
    expect(w.emitted()).not.toHaveProperty("exclude");
    w.unmount();
  });
  it("discloses historical, projection and profile unavailability", async () => {
    const w = view();
    await w.setProps({ evidence: undefined });
    expect(w.text()).toContain("Rerun to enable");
    await w.setProps({ evidence: { unavailable_reason: "Budget exceeded" } });
    expect(w.text()).toContain("Budget exceeded");
    const e = evidence();
    delete e.rows.b;
    e.coefficients = null;
    e.profiles_unavailable_reason = "Profile budget";
    await w.setProps({
      evidence: e,
      selected: ["b"],
      rows: [{ ...rows[1], projection_error: "Exact transform unavailable" }],
    });
    expect(w.text()).toContain("Exact transform unavailable");
    expect(w.text()).toContain("Profile budget");
    w.unmount();
  });
});


it("uses display labels in explanation selectors and cards without changing lookup IDs", async () => {
  const w = view(["a", "b"]);
  await w.setProps({ rows: rows.map((row) => ({ ...row, display_label: "Same <label>" })) });
  await flushPromises();
  const options = w.findAll('select[aria-label="Sample to explain"] option');
  expect(options.slice(1).map((option) => option.text())).toEqual(["Same <label>", "Same <label>"]);
  expect(options.slice(1).map((option) => option.attributes("value"))).toEqual(["a", "b"]);
  await w.get('select[aria-label="Sample to explain"]').setValue("b");
  expect(w.find("strong").text()).toBe("Same <label>");
  w.unmount();
});
