/* eslint-disable @typescript-eslint/no-explicit-any -- report assembly combines workflow output payloads with partially typed backend responses. */
import { defineStore } from "pinia";
import { ref, reactive, computed } from "vue";
import api from "@/api/client";
import { createSherpaRequestId, subscribeSherpaEvents } from "@/lib/sherpaEvents";
import { SHERPA_WS_ACTION, SHERPA_WS_EVENT } from "@/lib/sherpaWs";
import { useAppConfig } from "@/composables/useAppConfig";
import { useLlmStore } from "@/stores/llm";
import { useAdvisorStore } from "@/stores/advisor";
import { useProjectStore } from "@/stores/project";
import type { ExecutionRunSummary } from "@/types";

interface WorkflowOption {
  id: number;
  name: string;
}

interface RunOption {
  id: number;
  name: string;
  status: string;
  executed_at: string;
}

export interface RunReportData {
  id: number;
  name: string;
  status: string;
  executed_at: string | null;
  results_summary: Record<string, Record<string, unknown>>;
  diagnostics: Record<string, Record<string, unknown>> | null;
  params_snapshot: Record<string, Record<string, unknown>>;
  node_statuses: Record<string, string> | null;
  integrity_hash: string | null;
  labels: string[] | null;
}

export interface ReportNodeData {
  node_id: string;
  node_type: string;
  label: string;
  parameters: Record<string, unknown>;
  position_x: number;
  position_y: number;
}

export interface ReportEdgeData {
  from_node_id: string;
  to_node_id: string;
  from_output: string;
  to_input: string;
}

export interface ComparisonData {
  metric_keys: string[];
  diff: Record<string, Record<string, unknown>>;
}

export interface ExtendedReportData {
  workflow_id: number;
  name: string;
  description: string | null;
  technique: string | null;
  sample_type: string | null;
  integrity_hash: string | null;
  created_at: string | null;
  updated_at: string | null;
  nodes: ReportNodeData[];
  edges: ReportEdgeData[];
  runs?: RunReportData[];
  comparison?: ComparisonData | null;
}

export interface ReportSections {
  pipelineDetails: boolean;
  connections: boolean;
  executionResults: boolean;
  diagnostics: boolean;
  runComparison: boolean;
  aiNarrative: boolean;
}

