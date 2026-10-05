import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  connect: vi.fn(),
  featureEnabled: vi.fn(),
  sentMessages: [] as string[],
  ws: {
    readyState: 1,
    send: vi.fn((payload: string) => {
      mocks.sentMessages.push(payload);
    }),
  },
}));

vi.mock("@/api/client", () => ({
  default: {
    get: mocks.apiGet,
  },
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    isFeatureEnabled: mocks.featureEnabled,
  }),
}));

vi.mock("@/stores/llm", () => ({
  useLlmStore: () => ({
    connect: mocks.connect,
    wsRef: mocks.ws,
  }),
}));

vi.mock("@/stores/advisor", () => ({
  useAdvisorStore: () => ({
    activeNodeId: "advisor-report",
  }),
}));

vi.mock("@/stores/project", () => ({
  useProjectStore: () => ({
    currentProjectId: 17,
  }),
}));

import { createPinia, setActivePinia } from "pinia";
import {
  buildReportExperimentPayload,
  type ExtendedReportData,
  useReportStore,
} from "@/stores/report";
import { dispatchSherpaEvent } from "@/lib/sherpaEvents";
import { SHERPA_WS_ACTION, SHERPA_WS_EVENT } from "@/lib/sherpaWs";

const makeReportData = (): ExtendedReportData => ({
  workflow_id: 7,
  name: "MCR and Library Benchmark",
  description: "Synthetic FTIR benchmark",
  technique: "FTIR",
  sample_type: "atmospheric gases",
  integrity_hash: "workflow-hash",
  created_at: "2026-06-03T00:00:00Z",
  updated_at: "2026-06-03T00:00:00Z",
  nodes: [
    {
      node_id: "model_1",
      node_type: "decomposition.mcr_als",
      label: "MCR-ALS",
      parameters: { n_components: 4, normSpec: "euclid" },
      position_x: 0,
      position_y: 0,
    },
  ],
  edges: [],
  runs: [
    {
      id: 42,
      name: "MCR - benchmark",
      status: "completed",
      executed_at: "2026-06-03T01:00:00Z",
      results_summary: {
        compare_1: { top_hqi: 997.5, best_match: "Water" },
      },
      diagnostics: {
        model_1: {
          lof_percent: 0.8,
          ground_truth_comparison: { mean_abs_correlation: 0.98 },
        },
        compare_1: {
          best_match_known_present_rate: 1,
          n_auto_selected: 5,
        },
      },
      params_snapshot: {
        compare_1: { hqi_mode: "band_limited" },
      },
      node_statuses: {
        model_1: "completed",
        compare_1: "completed",
      },
      integrity_hash: "run-hash",
      labels: ["release-smoke"],
    },
  ],
  comparison: {
    metric_keys: ["compare_1.top_hqi"],
    diff: { "compare_1.top_hqi": { "42": 997.5 } },
  },
});

beforeEach(() => {
  setActivePinia(createPinia());
  mocks.apiGet.mockReset();
  mocks.connect.mockReset();
  mocks.connect.mockResolvedValue(undefined);
  mocks.featureEnabled.mockReset();
  mocks.featureEnabled.mockReturnValue(true);
  mocks.sentMessages = [];
  mocks.ws.readyState = WebSocket.OPEN;
  mocks.ws.send.mockClear();
});

