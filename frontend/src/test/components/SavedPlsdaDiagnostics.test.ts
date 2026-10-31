import { ref } from "vue";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
beforeEach(() => { setActivePinia(createPinia()); });
import SavedPlsdaDiagnostics from "@/components/SavedPlsdaDiagnostics.vue";

const apiGet = vi.hoisted(() => vi.fn());
const advisorPrompt = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ default: { get: apiGet } }));
vi.mock("@/stores/sherpa", () => ({ useSherpaStore: () => ({ chatState: "idle" }) }));
vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appConfig: ref({ siteProfile: "pro", advisorContextPolicy: "hosted" }),
    appMode: ref("hosted"),
    isFeatureEnabled: () => true,
  }),
}));
vi.mock("@/lib/advisorPromptActions", () => ({ requestAdvisorPrompt: advisorPrompt }));

const receipt = {
  schema_version: "spectrasherpa-plsda-sample-diagnostics/1",
  model_kind: "plsda",
  reference_population: "fitted calibration observations",
  reference_count: 2,
  components: 2,
  feature_values: [1000, 1100],
  feature_labels: null,
  feature_units: "cm-1",
  space: "internally centered predictor space",
  q_units: "squared input signal units",
  t2_units: "dimensionless",
  t2_limit: 5,
  screening_method: "prediction_f_and_residual_spectrum_0.95_strict_greater",
  q_limit_method: "jackson_mudholkar",
  score_covariance_rank: 2,
  q_limit: 2,
  t2_unavailable_reason: null,
  q_unavailable_reason: null,
  rows: [
    {
      id: "a:1",
      class: "A",
      role: "calibration",
      scores: [1, 2],
      t2: 1,
      q: 0.2,
      outside_t2: false,
      outside_q: false,
      terms: {
        variables: [
          [0, 0.1, 0.8],
          [1, 0.1, 0.2],
        ],
        omitted_q: 0,
        omitted_t2: 0,
        omitted_t2_absolute: 0,
      },
    },
    {
      id: "b:1",
      class: "B",
      role: "calibration",
      scores: [2, 3],
      t2: 6,
      q: 0.3,
      outside_t2: true,
      outside_q: false,
      terms: {
        variables: [
          [0, 0.2, 4],
          [1, 0.1, 2],
        ],
        omitted_q: 0,
        omitted_t2: 0,
        omitted_t2_absolute: 0,
      },
    },
  ],
};
const plotStub = {
  name: "PlotlyChart",
  props: ["data", "layout", "selectedPointIds"],
  template: '<div class="plotly-stub" />',
};

