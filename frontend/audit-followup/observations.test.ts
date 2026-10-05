/** OPEN-defect reproductions: passing means the defect is still present, not acceptance. */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import PrimeVue from "primevue/config";
import ComparisonPanel from "@/views/experiments/ComparisonPanel.vue";

describe("cross-cutting comparison reconstruction review", () => {
  it("demonstrates synthetic path and cross-node split setting composition", () => {
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
    expect(rows).toContain("Node pathsource → branch b → branch a → split a → split b");
    expect(rows).toContain("Split settingsduplex · 20% test · seed 99");
    wrapper.unmount();
  });
});

import { buildRegressionComparisonPlot, buildPeakTablePlot } from "@/utils/scientificPlots";
describe("XGSC-05 silent partial population loss (open)", () => {
  it("drops an invalid response row without disclosed exclusion counts", () => {
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
    expect(plot.data[0].x).toEqual([1]);
    expect(plot.layout.meta?.display_population).toBeUndefined();
    expect(plot.layout.meta?.refusal_reason).toBeUndefined();
  });
  it("drops an invalid peak without disclosed exclusion counts", () => {
    const plot = buildPeakTablePlot([
      { median_pos: 100, median_height: 1 },
      { median_pos: 200, median_height: null },
    ]);
    expect(plot.data[0].x).toEqual([100]);
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
describe("open execution-binding observations using the real workflow store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });
  function setup() {
    const store = useWorkflowStore();
    store.workflowId = 901;
    store.nodes = [
      { id: "source", type: "data.source", x: 0, y: 0, params: {} },
      { id: "preprocess", type: "preprocess.scale", x: 1, y: 0, params: { method: "center" } },
      { id: "pca", type: "model.pca", x: 2, y: 0, params: { n_components: 2 } },
    ];
    store.hasUnsavedChanges = false;
    return store;
  }
  const response = {
    run_id: 10,
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
  it("XGSC-02 discards the returned run identity", async () => {
    const store = setup();
    vi.mocked(api.post).mockResolvedValueOnce({ data: response });
    const execution = await store.executeWorkflow();
    expect((execution as any).run_id).toBe(10);
    expect(store.restoredRunId).toBeNull();
  });
  it("XGSC-03 merges node execution B with downstream output A", async () => {
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
    expect(store.lastExecutionResults).toEqual({ source: [[11]], preprocess: [[22]], pca: [[3]] });
    expect(store.nodes[2].executionState?.status).toBe("completed");
  });
});

import { effectScope, ref } from "vue";
import { useQuickPlotProjection } from "@/composables/useScientificPlotProjection";
describe("XGSC-06 cohort changes when switching canonical views (open)", () => {
  it("includes the excluded sentinel row in heatmap while overlay excludes it", () => {
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
      expect(plot.plotData.value[0].z).toEqual([
        [1, 2],
        [999, 999],
      ]);
      expect((plot.plotLayout.value as any).meta?.display_population).toBeUndefined();
    });
    scope.stop();
  });
});