describe("report payload assembly", () => {
  it("freezes the project evidence at generation and labels unavailable evidence honestly", async () => {
    const store = useReportStore();
    store.selectedWorkflowId = 7;
    const report = { ...makeReportData(), workflow_identity: {
      schema_version: 1 as const, project_id: 17, workflow_id: 7,
      workflow_name: "MCR and Library Benchmark", template_name: null, template_version: null,
      source_name: null, source_origin: "current" as const, source_node_id: null,
    } };
    const records = [{ kind: "source", label: "Source file", state: "healthy", name: "corn.mat", digest: "a".repeat(64), record_id: 1, detail: "verified", destination: "/data" }];
    mocks.apiGet.mockResolvedValueOnce({ data: report }).mockResolvedValueOnce({ data: {
      project_id: 17, project_name: "Corn", records, choice_event_ids: {},
    } });
    await store.fetchReportData();
    expect(mocks.apiGet).toHaveBeenCalledWith("/projects/17/provenance");
    expect(store.projectEvidenceSnapshot?.state).toBe("available");
    expect(store.projectEvidenceSnapshot?.records[0].digest).toBe("a".repeat(64));
    store.reset();
    expect(store.projectEvidenceSnapshot).toBeNull();

    store.selectedWorkflowId = 7;
    mocks.apiGet.mockResolvedValueOnce({ data: report }).mockRejectedValueOnce(new Error("offline"));
    await store.fetchReportData();
    expect(store.reportData).not.toBeNull();
    expect(store.projectEvidenceSnapshot?.state).toBe("unavailable");
  });
  it("discards an in-flight project snapshot when its report scope is reset", async () => {
    const store = useReportStore();
    store.selectedWorkflowId = 7;
    const report = { ...makeReportData(), workflow_identity: {
      schema_version: 1 as const, project_id: 17, workflow_id: 7,
      workflow_name: "MCR and Library Benchmark", template_name: null, template_version: null,
      source_name: null, source_origin: "current" as const, source_node_id: null,
    } };
    let resolveEvidence!: (value: { data: unknown }) => void;
    mocks.apiGet.mockResolvedValueOnce({ data: report });
    mocks.apiGet.mockImplementationOnce(() => new Promise((resolve) => { resolveEvidence = resolve; }));
    const pending = store.fetchReportData();
    await Promise.resolve();
    await Promise.resolve();
    store.resetProjectScope();
    resolveEvidence({ data: { project_id: 17, records: [], choice_event_ids: {} } });
    await pending;
    expect(store.reportData).toBeNull();
    expect(store.projectEvidenceSnapshot).toBeNull();
  });
  it("defaults and resets to free scientific summary without starting AI", () => {
    const store = useReportStore();
    expect(store.reportMode).toBe("summary");
    expect(store.sections.aiNarrative).toBe(false);
    store.reportMode = "detailed";
    store.sections.aiNarrative = true;
    store.reset();
    expect(store.reportMode).toBe("summary");
    expect(store.sections.aiNarrative).toBe(false);
    expect(mocks.connect).not.toHaveBeenCalled();
  });
  it("lists only initialized sheets in the active project with source identity", async () => {
    mocks.apiGet.mockResolvedValueOnce({
      data: [
        { id: 1, name: "Sheet 1", node_count: 0 },
        {
          id: 2,
          name: "PCA",
          node_count: 3,
          primary_data_source_name: "Wine (bundled example)",
          data_origin: "example",
        },
      ],
    });
    const store = useReportStore();

    await store.fetchWorkflows();

    expect(mocks.apiGet).toHaveBeenCalledWith("/workflows", {
      params: { project_id: 17, in_workbook: true, limit: 200 },
    });
    expect(store.workflows).toEqual([
      expect.objectContaining({
        id: 2,
        display_label: "PCA — Wine (bundled example) · Example data · Sheet #2",
      }),
    ]);
  });
  it("cancels an Advisor narrative when its source report is reset", async () => {
    const store = useReportStore();
    store.reportData = makeReportData();
    const pending = store.generateNarrative();
    await Promise.resolve();
    const sent = JSON.parse(mocks.sentMessages[0]);
    store.resetProjectScope();
    dispatchSherpaEvent({ type: SHERPA_WS_EVENT.reportResult,
      request_id: sent.payload.request_id, report: 'Old interpretation', memory_scopes: ['old-project'] });
    await pending;
    expect(store.narrativeText).toBeNull();
    expect(store.narrativeMemoryScopes).toEqual([]);
    expect(store.narrativeError).toBeNull();
    expect(store.narrativeLoading).toBe(false);
  });
  it("ignores a previous run selection that finishes after the current selection", async () => {
    let resolveOld!: (value: unknown) => void;
    mocks.apiGet.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const store = useReportStore();
    store.selectedWorkflowId = 7;
    store.selectedRunIds = [41];
    const oldRequest = store.fetchReportData();
    store.selectedRunIds = [42];
    mocks.apiGet.mockResolvedValueOnce({ data: makeReportData() });
    await store.fetchReportData();
    resolveOld({ data: { ...makeReportData(), name: 'Stale run' } });
    await oldRequest;
    expect(store.reportData?.name).toBe('MCR and Library Benchmark');
    expect(store.loading).toBe(false);
  });

  it("does not restore report evidence after a project reset", async () => {
    let resolve!: (value: unknown) => void;
    mocks.apiGet.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const store = useReportStore();
    store.selectedWorkflowId = 7;
    const pending = store.fetchReportData();
    store.resetProjectScope();
    resolve({ data: makeReportData() });
    await pending;
    expect(store.reportData).toBeNull();
    expect(store.loading).toBe(false);
  });
  it("maps the backend ranking authority into generated report data", async () => {
    const response = makeReportData();
    response.comparison = {
      metric_keys: ["qualified_cv.rmse"],
      diff: { "qualified_cv.rmse": { "41": 0.5, "42": 0.4 } },
      rankable_metric_keys: ["qualified_cv.rmse"],
    };
    mocks.apiGet.mockResolvedValueOnce({ data: response });
    const store = useReportStore();
    store.selectedWorkflowId = 7;
    store.selectedRunIds = [41, 42];

    await store.fetchReportData();

    expect(store.reportData?.comparison?.rankable_metrics).toEqual(["qualified_cv.rmse"]);
  });
  it("keeps diagnostics and workflow evidence for AI report generation", () => {
    const reportData = makeReportData();

    const payload = buildReportExperimentPayload(reportData);
    const runs = payload.runs as Array<Record<string, unknown>>;

    expect(payload).toMatchObject({
      workflow_name: "MCR and Library Benchmark",
      technique: "FTIR",
      node_count: 1,
    });
    expect(runs[0]).toMatchObject({
      id: 42,
      status: "completed",
      diagnostics: reportData.runs?.[0].diagnostics,
      params_snapshot: reportData.runs?.[0].params_snapshot,
      node_statuses: reportData.runs?.[0].node_statuses,
      integrity_hash: "run-hash",
      labels: ["release-smoke"],
    });
    expect(payload.comparison).toEqual(reportData.comparison);
  });

  it("surfaces generic Sherpa preamble errors during AI report generation", async () => {
    const reportStore = useReportStore();
    reportStore.reportData = makeReportData();

    const promise = reportStore.generateNarrative();
    await Promise.resolve();

    const sent = JSON.parse(mocks.sentMessages[0]);
    expect(sent.action).toBe(SHERPA_WS_ACTION.writeReport);

    dispatchSherpaEvent({
      type: SHERPA_WS_EVENT.error,
      request_id: sent.payload.request_id,
      detail: "Sherpa AI features are disabled in user privacy settings.",
    });
    await promise;

    expect(reportStore.narrativeText).toBeNull();
    expect(reportStore.narrativeError).toBe(
      "Sherpa AI features are disabled in user privacy settings."
    );
  });

  it("surfaces report not-configured status instead of timing out", async () => {
    const reportStore = useReportStore();
    reportStore.reportData = makeReportData();

    const promise = reportStore.generateNarrative();
    await Promise.resolve();

    const sent = JSON.parse(mocks.sentMessages[0]);
    dispatchSherpaEvent({
      type: SHERPA_WS_EVENT.status,
      request_id: sent.payload.request_id,
      payload: { connected: false, reason: "not_configured" },
    });
    await promise;

    expect(reportStore.narrativeError).toBe(
      "Sherpa Advisor is unavailable (not_configured)."
    );
  });
});


