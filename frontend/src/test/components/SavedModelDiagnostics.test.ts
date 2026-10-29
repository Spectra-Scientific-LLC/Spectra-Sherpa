import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
beforeEach(() => { setActivePinia(createPinia()); });
import SavedModelDiagnostics from "@/components/SavedModelDiagnostics.vue";

const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ default: { get: apiGet } }));

const receipt = {
  model_kind: "pca",
  graph_digest: "graph",
  source_digest: "source",
  n_calibration: 2,
  n_components: 2,
  calibration_t2_limit: 5,
  application_t2_limit: 6,
  q_limit: 2,
  q_limit_method: "fixture",
  rows: [
    { id: "source-a:1", role: "calibration", group: "batch A", scores: [1, 2], t2: 1, q: 0.2 },
    { id: "source-b:1", role: "calibration", group: "batch B", scores: [2, 3], t2: 2, q: 0.3 },
    { id: "test:1", role: "held_out_test", group: "batch B", scores: [4, 5], t2: 4, q: 1.1 },
  ],
  explanations: {
    schema_version: "test",
    model_digest: "fit",
    feature_identity: "features",
    reference_digest: "reference",
    reference_count: 2,
    formula: "fitted",
    space: "model",
    preprocessing: [],
    feature_count: 2,
    feature_labels: null,
    feature_values: [100, 200],
    feature_units: "cm⁻¹",
    top_per_statistic: 2,
    loadings: [
      [0.1, 0.2],
      [0.3, 0.4],
    ],
    loadings_unavailable_reason: null,
    rows: {},
  },
};
const plotStub = {
  name: "PlotlyChart",
  props: ["data", "layout", "selectedPointIds"],
  template: '<div class="plotly-stub" />',
};

describe("saved model diagnostic workbench", () => {
  it("uses exact source-run rows and links chart selection to the table", async () => {
    apiGet.mockResolvedValue({
      data: {
        run_id: 42,
        node_id: "fit",
        receipt,
        decision: { marked: ["source-b:1"], excluded: [], heldout_excluded: [] },
        review_revision: 3,
        post_review: false,
        decision_unavailable_reason: null,
      },
    });
    const wrapper = mount(SavedModelDiagnostics, {
      props: { artifactUid: "saved-1", projectId: 9, workflowId: 7, nodeId: "fit" },
      global: {
        stubs: {
          PlotlyChart: plotStub,
          PcaExplanation: true,
          PlsApplicability: true,
          PlsExplanation: true,
          DiagnosticAdvisor: true,
          DatasetCurationPanel: true,
        },
      },
    });
    await flushPromises();
    expect(apiGet).toHaveBeenCalledWith("/models/saved-1/diagnostics", {
      params: { project_id: 9 },
      signal: expect.any(AbortSignal),
    });
    const plots = wrapper.findAllComponents({ name: "PlotlyChart" });
    expect(plots).toHaveLength(3); // Scores, T²/Q and component loadings.
    expect(plots[0].props("data")[0].customdata).toContain("source-a:1");
    plots[0].vm.$emit("selected", { points: [{ customdata: "source-b:1" }] });
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain("1 observations selected");
    expect(wrapper.get('input[aria-label="Select sample source-b:1"]').element).toHaveProperty(
      "checked",
      true,
    );
    expect(plots[1].props("selectedPointIds")).toEqual(["source-b:1"]);
    expect(wrapper.text()).toContain("marked outlier");
    expect(plots[1].props("layout").shapes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ x0: 5 }),
        expect.objectContaining({ x0: 6, line: expect.objectContaining({ dash: "dash" }) }),
      ]),
    );
    const explanation = wrapper.findComponent({ name: "PcaExplanation" });
    explanation.vm.$emit("advisor-selection", {
      variables: ["feature:0"],
      response: 0,
      sample: "source-b:1",
    });
    await wrapper.vm.$nextTick();
    const advisor = wrapper.findComponent({ name: "DiagnosticAdvisor" });
    expect(advisor.props("variables")).toEqual(["feature:0"]);
    expect(advisor.props("variableContext")).toBeUndefined();
    wrapper.unmount();
  });

  it("does not treat missing historical review decisions as no marks", async () => {
    apiGet.mockResolvedValue({
      data: {
        run_id: 42,
        node_id: "fit",
        receipt,
        decision: { marked: null, excluded: null, heldout_excluded: null },
        review_revision: null,
        post_review: false,
        decision_unavailable_reason:
          "This historical run did not retain exact outlier mark decisions.",
      },
    });
    const wrapper = mount(SavedModelDiagnostics, {
      props: { artifactUid: "old-1", projectId: 9, workflowId: 7, nodeId: "fit" },
      global: {
        stubs: {
          PlotlyChart: plotStub,
          PcaExplanation: true,
          PlsApplicability: true,
          PlsExplanation: true,
          DiagnosticAdvisor: true,
          DatasetCurationPanel: true,
        },
      },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("did not retain exact outlier mark decisions");
    expect(wrapper.findComponent({ name: "DiagnosticAdvisor" }).exists()).toBe(false);
    wrapper.unmount();
  });

  it("clears Advisor feature focus when switching from PCA to a PLS artifact", async () => {
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({
        data: {
          run_id: url.includes("saved-pls") ? 52 : 42,
          node_id: "fit",
          receipt: url.includes("saved-pls")
            ? {
                ...receipt,
                model_kind: "pls",
                target_names: ["analyte"],
                target_units: ["mg/L"],
                pls_explanations: { unavailable_reason: "fixture" },
              }
            : receipt,
          decision: { marked: [], excluded: [], heldout_excluded: [] },
          review_revision: 0,
          post_review: false,
          decision_unavailable_reason: null,
        },
      }),
    );
    const wrapper = mount(SavedModelDiagnostics, {
      props: { artifactUid: "saved-pca", projectId: 9, workflowId: 7, nodeId: "fit" },
      global: {
        stubs: {
          PlotlyChart: plotStub,
          PcaExplanation: true,
          PlsApplicability: true,
          PlsExplanation: true,
          DiagnosticAdvisor: true,
          DatasetCurationPanel: true,
        },
      },
    });
    await flushPromises();
    wrapper.findComponent({ name: "PcaExplanation" }).vm.$emit("advisor-selection", {
      variables: ["old-pca-feature:0"],
      response: 0,
      sample: "source-b:1",
    });
    await wrapper.vm.$nextTick();
    expect(wrapper.findComponent({ name: "DiagnosticAdvisor" }).props("variables")).toEqual([
      "old-pca-feature:0",
    ]);
    await wrapper.setProps({ artifactUid: "saved-pls" });
    await flushPromises();
    wrapper.get('input[aria-label="Select sample source-b:1"]').setValue(true);
    await wrapper.vm.$nextTick();
    const advisor = wrapper.findComponent({ name: "DiagnosticAdvisor" });
    expect(advisor.props("variables")).toEqual([]);
    expect(advisor.props("focusedSample")).toBe("");
    expect(advisor.props("variableContext")).toBeUndefined();
    wrapper.unmount();
  });
});

