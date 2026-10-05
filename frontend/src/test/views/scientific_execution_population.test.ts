/** Desired-behavior regressions for execution and population authority. */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import PrimeVue from "primevue/config";
import ComparisonPanel from "@/views/experiments/ComparisonPanel.vue";

describe("XGSC-04 faithful comparison provenance", () => {
  it("labels unordered nodes and keeps split settings attached to their node", () => {
    const run = {
      id: 901,
      name: "Branched run",
      params_snapshot: {
        source: {},
        branch_b: {},
        branch_a: {},
        split_a: { test_size: 0.2 },
        split_b: { split_method: "duplex", random_seed: 99 },
      },
      results_summary: {},
      diagnostics: {},
      node_statuses: {},
      labels: [],
      produced_artifact_uids: [],
      attempted_artifact_uids: [],
      succeeded_artifact_uids: [],
      executed_at: "2026-09-21T00:00:00Z",
      run_kind: "training",
    };
    const wrapper = mount(ComparisonPanel, {
      props: { runs: [run as any], metricKeys: [], diff: {} },
      global: { plugins: [PrimeVue], stubs: { RouterLink: true } },
    });
    const rows = wrapper.findAll("tr").map((row) => row.text());
    expect(rows.join(" ")).not.toContain(" → ");
    expect(rows.join(" ")).toContain("split_a: test_size 0.2; split_b: method duplex · seed 99");
    wrapper.unmount();
  });
});

import { buildRegressionComparisonPlot, buildPeakTablePlot } from "@/utils/scientificPlots";
describe("XGSC-05 silent partial population loss (fixed)", () => {
  it("refuses an invalid response row with the retained denominator", () => {
    const plot = buildRegressionComparisonPlot([
      {
        sample: "A",
        target: "y",
        reference: 1,
        predicted: 1.1,
        residual: -0.1,
        role: "held_out_test",
      },
      {
        sample: "B",
        target: "y",
        reference: null,
        predicted: 2.1,
        residual: null,
        role: "held_out_test",
      },
    ]);
    expect(plot.data).toEqual([]);
    expect(plot.layout.meta.refusal_reason).toContain("1 of 2");
    expect(plot.layout.meta?.display_population).toBeUndefined();
  });
  it("refuses an invalid peak with the retained denominator", () => {
    const plot = buildPeakTablePlot([
      { median_pos: 100, median_height: 1 },
      { median_pos: 200, median_height: null },
    ]);
    expect(plot.data).toEqual([]);
    expect(plot.layout.meta.refusal_reason).toContain("1 of 2");
    expect(plot.layout.meta?.display_population).toBeUndefined();
  });
});