describe("row-level report export consent", () => {
  it("defaults to summaries and requires a fresh opt-in per workflow", async () => {
    const store = useReportStore();
    store.selectedWorkflowId = 7;
    mocks.apiGet.mockResolvedValue({ data: makeReportData() });
    await store.fetchReportData();
    expect(mocks.apiGet).toHaveBeenLastCalledWith(
      "/workflows/7/export/report-data", { params: { include_row_level_plots: "false" } });
    store.includeRowLevelPlots = true;
    expect(store.reportData).toBeNull();
    await store.fetchReportData();
    expect(mocks.apiGet).toHaveBeenLastCalledWith(
      "/workflows/7/export/report-data", { params: { include_row_level_plots: "true" } });
    store.selectedWorkflowId = 8;
    expect(store.includeRowLevelPlots).toBe(false);
    expect(store.reportData).toBeNull();
  });

  it("discards an in-flight row-level response when consent is removed", async () => {
    const store = useReportStore();
    store.selectedWorkflowId = 7;
    store.includeRowLevelPlots = true;
    let resolve!: (value: { data: ExtendedReportData }) => void;
    mocks.apiGet.mockReturnValue(new Promise((done) => { resolve = done; }));
    const pending = store.fetchReportData();
    store.includeRowLevelPlots = false;
    resolve({ data: makeReportData() });
    await pending;
    expect(store.reportData).toBeNull();
    expect(store.loading).toBe(false);
    store.includeRowLevelPlots = true;
    store.reset();
    expect(store.includeRowLevelPlots).toBe(false);
  });

  it("does not treat export opt-in as consent to send row values to AI", () => {
    const data = makeReportData();
    data.runs[0].validation_summary = {
      schema_version: "test", run_id: 42, rows: [], figures: [],
    };
    // A sentinel represents a row-bearing figure without coupling to its schema.
    const figures = [{ private_rows: [1, 2, 3] }] as unknown as NonNullable<
      NonNullable<typeof data.runs[0]["validation_summary"]>["figures"]>;
    data.runs[0].validation_summary.figures = figures;
    data.runs[0].node_plots = [{ node_id: "source", label: "Private spectra", node_type: "data.file_load",
      notices: [], plots: [{ title: "Private graph", image: "data:image/png;base64,private" }] }];
    data.runs[0].validation_summary.rows = [{ label: "Observation 1 — calibration", value: "private reference" }];
    data.runs[0].validation_summary.regression_results = [{
      node_id: "fit", source_port: "comparison", target: "y", units: "mg/L", role: "calibration",
      reference_min: 1, reference_max: 1, reference_sd: null, metrics: { n_samples: 1 },
      bias_definition: "predicted_minus_reference",
      observations: [{ sample: "private-sample", reference: 1, predicted: 2 }],
    }];
    const payload = buildReportExperimentPayload(data);
    expect(payload.runs[0]).not.toHaveProperty("node_plots");
    expect(payload.runs[0].validation_summary?.figures).toEqual([]);
    expect(payload.runs[0].validation_summary?.rows).toEqual([]);
    expect(payload.runs[0].validation_summary?.regression_results?.[0].observations).toBeUndefined();
    expect(data.runs[0].validation_summary.regression_results[0].observations).toHaveLength(1);
    expect(data.runs[0].validation_summary.figures).toEqual(figures);
  });
});