describe("saved diagnostic quantity labels", () => {
  const mountReceipt = async (saved: Record<string, unknown>) => {
    apiGet.mockResolvedValue({ data: { run_id: 42, node_id: "fit", receipt: saved,
      decision: { marked: [], excluded: [], heldout_excluded: [] },
      review_revision: 0, post_review: false, decision_unavailable_reason: null } });
    const wrapper = mount(SavedModelDiagnostics, {
      props: { artifactUid: "units-review", projectId: 9, workflowId: 7, nodeId: "fit" },
      global: { stubs: { PlotlyChart: plotStub, PcaExplanation: true, PlsExplanation: true,
        PlsApplicability: true, DiagnosticAdvisor: true, DatasetCurationPanel: true } },
    });
    await flushPromises();
    return wrapper;
  };
  it("keeps the chosen response name and units on prediction and residual axes", async () => {
    const wrapper = await mountReceipt({ ...receipt, model_kind: "pls",
      target_names: ["Methane", "Carbon dioxide"], target_units: ["ppm", "percent"],
      pls_explanations: { unavailable_reason: "Not retained" } });
    const layout = (title: string) => wrapper.findAllComponents({ name: "PlotlyChart" })
      .map(plot => plot.props("layout")).find(value => value.title === title);
    expect(layout("Predicted versus measured")).toMatchObject({
      xaxis: { title: "Measured Methane (ppm)" }, yaxis: { title: "Predicted Methane (ppm)" } });
    expect(layout("Residuals")).toMatchObject({
      xaxis: { title: "Predicted Methane (ppm)" },
      yaxis: { title: "Residual Methane (ppm) (measured − predicted)" } });
    const responseSelect = wrapper.findAll("select").find(select => select.text().includes("Carbon dioxide"))!;
    await responseSelect.setValue("1");
    expect(layout("Predicted versus measured").yaxis.title).toBe("Predicted Carbon dioxide (percent)");
    expect(layout("Residuals").yaxis.title).toContain("Carbon dioxide (percent)");
    wrapper.unmount();
  });
  it.each([null, "cm⁻¹"])("does not call retained coordinates indices or infer their physical meaning (%s)", async units => {
    const wrapper = await mountReceipt({ ...receipt, explanations: { ...receipt.explanations, feature_units: units } });
    const layout = wrapper.findAllComponents({ name: "PlotlyChart" }).map(plot => plot.props("layout"))
      .find(value => String(value.title).includes("loadings"));
    expect(layout.xaxis.title).toBe(units ? "Fitted feature coordinate (cm⁻¹)" : "Fitted feature coordinate");
    wrapper.unmount();
  });
  it("uses variable index only without retained feature coordinates", async () => {
    const wrapper = await mountReceipt({ ...receipt, explanations: { ...receipt.explanations, feature_values: null, feature_units: null } });
    const plot = wrapper.findAllComponents({ name: "PlotlyChart" }).find(plot => String(plot.props("layout").title).includes("loadings"))!;
    expect(plot.props("layout").xaxis.title).toBe("Variable index");
    expect(plot.props("data")[0].x).toEqual([1, 2]);
    wrapper.unmount();
  });
});