export const useReportStore = defineStore("report", () => {
  // Source selection
  const selectedWorkflowId = ref<number | null>(null);
  const selectedRunIds = ref<number[]>([]);

  // Section toggles
  const sections = reactive<ReportSections>({
    pipelineDetails: true,
    connections: true,
    executionResults: true,
    diagnostics: false,
    runComparison: false,
    aiNarrative: false,
  });

  // Data
  const reportData = ref<ExtendedReportData | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const narrativeText = ref<string | null>(null);
  const narrativeMemoryScopes = ref<string[]>([]);
  const narrativeLoading = ref(false);

  // Options for selectors
  const workflows = ref<WorkflowOption[]>([]);
  const workflowsLoading = ref(false);
  const availableRuns = ref<RunOption[]>([]);
  const runsLoading = ref(false);

  // Computed
  const hasRuns = computed(() => selectedRunIds.value.length > 0);
  const hasComparison = computed(() => selectedRunIds.value.length >= 2);
  const isReady = computed(() => reportData.value !== null);

  async function fetchWorkflows(): Promise<void> {
    workflowsLoading.value = true;
    try {
      const response = await api.get<WorkflowOption[]>("/workflows");
      workflows.value = response.data;
    } catch {
      workflows.value = [];
    } finally {
      workflowsLoading.value = false;
    }
  }

  async function fetchRunsForWorkflow(workflowId: number): Promise<void> {
    runsLoading.value = true;
    try {
      const response = await api.get<{
        runs: ExecutionRunSummary[];
        total: number;
      }>(`/workflows/${workflowId}/runs`);
      availableRuns.value = response.data.runs.map((r) => ({
        id: r.id,
        name: r.name,
        status: r.status,
        executed_at: r.executed_at,
      }));
    } catch {
      availableRuns.value = [];
    } finally {
      runsLoading.value = false;
    }
  }

  async function fetchReportData(): Promise<void> {
    if (!selectedWorkflowId.value) return;
    loading.value = true;
    error.value = null;

    try {
      const params: Record<string, string> = {};
      if (selectedRunIds.value.length > 0) {
        params.run_ids = selectedRunIds.value.join(",");
      }
      const response = await api.get<ExtendedReportData>(
        `/workflows/${selectedWorkflowId.value}/export/report-data`,
        { params }
      );
      reportData.value = response.data;

      // Auto-enable comparison if 2+ runs
      if ((response.data.runs?.length ?? 0) >= 2) {
        sections.runComparison = true;
      }
    } catch (err: any) {
      error.value =
        err?.response?.data?.detail || err?.message || "Failed to load report data";
      reportData.value = null;
    } finally {
      loading.value = false;
    }
  }

  function _buildExperimentPayload(): Record<string, unknown> {
    if (!reportData.value) return {};
    const experiment: Record<string, unknown> = {
      workflow_name: reportData.value.name,
      description: reportData.value.description,
      technique: reportData.value.technique,
      sample_type: reportData.value.sample_type,
      node_count: reportData.value.nodes.length,
      nodes: reportData.value.nodes.map((n) => ({
        type: n.node_type,
        label: n.label,
        parameters: n.parameters,
      })),
    };

    if (reportData.value.runs?.length) {
      experiment.runs = reportData.value.runs.map((r) => ({
        name: r.name,
        status: r.status,
        results_summary: r.results_summary,
      }));
    }

    if (reportData.value.comparison) {
      experiment.comparison = reportData.value.comparison;
    }
    return experiment;
  }

  async function generateNarrative(): Promise<void> {
    if (!reportData.value) return;
    narrativeLoading.value = true;

    try {
      const experiment = _buildExperimentPayload();
      const { isFeatureEnabled } = useAppConfig();

      if (!isFeatureEnabled("sherpaWriteReport")) {
        throw new Error("AI report writing requires a Sherpa subscription.");
      }

      // Use Sherpa cloud proxy via WebSocket
      const llm = useLlmStore();
      await llm.connect();
      const ws = llm.wsRef;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        throw new Error("WebSocket not connected");
      }

      narrativeMemoryScopes.value = [];
      const result = await new Promise<string>((resolve, reject) => {
        const requestId = createSherpaRequestId();
        const timeout = window.setTimeout(() => {
          cleanup();
          reject(new Error("Report generation timed out"));
        }, 60_000);

        const unsubscribe = subscribeSherpaEvents((payload) => {
          if (payload.type === SHERPA_WS_EVENT.reportResult) {
            cleanup();
            narrativeMemoryScopes.value = Array.isArray(payload.memory_scopes)
              ? payload.memory_scopes.map((scope) => String(scope)).filter(Boolean)
              : [];
            resolve(
              typeof payload.report === "string"
                ? payload.report
                : (payload.response ?? "")
            );
          } else if (payload.type === SHERPA_WS_EVENT.reportError) {
            cleanup();
            reject(new Error(payload.detail || "Report generation failed"));
          } else if (payload.type === SHERPA_WS_EVENT.subscriptionRequired) {
            cleanup();
            reject(new Error("Subscription required for AI reports"));
          }
        }, {
          requestId,
          types: [
            SHERPA_WS_EVENT.reportResult,
            SHERPA_WS_EVENT.reportError,
            SHERPA_WS_EVENT.subscriptionRequired,
          ],
        });

        const cleanup = () => {
          clearTimeout(timeout);
          unsubscribe();
        };

        ws.send(JSON.stringify({
          action: SHERPA_WS_ACTION.writeReport,
          payload: {
            request_id: requestId,
            experiment,
            advisor_node_id: useAdvisorStore().activeNodeId,
            project_id: useProjectStore().currentProjectId,
          },
        }));
      });

      narrativeText.value = result;
    } catch (err: any) {
      narrativeText.value = null;
      narrativeMemoryScopes.value = [];
      console.error("Failed to generate narrative:", err);
    } finally {
      narrativeLoading.value = false;
    }
  }

  function reset(): void {
    selectedWorkflowId.value = null;
    selectedRunIds.value = [];
    reportData.value = null;
    error.value = null;
    narrativeText.value = null;
    narrativeMemoryScopes.value = [];
    sections.pipelineDetails = true;
    sections.connections = true;
    sections.executionResults = true;
    sections.diagnostics = false;
    sections.runComparison = false;
    sections.aiNarrative = false;
  }

  return {
    // State
    selectedWorkflowId,
    selectedRunIds,
    sections,
    reportData,
    loading,
    error,
    narrativeText,
    narrativeMemoryScopes,
    narrativeLoading,
    workflows,
    workflowsLoading,
    availableRuns,
    runsLoading,

    // Computed
    hasRuns,
    hasComparison,
    isReady,

    // Actions
    fetchWorkflows,
    fetchRunsForWorkflow,
    fetchReportData,
    generateNarrative,
    reset,
  };
});