describe("generated report authority", () => {
  it("retains generated identity, mode and time while Setup changes", async () => {
    const store = useReportStore();
    store.selectedWorkflowId = 7;
    store.selectedRunIds = [42];
    mocks.apiGet.mockResolvedValueOnce({ data: makeReportData() });
    await store.fetchReportData();
    const generated = JSON.parse(JSON.stringify(store.generatedSelection));
    expect(generated).toEqual({ workflowId: 7, runIds: [42], includeRowLevelPlots: false,
      reportMode: "summary", generatedAt: expect.any(String) });
    expect(store.isStale).toBe(false);
    store.selectedRunIds = [43, 44];
    store.reportMode = "detailed";
    expect(store.isStale).toBe(true);
    expect(store.generatedSelection).toEqual(generated);
    expect(store.reportData?.runs?.map(run => run.id)).toEqual([42]);
    expect(store.hasRuns).toBe(true);
    expect(store.hasComparison).toBe(false);
    store.selectedRunIds = [42];
    store.reportMode = "summary";
    expect(store.isStale).toBe(false);
  });
  it("does not repopulate selector options after project reset", async () => {
    let resolveWorkflows!: (value: unknown) => void;
    let resolveRuns!: (value: unknown) => void;
    mocks.apiGet.mockImplementationOnce(() => new Promise(resolve => { resolveWorkflows = resolve; }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveRuns = resolve; }));
    const store = useReportStore();
    store.selectedWorkflowId = 7;
    const workflows = store.fetchWorkflows();
    const runs = store.fetchRunsForWorkflow(7);
    store.resetProjectScope();
    resolveWorkflows({ data: [{ id: 7, name: "Old", node_count: 2 }] });
    resolveRuns({ data: { runs: [{ id: 42, name: "Old" }] } });
    await Promise.all([workflows, runs]);
    expect(store.workflows).toEqual([]);
    expect(store.availableRuns).toEqual([]);
    expect(store.generatedSelection).toBeNull();
  });
  it("exposes selector failures and clears them on successful retry", async () => {
    mocks.apiGet.mockRejectedValueOnce(new Error("offline"))
      .mockRejectedValueOnce(new Error("offline"));
    const store = useReportStore();
    store.selectedWorkflowId = 7;
    await store.fetchWorkflows();
    await store.fetchRunsForWorkflow(7);
    expect(store.workflowsError).toBe("Workflows could not be loaded.");
    expect(store.runsError).toBe("Runs could not be loaded.");
    mocks.apiGet.mockResolvedValueOnce({ data: [] }).mockResolvedValueOnce({ data: { runs: [] } });
    await store.fetchWorkflows();
    await store.fetchRunsForWorkflow(7);
    expect(store.workflowsError).toBe("");
    expect(store.runsError).toBe("");
  });
});