import { vi, beforeEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import api from "@/api/client";
import { useWorkflowStore } from "@/stores/workflow";
vi.mock("@/api/client", () => ({ default: { post: vi.fn(), get: vi.fn(), put: vi.fn() } }));
vi.mock("@/stores/workbook", () => ({
  useWorkbookStore: () => ({ activeSheet: null, sheets: [] }),
}));
vi.mock("@/stores/job", () => ({ useJobStore: () => ({ wsRef: null }) }));
describe("execution-binding regressions using the real workflow store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });
  function setup() {
    const store = useWorkflowStore();
    store.workflowId = 901;
    store.nodes = [
      { id: "source", type: "data.file_load", x: 0, y: 0, params: {} },
      { id: "preprocess", type: "preprocess.scale", x: 1, y: 0, params: { method: "center" } },
      { id: "pca", type: "model.pca", x: 2, y: 0, params: { n_components: 2 } },
    ];
    store.hasUnsavedChanges = false;
    return store;
  }
  const response = {
    run_id: 10,
    status: "completed",
    results: { source: [[1]], preprocess: [[2]], pca: [[3]] },
    node_statuses: { source: "completed", preprocess: "completed", pca: "completed" },
  };
  it("XGSC-01 preserves completed prior evidence after a semantic edit", async () => {
    const store = setup();
    vi.mocked(api.post).mockResolvedValueOnce({ data: response });
    await store.executeWorkflow();
    store.updateNode("pca", { params: { n_components: 5 } });
    expect(store.isWorkflowStale).toBe(true);
    expect(store.nodes[2].params.n_components).toBe(5);
    expect(store.nodes[2].executionState?.status).toBe("completed");
    expect(store.lastExecutionResults?.pca).toEqual([[3]]);
  });
  it("XGSC-02 retains the returned run identity", async () => {
    const store = setup();
    vi.mocked(api.post).mockResolvedValueOnce({ data: response });
    const execution = await store.executeWorkflow();
    expect((execution as any).run_id).toBe(10);
    expect(store.restoredRunId).toBe(10);
  });
  it("XGSC-03 replaces output A with the coherent partial snapshot B", async () => {
    const store = setup();
    vi.mocked(api.post).mockResolvedValueOnce({ data: response });
    await store.executeWorkflow();
    store.updateNode("preprocess", { params: { method: "autoscale" } });
    store.hasUnsavedChanges = false; // Equivalent to saving the edited graph before Run Node.
    vi.mocked(api.post).mockResolvedValueOnce({
      data: {
        run_id: 11,
        results: { source: [[11]], preprocess: [[22]] },
        node_statuses: { source: "completed", preprocess: "completed" },
      },
    });
    await store.executeNode("preprocess");
    expect(store.lastExecutionResults).toEqual({ source: [[11]], preprocess: [[22]] });
    expect(store.nodes[2].executionState?.status).toBe("pending");
  });
  it("keeps a graph edited during an in-flight run stale", async () => {
    const store = setup();
    let resolve!: (response: any) => void;
    vi.mocked(api.post).mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const pending = store.executeWorkflow();
    await vi.waitFor(() => expect(api.post).toHaveBeenCalled());
    store.updateNode("pca", { params: { n_components: 5 } });
    resolve({ data: { ...response, params_snapshot: { pca: { n_components: 2 } } } });
    await pending;
    expect(store.isWorkflowStale).toBe(true);
    expect(store.lastExecutionParams.pca.n_components).toBe(2);
    expect(store.restoredRunId).toBe(10);
  });
  it("refuses overlapping execution and unbound workflow status events", async () => {
    const store = setup();
    let resolve!: (response: any) => void;
    vi.mocked(api.post).mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const pending = store.executeWorkflow();
    await vi.waitFor(() => expect(api.post).toHaveBeenCalled());
    await expect(store.executeNode("source")).rejects.toThrow("already in progress");
    window.dispatchEvent(
      new CustomEvent("workflow-node-status", { detail: { node_id: "pca", status: "completed" } }),
    );
    expect(store.nodes[2].executionState?.status).toBe("pending");
    expect(store.isExecuting).toBe(true);
    resolve({ data: response });
    await pending;
    expect(store.restoredRunId).toBe(10);
    expect(store.isExecuting).toBe(false);
  });
  it.each(["full", "node"])("refuses edits while saving before %s execution", async (mode) => {
    const store = setup();
    store.hasUnsavedChanges = true;
    vi.mocked(api.put).mockImplementationOnce(async () => {
      store.updateNode("pca", { params: { n_components: 7 } });
      return { data: { id: 901 } };
    });
    vi.mocked(api.post).mockResolvedValueOnce({ data: { semantic_edges: [], issues: [] } });
    const action = mode === "full" ? store.executeWorkflow() : store.executeNode("pca");
    await expect(action).rejects.toThrow("changed while saving");
    expect(api.post).not.toHaveBeenCalledWith(
      expect.stringContaining("/execute"),
      expect.anything(),
      expect.anything(),
    );
    expect(store.isWorkflowStale).toBe(true);
    expect(store.restoredRunId).toBeNull();
    expect(store.isExecuting).toBe(false);
  });
  it("refuses prior-result authority during a new attempt and after its failure", async () => {
    const store = setup();
    vi.mocked(api.post).mockResolvedValueOnce({ data: response });
    await store.executeWorkflow();
    let reject!: (error: Error) => void;
    vi.mocked(api.post).mockImplementationOnce(
      () =>
        new Promise((_done, fail) => {
          reject = fail;
        }),
    );
    const pending = store.executeNode("pca");
    await vi.waitFor(() => expect(store.isExecuting).toBe(true));
    expect(store.lastExecutionResults).toBeNull();
    expect(store.restoredRunId).toBeNull();
    expect(store.isWorkflowStale).toBe(true);
    reject(new Error("offline"));
    await expect(pending).rejects.toThrow("offline");
    expect(store.lastExecutionResults).toBeNull();
    expect(store.isExecuting).toBe(false);
    expect(store.restoredEvidenceNotice).toContain("did not finish");
  });
  it.each(["full", "node"])(
    "aborts %s results after navigation without restoring old evidence",
    async (mode) => {
      const store = setup();
      let resolve!: (value: any) => void;
      vi.mocked(api.post).mockImplementationOnce(
        () =>
          new Promise((done) => {
            resolve = done;
          }),
      );
      const pending = mode === "full" ? store.executeWorkflow() : store.executeNode("pca");
      await vi.waitFor(() => expect(api.post).toHaveBeenCalled());
      store.clearWorkflow();
      store.workflowId = 902;
      store.restoredEvidenceNotice = "Workflow B";
      resolve({ data: response });
      await expect(pending).rejects.toMatchObject({ name: "AbortError" });
      expect(store.lastExecutionResults).toBeNull();
      expect(store.restoredRunId).toBeNull();
      expect(store.restoredEvidenceNotice).toBe("Workflow B");
    },
  );
});

import { effectScope, ref } from "vue";
import { useQuickPlotProjection } from "@/composables/useScientificPlotProjection";
describe("XGSC-06 cohort changes when switching canonical views (fixed)", () => {
  it("excludes the sentinel in both heatmap and overlay", () => {
    const scope = effectScope();
    scope.run(() => {
      const output = ref({
        data: [
          [1, 2],
          [999, 999],
        ],
        presentation_value: {
          data: [
            [1, 2],
            [999, 999],
          ],
          sample_axis: { include_mask: [true, false] },
        },
        metadata: {
          scientific_presentation: {
            schema_version: "spectrasherpa-node-presentation/1",
            contract_digest: "a".repeat(64),
            presentation_id: "result",
            kind: "spectral_dataset",
            source_port: "result",
            source_ports: ["result"],
            modes: ["plot"],
          },
        },
      });
      const plot = useQuickPlotProjection(output, ref(""));
      plot.selectedPlotKey.value = "scientific_spectral_overlay";
      expect(plot.plotData.value.map((trace) => trace.y)).toEqual([[1, 2]]);
      plot.selectedPlotKey.value = "scientific_spectral_heatmap";
      expect(plot.plotData.value[0].z).toEqual([[1, 2]]);
      expect((plot.plotLayout.value as any).meta.display_population.excluded).toBe(1);
    });
    scope.stop();
  });
});
