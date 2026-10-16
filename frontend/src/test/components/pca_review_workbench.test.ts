import { flushPromises, mount } from "@vue/test-utils";
import { reactive } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), store: {} as any }));
vi.mock("@/api/client", () => ({ default: { get: mocks.get, post: mocks.post } }));
vi.mock("@/stores/workflow", () => ({ useWorkflowStore: () => mocks.store }));
import { plsReview } from "@/test/fixtures/plsApplicability";
import PcaReviewWorkbench from "@/components/PcaReviewWorkbench.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
function receipt() {
  return {
    run_id: 10,
    latest_run_id: 10,
    revision: 0,
    graph_digest: "a".repeat(64),
    source_digest: "b".repeat(64),
    stale: false,
    n_calibration: 3,
    n_components: 3,
    calibration_t2_limit: 8,
    application_t2_limit: 10,
    q_limit: 2,
    q_limit_method: "Jackson-Mudholkar",
    state: { marked: [], excluded: [] },
    history: [],
    rows: ["a", "b", "c"].map((id, i) => ({
      id,
      role: "calibration",
      group: "Batch 1",
      scores: [i, i + 1, i + 2],
      t2: i,
      q: i / 2,
    })),
  };
}
const options = {
  props: { modelValue: true, nodeId: "pca" },
  global: {
    stubs: {
      DiagnosticAdvisor: true,
      Dialog: { template: "<div><slot /></div>" },
      PlotlyChart: { props: ["data", "selectedPointIds"], template: "<div class='chart' />" },
    },
  },
};
function button(wrapper: any, text: string) {
  return wrapper.findAll("button").find((b: any) => b.text() === text)!;
}
beforeEach(() => {
  mocks.get.mockReset().mockResolvedValue({ data: receipt() });
  mocks.post.mockReset().mockResolvedValue({});
  mocks.store = reactive({
    workflowId: 12,
    isExecuting: false,
    hasUnsavedChanges: false,
    loadWorkflow: vi.fn().mockResolvedValue(undefined),
    executeWorkflow: vi.fn().mockResolvedValue(undefined),
  });
});
describe("PCA review workbench", () => {
  it("links lasso to the other plot and keyboard table, then persists an explicit mark", async () => {
    const wrapper = mount(PcaReviewWorkbench, options);
    await flushPromises();
    const charts = wrapper.findAllComponents(PlotlyChart);
    charts[0].vm.$emit("selected", { points: [{ customdata: "b" }] });
    await flushPromises();
    expect(charts[1].props("selectedPointIds")).toEqual(["b"]);
    expect(
      (wrapper.get('input[aria-label="Select sample b"]').element as HTMLInputElement).checked,
    ).toBe(true);
    await wrapper.get('input[aria-label="Select sample a"]').setValue(true);
    expect(charts[0].props("selectedPointIds")).toEqual(["b", "a"]);
    expect(button(wrapper, "Mark as outlier").attributes("disabled")).toBeDefined();
    await wrapper.get('input[maxlength="1000"]').setValue("High Q; inspection only");
    await button(wrapper, "Mark as outlier").trigger("click");
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith(
      "/workflows/12/sample-review/pca",
      expect.objectContaining({
        action: "mark",
        sample_ids: ["b", "a"],
        expected_latest_run_id: 10,
        expected_revision: 0,
      }),
    );
    expect(mocks.store.executeWorkflow).not.toHaveBeenCalled();
    wrapper.unmount();
  });
  it("reloads saved exclusion after failed refit so Restore remains usable; clamps both axes", async () => {
    const wrapper = mount(PcaReviewWorkbench, options);
    await flushPromises();
    await wrapper.findAll("select")[0].setValue("2");
    await wrapper.get('input[aria-label="Select sample c"]').setValue(true);
    await wrapper.get('input[maxlength="1000"]').setValue("Inspect acquisition");
    const fallback = {
      ...receipt(),
      revision: 1,
      latest_run_id: 11,
      stale: true,
      n_components: 2,
      state: { marked: [], excluded: ["c"] },
    };
    mocks.get.mockResolvedValue({ data: fallback });
    mocks.store.executeWorkflow.mockRejectedValueOnce(new Error("Refit failed"));
    await button(wrapper, "Exclude from this analysis and rerun").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("Refit failed");
    expect(button(wrapper, "Restore selected and rerun").attributes("disabled")).toBeUndefined();
    expect(button(wrapper, "Mark as outlier").attributes("disabled")).toBeDefined();
    expect(wrapper.findAllComponents(PlotlyChart)[0].props("data")[0].x).toEqual([1, 2, 3]);
    expect(mocks.store.loadWorkflow).toHaveBeenCalledWith(12);
    wrapper.unmount();
  });
  it("clears selection and ignores an old request after switching workflows", async () => {
    let resolve: (v: unknown) => void = () => {};
    mocks.get.mockReturnValueOnce(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const wrapper = mount(PcaReviewWorkbench, options);
    mocks.store.workflowId = 13;
    await flushPromises();
    const old = receipt();
    old.rows[0].id = "foreign";
    resolve({ data: old });
    await flushPromises();
    expect(wrapper.text()).not.toContain("foreign");
    expect(wrapper.text()).toContain("0 samples selected");
    wrapper.unmount();
  });
});

describe("PLS linked review", () => {
  it("keeps explicit applicability variable focus when shared sample selection changes", async () => {
    const review = plsReview();
    review.pls_explanations = {
      schema_version: "spectrasherpa-pls-explanations/1",
      model_digest: "model",
      feature_identity: "axis",
      reference_digest: "reference",
      reference_count: 30,
      response_identity: { names: ["Protein", "Moisture"], units: ["%", "g/L"] },
      baseline: [0, 0],
      formula: "additive",
      preprocessing: [],
      internal_scale: false,
      feature_count: 3,
      feature_labels: null,
      feature_values: [100, 200, 300],
      feature_units: "nm",
      signal_units: "absorbance",
      top_per_response: 1,
      coefficients: [
        [1, 2, 3],
        [3, 4, 5],
      ],
      loadings: [[1, 0, 0]],
      vip: [1, 1, 1],
      profiles_unavailable_reason: null,
      rows: Object.fromEntries(
        review.rows.map((row) => [
          row.id,
          row.predicted!.map((value) => ({
            variables: [[0, value]],
            prediction: value,
            contribution_total: value,
            omitted_signed: 0,
            omitted_absolute: 0,
          })),
        ]),
      ),
    };
    mocks.get.mockResolvedValue({ data: review });
    const w = mount(PcaReviewWorkbench, options);
    await flushPromises();
    await w.get('input[aria-label="Select sample a"]').setValue(true);
    await w.get('input[aria-label="Select sample b"]').setValue(true);
    const prediction = w
      .findAll("details")
      .find((item) => item.find("summary").text().includes("PLS predictions and fitted profiles"))!;
    (prediction.element as HTMLDetailsElement).open = true;
    await prediction.trigger("toggle");
    await flushPromises();
    await w.get('input[aria-label="Highlight variable 1"]').setValue(true);
    const advisor = w.findComponent({ name: "DiagnosticAdvisor" });
    expect(advisor.props("variableContext")).toBe("prediction");
    await w.get('input[aria-label="Highlight applicability variable 2"]').setValue(true);
    expect(advisor.props("variableContext")).toBe("applicability");
    await w.get('input[aria-label="Select sample a"]').setValue(false);
    await flushPromises();
    expect(advisor.props("variableContext")).toBe("applicability");
    expect(advisor.props("focusedSample")).toBe("b");
    expect(advisor.props("variables")).toEqual(["axis:1"]);
    (prediction.element as HTMLDetailsElement).open = false;
    await prediction.trigger("toggle");
    await flushPromises();
    expect(advisor.props("variableContext")).toBe("applicability");
    expect(advisor.props("variables")).toEqual(["axis:1"]);
    (prediction.element as HTMLDetailsElement).open = true;
    await prediction.trigger("toggle");
    await flushPromises();
    expect(advisor.props("variableContext")).toBe("applicability");
    expect(advisor.props("focusedSample")).toBe("b");
    expect(advisor.props("variables")).toEqual(["axis:1"]);
    w.unmount();
  });

  it("links predictor scores to response charts and table without excluding on selection", async () => {
    mocks.get.mockResolvedValue({ data: plsReview() });
    const w = mount(PcaReviewWorkbench, options);
    await flushPromises();
    const plots = w.findAllComponents(PlotlyChart);
    expect(plots).toHaveLength(4);
    plots[2].vm.$emit("selected", { points: [{ customdata: "b" }, { customdata: "axis:0" }] });
    await flushPromises();
    expect(plots[0].props("selectedPointIds")).toEqual(["b"]);
    expect(plots[3].props("selectedPointIds")).toEqual(["b"]);
    expect((w.get('input[aria-label="Select sample b"]').element as HTMLInputElement).checked).toBe(
      true,
    );
    expect(w.text()).toContain("Predictor screening");
    expect(w.text()).toContain("Q above limit");
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.store.executeWorkflow).not.toHaveBeenCalled();
    w.unmount();
  });

  it("links targets and spectra, and requires acknowledgement for a test-only mask without rerunning", async () => {
    const metric = {
      targets: [{ target: "Concentration", metrics: { n_samples: 2, rmse: 1, r2: 0.9, bias: 0 } }],
    };
    const data = {
      ...receipt(),
      model_kind: "pls",
      target_names: ["Concentration", "Moisture"],
      target_units: ["mg/L", "%"],
      full_test_statistics: metric,
      review_subset_statistics: metric,
      calibration_statistics: metric,
      rows: receipt().rows.map((r, i) => ({
        ...r,
        role: i === 2 ? "held_out_test" : "calibration",
        reference: [i, i + 10],
        predicted: [i + 0.1, i + 10.2],
        residual: [-0.1, -0.2],
      })),
      spectra: {
        x: [100, 200],
        units: "cm^-1",
        variable_count: 2,
        display_count: 2,
        rows: { a: [1, 2], b: [2, 3], c: [3, 4] },
      },
      preprocessing: [
        {
          node_id: "snv",
          operation: "preprocess.normalize",
          parameters: { method: "snv" },
          fitting_population: "sample_local",
        },
        {
          node_id: "scale",
          operation: "preprocess.scale",
          parameters: { method: "auto" },
          fitting_population: "retained_calibration",
          fitting_count: 2,
          fitted_state_sha256: "a".repeat(64),
        },
      ],
      model_input_spectra: {
        x: [100, 200],
        units: "cm^-1",
        signal_units: "scaled absorbance",
        variable_count: 2,
        display_count: 2,
        rows: { a: [0, 1], b: [1, 0], c: [2, 2] },
        space: "Executed model input",
      },
    };
    mocks.get.mockResolvedValue({ data });
    const wrapper = mount(PcaReviewWorkbench, options);
    await flushPromises();
    const charts = wrapper.findAllComponents(PlotlyChart);
    expect(charts).toHaveLength(4);
    charts[2].vm.$emit("selected", { points: [{ customdata: "c" }, { customdata: "c" }] });
    await flushPromises();
    expect(charts[0].props("selectedPointIds")).toEqual(["c"]);
    expect(charts[3].props("selectedPointIds")).toEqual(["c"]);
    expect(wrapper.text()).toContain("fit on 2 retained calibration observations");
    expect(wrapper.text()).toContain('parameters: method="auto"');
    expect(wrapper.text()).toContain("Linked model-input spectra");
    expect(
      button(wrapper, "Exclude from this analysis and rerun").attributes("disabled"),
    ).toBeDefined();
    await wrapper.get('input[maxlength="1000"]').setValue("Damaged cuvette confirmed");
    const omit = button(wrapper, "Omit selected test observations from review subset");
    expect(omit.attributes("disabled")).toBeDefined();
    const ack = wrapper.findAll("label").find((l) => l.text().includes("I understand"))!;
    await ack.get("input").setValue(true);
    await omit.trigger("click");
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith(
      "/workflows/12/sample-review/pca",
      expect.objectContaining({
        action: "exclude_test",
        sample_ids: ["c"],
        acknowledge_post_review: true,
      }),
    );
    expect(mocks.store.executeWorkflow).not.toHaveBeenCalled();
    await wrapper.get("select").setValue("1");
    await flushPromises();
    expect(charts[0].props("data").flatMap((t: { x: number[] }) => t.x)).toEqual([10, 11, 12]);
    expect(charts[1].props("data").flatMap((t: { y: number[] }) => t.y)).toEqual([
      -0.2, -0.2, -0.2,
    ]);
    expect(wrapper.text()).toContain("Current model — full original test set");
    wrapper.unmount();
  });
});
