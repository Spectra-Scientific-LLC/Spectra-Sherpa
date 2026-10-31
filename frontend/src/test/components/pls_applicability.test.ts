import { flushPromises, mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import PlsApplicability from "@/components/PlsApplicability.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import { plsReview, applicability } from "@/test/fixtures/plsApplicability";
type Trace = { x: number[]; y: number[]; marker: { symbol: string; color: string } };
const colors = new Map([
  ["Batch A", "#0072B2"],
  ["Batch B", "#D55E00"],
]);
function view() {
  return mount(PlsApplicability, {
    props: {
      review: plsReview(),
      selected: ["a", "b", "c"],
      colors,
      stale: false,
      responseIndex: 1,
    },
    global: {
      stubs: {
        PlotlyChart: {
          props: ["data", "layout", "selectedPointIds"],
          template: "<div class='chart'/>",
        },
      },
    },
  });
}
describe("PLS predictor-space workbench", () => {
  it("shows one retained latent variable without inventing a second score dimension", async () => {
    const w = view();
    const review = plsReview();
    const detail = applicability();
    detail.components = 1;
    detail.score_covariance_rank = 1;
    review.pls_applicability = detail;
    review.rows = review.rows.map((row) => ({ ...row, scores: row.scores!.slice(0, 1) }));
    await w.setProps({ review });
    expect(w.find('[aria-label="PLS score Y component"]').exists()).toBe(false);
    expect(
      w
        .findAllComponents(PlotlyChart)[0]
        .props("data")
        .map((trace: Trace) => trace.y),
    ).toEqual([[0], [0], [0]]);
    expect(w.text()).toContain("not a second latent variable");
    w.unmount();
  });

  it("uses exact score components and role-specific limits without changing all-component diagnostics", async () => {
    const w = view();
    const plots = w.findAllComponents(PlotlyChart);
    expect(plots[0].props("data").map((trace: Trace) => trace.x)).toEqual([[1], [2], [3]]);
    expect(plots[0].props("data").map((trace: Trace) => trace.marker.symbol)).toEqual([
      "circle",
      "x",
      "square-open",
    ]);
    expect(plots[0].props("data").map((trace: Trace) => trace.marker.color)).toEqual([
      "#0072B2",
      "#0072B2",
      "#D55E00",
    ]);
    const diagnostics = JSON.stringify(plots[1].props("data"));
    await w.get('[aria-label="PLS score X component"]').setValue("2");
    expect(plots[0].props("data").map((trace: Trace) => trace.x)).toEqual([[3], [4], [5]]);
    expect(JSON.stringify(plots[1].props("data"))).toBe(diagnostics);
    expect(plots[1].props("layout").shapes).toMatchObject([
      { x0: 3, line: { color: "#555" } },
      { x0: 5, line: { dash: "dash" } },
      { y0: 2 },
    ]);
    await w.get('[aria-label="Applicability sample"]').setValue("b");
    expect(w.text()).toContain("Applicable T² limit: 5.0000");
    expect(w.text()).toContain("Q above limit");
    expect(w.text()).toContain("prediction certainty");
    await w.get('[aria-label="Applicability sample"]').setValue("c");
    expect(w.text()).toContain("Held-out inspection does not change its cohort");
    expect(w.text()).toContain("Within global screen — local support unknown");
    w.unmount();
  });
  it("links only observation scatter selections and keeps signed variable focus separate", async () => {
    const w = view();
    const plots = w.findAllComponents(PlotlyChart);
    plots[0].vm.$emit("selected", { points: [{ customdata: "b" }] });
    await flushPromises();
    expect(w.emitted("selected")?.[0]).toEqual([{ points: [{ customdata: "b" }] }]);
    await w.get('[aria-label="Highlight applicability variable 1"]').setValue(true);
    expect(w.emitted("advisor-selection")?.at(-1)?.[0]).toEqual({
      variables: ["axis:0"],
      sample: "a",
      response: 1,
    });
    expect(w.emitted("selected")).toHaveLength(1);
    expect(w.text()).toContain("Omitted signed T²: 1.0000");
    expect(w.text()).toContain("Omitted absolute T² mass: 3.0000");
    expect(w.text()).toContain("signed cancellation");
    expect(plots[3].props("data")[0].y).toEqual([-2, 5]);
    await w.get("button").trigger("click");
    expect(w.emitted("advisor-selection")?.at(-1)?.[0]).toMatchObject({ variables: [] });
    w.unmount();
  });
  it("preserves Q when rank prevents T², never turning unknown terms into zeros", async () => {
    const w = view();
    const review = plsReview();
    const detail = applicability();
    detail.score_covariance_rank = 2;
    detail.t2_unavailable_reason = "Rank-deficient score covariance";
    detail.application_t2_limit = null;
    detail.calibration_t2_limit = null;
    for (const terms of Object.values(detail.rows)) {
      terms.t2_total = null;
      terms.omitted_t2 = null;
      terms.omitted_t2_absolute = null;
      terms.variables = terms.variables.map(([index, q]) => [index, q, null]);
    }
    review.pls_applicability = detail;
    review.rows = review.rows.map((row) => ({
      ...row,
      t2: null,
      outside_t2: null,
      applicability_unavailable_reason: detail.t2_unavailable_reason,
      screening_status: "unavailable",
    }));
    await w.setProps({ review });
    const plots = w.findAllComponents(PlotlyChart);
    expect(plots[1].props("layout").title).toContain("T² unavailable");
    expect(plots[1].props("layout").shapes).toEqual([expect.objectContaining({ y0: 2 })]);
    expect(plots[1].props("data").map((t: Trace) => t.y)).toEqual([[9], [9], [1]]);
    expect(plots[3].props("data")[0].y).toEqual([]);
    expect(w.text()).toContain("Full T²: Unavailable");
    expect(w.text()).toContain("score covariance rank 2 of 3");
    w.unmount();
  });
  it("makes missing historical evidence and stale runs explicit without leaking old contributions", async () => {
    const w = view();
    await w.setProps({ stale: true });
    expect(w.findAllComponents(PlotlyChart)).toHaveLength(0);
    expect(w.text()).toContain("Previous-fit applicability is hidden");
    await w.setProps({
      stale: false,
      review: {
        ...plsReview(),
        pls_applicability: { unavailable_reason: "Legacy screening requires a new saved run." },
      },
    });
    expect(w.findAllComponents(PlotlyChart)).toHaveLength(0);
    expect(w.text()).toContain("Legacy screening requires a new saved run");
    w.unmount();
  });
});


it("uses optional observation labels for applicability text while keeping chart and selector IDs", async () => {
  const w = view();
  const review = plsReview();
  review.rows = review.rows.map((row) => ({ ...row, display_label: "Same <&>" }));
  await w.setProps({ review });
  const options = w.findAll("select option").filter((option) => ["a", "b", "c"].includes(option.attributes("value")));
  expect(options.map((option) => option.text())).toEqual(["Same <&>", "Same <&>", "Same <&>"]);
  const traces = w.findAllComponents(PlotlyChart)[0].props("data");
  expect(traces.flatMap((trace: { customdata: string[] }) => trace.customdata)).toEqual(["a", "b", "c"]);
  expect(traces.flatMap((trace: { text: string[] }) => trace.text)).toEqual(["Same &lt;&amp;&gt;", "Same &lt;&amp;&gt;", "Same &lt;&amp;&gt;"]);
  w.unmount();
});