describe("saved PLS-DA diagnostics", () => {
  it("displays duplicate source labels while keeping exact IDs for selection, terms and Advisor references", async () => {
    advisorPrompt.mockClear();
    const label = '<Sample, "shared" | &>';
    const escaped = '&lt;Sample, &quot;shared&quot; | &amp;&gt;';
    const labelled = {
      ...structuredClone(receipt),
      rows: receipt.rows.map((row) => ({ ...structuredClone(row), display_label: label })),
    };
    const original = JSON.stringify(labelled);
    apiGet.mockResolvedValue({
      data: { run_id: 42, node_id: "fit", receipt_sha256: "a".repeat(64), receipt: labelled },
    });
    const wrapper = mount(SavedPlsdaDiagnostics, {
      props: { artifactUid: "saved-labels", projectId: 9, nodeId: "fit", workflowId: 7 },
      global: { stubs: { PlotlyChart: plotStub } },
    });
    await flushPromises();
    const rows = wrapper.findAll("tbody tr");
    expect(rows.map((row) => row.findAll("td")[1].text())).toEqual([label, label]);
    expect(rows.map((row) => row.findAll("td")[1].attributes("title"))).toEqual(["a:1", "b:1"]);
    const boxes = wrapper.findAll('input[type="checkbox"]');
    expect(boxes.map((box) => box.attributes("aria-label"))).toEqual([
      `Select sample ${label}`, `Select sample ${label}`,
    ]);
    expect(wrapper.find("sample").exists()).toBe(false);
    for (const plot of wrapper.findAllComponents({ name: "PlotlyChart" })) {
      const traces = plot.props("data");
      expect(traces.map((trace: { customdata: string[] }) => trace.customdata)).toEqual([["a:1"], ["b:1"]]);
      expect(traces.map((trace: { text: string[] }) => trace.text)).toEqual([[escaped], [escaped]]);
      expect(traces[0].hovertemplate).toContain("%{text}");
    }
    await boxes[1].setValue(true);
    expect(boxes[0].element).toHaveProperty("checked", false);
    expect(boxes[1].element).toHaveProperty("checked", true);
    expect(wrapper.get("h4").text()).toBe(`Why ${label} has this T²/Q`);
    expect(wrapper.get("h4").attributes("title")).toBe("b:1");
    const plots = wrapper.findAllComponents({ name: "PlotlyChart" });
    expect(plots[0].props("selectedPointIds")).toEqual(["b:1"]);
    expect(plots[2].props("data")[0].y).toEqual([0.2, 0.1]);
    expect(plots[3].props("data")[0].y).toEqual([4, 2]);
    expect(plots[2].props("layout").title).toBe(`Selected-sample Q terms — ${escaped}`);
    expect(plots[3].props("layout").title).toBe(`Selected-sample signed T² terms — ${escaped}`);
    await wrapper.findAll("button").find((b) => b.text().includes("Explain this sample"))!.trigger("click");
    expect(advisorPrompt.mock.lastCall?.[1].diagnosticScope.reference).toEqual({
      kind: "saved_plsda", artifact_uid: "saved-labels", workflow_id: 7, run_id: 42,
      node_id: "fit", receipt_sha256: "a".repeat(64), selected_ids: ["b:1"],
      select_all: false, variable_ids: [],
    });
    await wrapper.get('input[type="search"]').setValue("shared");
    expect(wrapper.findAll("tbody tr")).toHaveLength(2);
    await wrapper.get('input[type="search"]').setValue("b:1");
    expect(wrapper.findAll("tbody tr")).toHaveLength(1);
    plots[0].vm.$emit("selected", { points: [{ customdata: label }] });
    await wrapper.vm.$nextTick();
    expect(plots[0].props("selectedPointIds")).toEqual([]);
    plots[0].vm.$emit("selected", { points: [{ customdata: "a:1" }] });
    await wrapper.vm.$nextTick();
    expect(plots[0].props("selectedPointIds")).toEqual(["a:1"]);
    expect(wrapper.get("h4").attributes("title")).toBe("a:1");
    expect(wrapper.findAllComponents({ name: "PlotlyChart" })[2].props("data")[0].y).toEqual([0.1, 0.1]);
    expect(JSON.stringify(labelled)).toBe(original);
    wrapper.unmount();
  });

  it("links a selected classifier row to exact additive variable terms", async () => {
    advisorPrompt.mockClear();
    apiGet.mockResolvedValue({
      data: { run_id: 42, node_id: "fit", receipt_sha256: "a".repeat(64), receipt },
    });
    const wrapper = mount(SavedPlsdaDiagnostics, {
      props: { artifactUid: "saved-1", projectId: 9, nodeId: "fit", workflowId: 7 },
      global: { stubs: { PlotlyChart: plotStub } },
    });
    await flushPromises();
    expect(apiGet).toHaveBeenCalledWith("/models/saved-1/plsda-diagnostics", {
      params: { project_id: 9 },
      signal: expect.any(AbortSignal),
    });
    const plots = wrapper.findAllComponents({ name: "PlotlyChart" });
    expect(plots).toHaveLength(2);
    plots[1].vm.$emit("selected", { points: [{ customdata: "b:1" }] });
    await wrapper.vm.$nextTick();
    expect(advisorPrompt).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("Why b:1 has this T²/Q");
    await wrapper
      .findAll("button")
      .find((button) => button.text().includes("Explain this sample"))!
      .trigger("click");
    expect(advisorPrompt).toHaveBeenCalledWith(expect.any(String), {
      diagnosticScope: {
        project_id: 9,
        model_kind: "plsda",
        reference: {
          kind: "saved_plsda",
          artifact_uid: "saved-1",
          workflow_id: 7,
          run_id: 42,
          node_id: "fit",
          receipt_sha256: "a".repeat(64),
          selected_ids: ["b:1"],
          select_all: false,
          variable_ids: [],
        },
      },
    });
    expect(wrapper.get('input[aria-label="Select sample b:1"]').element).toHaveProperty(
      "checked",
      true,
    );
    const termPlots = wrapper.findAllComponents({ name: "PlotlyChart" });
    expect(termPlots[2].props("data")[0].y).toEqual([0.2, 0.1]);
    expect(termPlots[3].props("data")[0].y).toEqual([4, 2]);
    expect(termPlots[2].props("layout").yaxis.title).toContain("squared input signal units");
    expect(termPlots[3].props("layout").yaxis.title).toContain("dimensionless");
    expect(wrapper.text()).toContain("Outside global screen");
    wrapper.unmount();
  });

  it("keeps Q-only rank-deficient observations selectable and preserves a zero feature coordinate", async () => {
    const qOnly = structuredClone(receipt);
    qOnly.t2_limit = null;
    qOnly.t2_unavailable_reason = "rank_deficient_score_covariance";
    qOnly.feature_values[0] = 0;
    qOnly.rows.forEach((row) => {
      row.t2 = null;
      row.outside_t2 = null;
      row.terms.variables = row.terms.variables.map(([i, q]) => [i, q, null]);
      row.terms.omitted_t2 = null;
      row.terms.omitted_t2_absolute = null;
    });
    apiGet.mockResolvedValue({
      data: { run_id: 43, node_id: "fit", receipt_sha256: "b".repeat(64), receipt: qOnly },
    });
    const wrapper = mount(SavedPlsdaDiagnostics, {
      props: { artifactUid: "saved-2", projectId: 9, nodeId: "fit", workflowId: 7 },
      global: { stubs: { PlotlyChart: plotStub } },
    });
    await flushPromises();
    const influence = wrapper.findAllComponents({ name: "PlotlyChart" })[1];
    expect(influence.props("layout").title).toContain("T² unavailable");
    expect(influence.props("data")[0].customdata).toContain("a:1");
    influence.vm.$emit("selected", { points: [{ customdata: "a:1" }] });
    await wrapper.vm.$nextTick();
    const plots = wrapper.findAllComponents({ name: "PlotlyChart" });
    expect(plots).toHaveLength(3); // Scores, Q by order, and Q contributions; no T² terms.
    expect(plots[2].props("data")[0].x[0]).toBe(0);
    wrapper.unmount();
  });
});
