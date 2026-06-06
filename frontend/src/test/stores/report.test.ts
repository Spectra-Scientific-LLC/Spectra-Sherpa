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
