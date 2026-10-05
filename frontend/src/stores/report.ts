import { sherpaResponseTimeoutMs } from "@/lib/sherpaTimeouts";
import type { ValidationFigure } from "@/utils/validationReportPlots";
import type { ReportRegressionResult } from "@/utils/reportGenerator";
import type { ReportNodePlotSection } from "@/utils/reportNodePlots";
/* eslint-disable @typescript-eslint/no-explicit-any -- report assembly combines workflow output payloads with partially typed backend responses. */
import { defineStore } from "pinia";
import { ref, reactive, computed, watch } from "vue";
import api from "@/api/client";
import { createSherpaRequestId, subscribeSherpaEvents } from "@/lib/sherpaEvents";
import { SHERPA_WS_ACTION, SHERPA_WS_EVENT } from "@/lib/sherpaWs";
import { useAppConfig } from "@/composables/useAppConfig";
import { useLlmStore } from "@/stores/llm";
import { useAdvisorStore } from "@/stores/advisor";
import { useProjectStore } from "@/stores/project";
import type { ProjectProvenanceRecord, ProjectProvenanceResponse } from "@/stores/projectProvenance";
import { registerProjectScopeReset } from "@/stores/projectScopeRegistry";
import type { ExecutionRunSummary } from "@/types";
import type { EvidenceGap } from "@/utils/runEvidence";

function formatSherpaReportFailure(payload: Record<string, any>): string {
  const detail =
    typeof payload.detail === "string" && payload.detail.trim()
      ? payload.detail.trim()
      : typeof payload.message === "string" && payload.message.trim()
        ? payload.message.trim()
        : null;
  if (detail) return detail;

  const statusPayload = payload.payload;
  if (
    payload.type === SHERPA_WS_EVENT.status &&
    statusPayload &&
    statusPayload.connected === false
  ) {
    const reason =
      typeof statusPayload.reason === "string" && statusPayload.reason.trim()
        ? statusPayload.reason.trim()
        : "unknown";
    return `Sherpa Advisor is unavailable (${reason}).`;
  }

  return "Report generation failed.";
}

interface WorkflowOption {
  id: number;
  name: string;
  display_label: string;
  project_id?: number | null;
  node_count?: number;
  primary_data_source_name?: string | null;
  data_origin?: "current" | "example" | null;
}

interface RunOption {
  id: number;
  name: string;
  status: string;
  executed_at: string;
}

export interface RunReportData {
  node_plots?: ReportNodePlotSection[];
  validation_summary?: {
    schema_version: string;
    run_id: number;
    rows: { label: string; value: string }[];
    figures?: ValidationFigure[];
    regression_results?: ReportRegressionResult[];
  };
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
  evidence_notice?: string;
  evidence_gaps?: EvidenceGap[];
  workflow_identity?: WorkflowIdentity;
  selection_provenance?: SelectionProvenance;
  saved_definition?: { nodes: ReportNodeData[]; edges: ReportEdgeData[] } | null;
}

export interface SelectionProvenance {
  schema_version: 1;
  state: "exact" | "unavailable";
  reason: string | null;
  executor_user_id: number;
  workflow_version_id: number | null;
  revisions: Array<{
    revision_id: number;
    revision_number: number;
    source_node_id: string;
    created_by: number;
    created_at: string;
    origin: string;
    reason: string | null;
    graph_digest: string;
    selection: {
      dataset_name: string;
      experiment_id: number;
      stage: string;
      selected_file_ids: number[] | null;
      target_authority: {
        column: string;
        target_type: string;
        units: string | null;
        source_digest: string;
      } | null;
      group_column: string | null;
      scientific_collection_sha256: string;
    };
  }>;
  scientific_receipts: Array<{
    node_id: string;
    scientific_digest: string;
    shape: number[];
    title: string | null;
    sample_identity?: {
      count: number;
      labels_sha256: string | null;
    };
    selection_lineage?: Array<{
      node_id: string | null;
      operation: "data.filter_samples";
      parameters: Record<string, unknown>;
      selected_index_ranges: number[][];
      selected_indices_sha256: string;
      input_shape: number[] | null;
      output_shape: number[] | null;
    }>;
  }>;
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
  rankable_metric_keys?: string[];
  rankable_metrics?: string[];
  result_pairs?: { state: string; reason: string }[];
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
  workflow_identity?: WorkflowIdentity;
}

export interface ReportProjectEvidenceSnapshot {
  state: "available" | "unavailable";
  projectId: number | null;
  capturedAt: string;
  records: ProjectProvenanceRecord[];
  reason: string | null;
}

export interface WorkflowIdentity {
  schema_version: 1;
  project_id: number | null;
  workflow_id: number;
  workflow_name: string;
  template_name: string | null;
  template_version: string | null;
  source_name: string | null;
  source_origin: "current" | "example" | null;
  source_node_id: string | null;
}

export interface ReportSections {
  pipelineDetails: boolean;
  connections: boolean;
  executionResults: boolean;
  diagnostics: boolean;
  runComparison: boolean;
  aiNarrative: boolean;
}

export function buildReportExperimentPayload(
  reportData: ExtendedReportData | null,
): Record<string, unknown> {
  if (!reportData) return {};
  const experiment: Record<string, unknown> = {
    workflow_name: reportData.name,
    description: reportData.description,
    technique: reportData.technique,
    sample_type: reportData.sample_type,
    node_count: reportData.nodes.length,
    nodes: reportData.nodes.map((n) => ({
      type: n.node_type,
      label: n.label,
      parameters: n.parameters,
    })),
  };

  if (reportData.runs?.length) {
    experiment.runs = reportData.runs.map((r) => ({
      id: r.id,
      name: r.name,
      status: r.status,
      executed_at: r.executed_at,
      results_summary: r.results_summary,
      diagnostics: r.diagnostics ?? {},
      params_snapshot: r.params_snapshot,
      node_statuses: r.node_statuses ?? {},
      integrity_hash: r.integrity_hash,
      labels: r.labels ?? [],
      evidence_notice: r.evidence_notice,
      evidence_gaps: r.evidence_gaps ?? [],
      workflow_identity: r.workflow_identity,
      selection_provenance: r.selection_provenance,
      saved_definition: r.saved_definition,
      // Export consent does not authorize sending row-level plot data to an AI provider.
      validation_summary: r.validation_summary
        ? {
            ...r.validation_summary,
            figures: [],
            rows: r.validation_summary.rows.filter((row) => !row.label.startsWith("Observation ")),
            regression_results: r.validation_summary.regression_results?.map(
              ({ observations: _observations, ...result }) => result,
            ),
          }
        : undefined,
    }));
  }

  if (reportData.comparison) {
    experiment.comparison = reportData.comparison;
  }
  return experiment;
}

export const useReportStore = defineStore("report", () => {
  // Source selection
  const selectedWorkflowId = ref<number | null>(null);
  const selectedRunIds = ref<number[]>([]);
  const includeRowLevelPlots = ref(false);
  const reportMode = ref<"summary" | "detailed">("summary");

  // Detailed sections retain their defaults. AI is always separately opt-in.
  const sections = reactive<ReportSections>({
    pipelineDetails: true,
    connections: true,
    executionResults: true,
    diagnostics: true,
    runComparison: true,
    aiNarrative: false,
  });

  // Data
  const reportData = ref<ExtendedReportData | null>(null);
  const projectEvidenceSnapshot = ref<ReportProjectEvidenceSnapshot | null>(null);
  const generatedSelection = ref<{
    workflowId: number;
    runIds: number[];
    includeRowLevelPlots: boolean;
    reportMode: "summary" | "detailed";
    generatedAt: string;
  } | null>(null);
  const isStale = computed(
    () =>
      !!reportData.value &&
      !!generatedSelection.value &&
      (generatedSelection.value.workflowId !== selectedWorkflowId.value ||
        generatedSelection.value.runIds.join(",") !== selectedRunIds.value.join(",") ||
        generatedSelection.value.includeRowLevelPlots !== includeRowLevelPlots.value ||
        generatedSelection.value.reportMode !== reportMode.value),
  );
  const loading = ref(false);
  const error = ref<string | null>(null);
  const narrativeText = ref<string | null>(null);
  const narrativeMemoryScopes = ref<string[]>([]);
  const narrativeError = ref<string | null>(null);
  const narrativeLoading = ref(false);

  // Options for selectors
  const workflows = ref<WorkflowOption[]>([]);
  const workflowsLoading = ref(false);
  const availableRuns = ref<RunOption[]>([]);
  const runsLoading = ref(false);
  const workflowsError = ref("");
  const runsError = ref("");
  let workflowsRequest = 0;
  let runsRequest = 0;

  // Computed
  const hasRuns = computed(() => (reportData.value?.runs?.length ?? 0) > 0);
  const hasComparison = computed(() => (reportData.value?.runs?.length ?? 0) >= 2);
  const isReady = computed(() => reportData.value !== null);
  let reportRequest = 0;
  let narrativeRequest = 0;
  let cancelNarrative: (() => void) | undefined;

  function invalidateNarrative(): void {
    ++narrativeRequest;
    cancelNarrative?.();
    cancelNarrative = undefined;
    narrativeText.value = null;
    narrativeMemoryScopes.value = [];
    narrativeError.value = null;
    narrativeLoading.value = false;
  }

  async function fetchWorkflows(): Promise<void> {
    const request = ++workflowsRequest;
    const projectId = useProjectStore().currentProjectId;
    workflowsLoading.value = true;
    workflowsError.value = "";
    try {
      if (projectId == null) {
        workflows.value = [];
        return;
      }
      const response = await api.get<Omit<WorkflowOption, "display_label">[]>("/workflows", {
        params: { project_id: projectId, in_workbook: true, limit: 200 },
      });
      if (request !== workflowsRequest || projectId !== useProjectStore().currentProjectId) return;
      workflows.value = response.data
        .filter((workflow) => (workflow.node_count ?? 0) > 0)
        .map((workflow) => {
          const originLabel =
            workflow.data_origin === "example"
              ? "Example data"
              : workflow.data_origin === "current"
                ? "Current data"
                : "Origin unavailable";
          return {
            ...workflow,
            display_label: `${workflow.name} — ${workflow.primary_data_source_name || "source identity unavailable"} · ${originLabel} · Sheet #${workflow.id}`,
          };
        });
    } catch {
      if (request === workflowsRequest && projectId === useProjectStore().currentProjectId) {
        workflows.value = [];
        workflowsError.value = "Workflows could not be loaded.";
      }
    } finally {
      if (request === workflowsRequest) workflowsLoading.value = false;
    }
  }

  async function fetchRunsForWorkflow(workflowId: number): Promise<void> {
    const request = ++runsRequest;
    const projectId = useProjectStore().currentProjectId;
    const selectedWorkflow = selectedWorkflowId.value;
    const isCurrent = () =>
      request === runsRequest &&
      projectId === useProjectStore().currentProjectId &&
      selectedWorkflow === selectedWorkflowId.value;
    runsLoading.value = true;
    runsError.value = "";
    try {
      const response = await api.get<{
        runs: ExecutionRunSummary[];
        total: number;
      }>(`/workflows/${workflowId}/runs`);
      if (!isCurrent()) return;
      availableRuns.value = response.data.runs.map((r) => ({
        id: r.id,
        name: r.name,
        status: r.status,
        executed_at: r.executed_at,
      }));
    } catch {
      if (isCurrent()) {
        availableRuns.value = [];
        runsError.value = "Runs could not be loaded.";
      }
    } finally {
      if (request === runsRequest) runsLoading.value = false;
    }
  }

  async function fetchReportData(): Promise<void> {
    if (!selectedWorkflowId.value) return;
    invalidateNarrative();
    const request = ++reportRequest;
    const workflowId = selectedWorkflowId.value;
    const projectId = useProjectStore().currentProjectId;
    const optedIntoRows = includeRowLevelPlots.value;
    const selectedRuns = selectedRunIds.value.join(",");
    const selection = {
      workflowId,
      runIds: [...selectedRunIds.value],
      includeRowLevelPlots: optedIntoRows,
      reportMode: reportMode.value,
      generatedAt: new Date().toISOString(),
    };
    const isCurrent = () =>
      request === reportRequest &&
      selectedWorkflowId.value === workflowId &&
      selectedRunIds.value.join(",") === selectedRuns &&
      includeRowLevelPlots.value === optedIntoRows &&
      useProjectStore().currentProjectId === projectId;
    loading.value = true;
    error.value = null;
    reportData.value = null;
    projectEvidenceSnapshot.value = null;
    generatedSelection.value = null;

    try {
      const params: Record<string, string> = { include_row_level_plots: String(optedIntoRows) };
      if (selectedRunIds.value.length > 0) {
        params.run_ids = selectedRunIds.value.join(",");
      }
      const response = await api.get<ExtendedReportData>(
        `/workflows/${selectedWorkflowId.value}/export/report-data`,
        { params },
      );
      if (!isCurrent()) return;
      const data = response.data;
      if (optedIntoRows && data.runs?.length) {
        const { captureReportPlots } = await import("@/utils/captureReportPlots");
        for (const run of data.runs) {
          if (!isCurrent()) return;
          run.node_plots = projectId
            ? await captureReportPlots(run, projectId, isCurrent)
            : [
                {
                  node_id: "run",
                  label: "Saved-run plots",
                  node_type: "",
                  plots: [],
                  notices: ["Select the project that owns this run to load retained plots."],
                },
              ];
        }
      }
      if (!isCurrent()) return;
      if (data.comparison) {
        data.comparison = {
          ...data.comparison,
          rankable_metrics:
            data.comparison.rankable_metric_keys ?? data.comparison.rankable_metrics ?? [],
        };
      }
      let evidence: ReportProjectEvidenceSnapshot = {
        state: "unavailable", projectId, capturedAt: new Date().toISOString(),
        records: [], reason: "Current-project evidence was not available when this report was generated.",
      };
      if (projectId != null && data.workflow_identity?.project_id === projectId) {
        try {
          const current = await api.get<ProjectProvenanceResponse>(`/projects/${projectId}/provenance`);
          evidence = {
            state: "available", projectId, capturedAt: new Date().toISOString(),
            records: current.data.records, reason: null,
          };
        } catch {
          // Report-specific workflow and run evidence remains usable. Do not
          // silently present a stale project beacon snapshot as current.
        }
      } else if (projectId != null) {
        evidence.reason = "The report workflow is not bound to the selected project; no project snapshot was attached.";
      }
      if (!isCurrent()) return;
      reportData.value = data;
      projectEvidenceSnapshot.value = evidence;
      generatedSelection.value = selection;

      // Auto-enable comparison if 2+ runs
      if ((response.data.runs?.length ?? 0) >= 2) {
        sections.runComparison = true;
      }
    } catch (err: any) {
      if (!isCurrent()) return;
      error.value = err?.response?.data?.detail || err?.message || "Failed to load report data";
      reportData.value = null;
      projectEvidenceSnapshot.value = null;
      generatedSelection.value = null;
    } finally {
      if (request === reportRequest) loading.value = false;
    }
  }

  function _buildExperimentPayload(): Record<string, unknown> {
    return buildReportExperimentPayload(reportData.value);
  }

  async function generateNarrative(): Promise<void> {
    if (!reportData.value) return;
    invalidateNarrative();
    const request = narrativeRequest;
    const source = reportData.value;
    const projectId = useProjectStore().currentProjectId;
    const isCurrent = () =>
      request === narrativeRequest &&
      reportData.value === source &&
      useProjectStore().currentProjectId === projectId;
    narrativeLoading.value = true;
    narrativeError.value = null;

    try {
      const experiment = _buildExperimentPayload();
      const { isFeatureEnabled } = useAppConfig();

      if (!isFeatureEnabled("sherpaWriteReport")) {
        throw new Error("AI report writing requires a Sherpa subscription.");
      }

      // Use Sherpa cloud proxy via WebSocket
      const llm = useLlmStore();
      await llm.connect();
      if (!isCurrent()) return;
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
        }, sherpaResponseTimeoutMs());

        const unsubscribe = subscribeSherpaEvents(
          (payload) => {
            if (payload.type === SHERPA_WS_EVENT.reportResult) {
              cleanup();
              if (isCurrent()) {
                narrativeMemoryScopes.value = Array.isArray(payload.memory_scopes)
                  ? payload.memory_scopes.map((scope) => String(scope)).filter(Boolean)
                  : [];
              }
              resolve(
                typeof payload.report === "string" ? payload.report : (payload.response ?? ""),
              );
            } else if (payload.type === SHERPA_WS_EVENT.reportError) {
              cleanup();
              reject(new Error(formatSherpaReportFailure(payload)));
            } else if (payload.type === SHERPA_WS_EVENT.error) {
              cleanup();
              reject(new Error(formatSherpaReportFailure(payload)));
            } else if (payload.type === SHERPA_WS_EVENT.status) {
              const statusPayload = payload.payload;
              if (statusPayload && statusPayload.connected === false) {
                cleanup();
                reject(new Error(formatSherpaReportFailure(payload)));
              }
            } else if (payload.type === SHERPA_WS_EVENT.subscriptionRequired) {
              cleanup();
              reject(new Error(payload.detail || "Subscription required for AI reports"));
            }
          },
          {
            requestId,
            types: [
              SHERPA_WS_EVENT.reportResult,
              SHERPA_WS_EVENT.reportError,
              SHERPA_WS_EVENT.error,
              SHERPA_WS_EVENT.status,
              SHERPA_WS_EVENT.subscriptionRequired,
            ],
          },
        );

        const cleanup = () => {
          clearTimeout(timeout);
          unsubscribe();
          if (request === narrativeRequest) cancelNarrative = undefined;
        };
        cancelNarrative = () => {
          cleanup();
          reject(new Error("Report selection changed"));
        };

        ws.send(
          JSON.stringify({
            action: SHERPA_WS_ACTION.writeReport,
            payload: {
              request_id: requestId,
              experiment,
              advisor_node_id: useAdvisorStore().activeNodeId,
              project_id: projectId,
            },
          }),
        );
      });

      if (isCurrent()) narrativeText.value = result;
    } catch (err: any) {
      if (!isCurrent()) return;
      narrativeText.value = null;
      narrativeMemoryScopes.value = [];
      narrativeError.value =
        err instanceof Error && err.message ? err.message : "Could not generate AI narrative.";
      console.error("Failed to generate narrative:", err);
    } finally {
      if (request === narrativeRequest) narrativeLoading.value = false;
    }
  }

  watch(
    selectedWorkflowId,
    () => {
      includeRowLevelPlots.value = false;
    },
    { flush: "sync" },
  );

  watch(
    includeRowLevelPlots,
    () => {
      ++reportRequest;
      loading.value = false;
      reportData.value = null;
      projectEvidenceSnapshot.value = null;
      generatedSelection.value = null;
      invalidateNarrative();
    },
    { flush: "sync" },
  );

  function reset(): void {
    invalidateNarrative();
    ++reportRequest;
    ++workflowsRequest;
    ++runsRequest;
    workflowsError.value = "";
    runsError.value = "";
    loading.value = false;
    selectedWorkflowId.value = null;
    selectedRunIds.value = [];
    includeRowLevelPlots.value = false;
    reportData.value = null;
    projectEvidenceSnapshot.value = null;
    generatedSelection.value = null;
    error.value = null;
    narrativeText.value = null;
    narrativeMemoryScopes.value = [];
    narrativeError.value = null;
    sections.pipelineDetails = true;
    sections.connections = true;
    sections.executionResults = true;
    sections.diagnostics = true;
    sections.runComparison = true;
    sections.aiNarrative = false;
    reportMode.value = "summary";
  }

  function resetProjectScope(): void {
    reset();
    workflows.value = [];
    workflowsLoading.value = false;
    availableRuns.value = [];
    runsLoading.value = false;
    narrativeLoading.value = false;
    loading.value = false;
  }
  registerProjectScopeReset(resetProjectScope);

  return {
    // State
    selectedWorkflowId,
    selectedRunIds,
    includeRowLevelPlots,
    reportMode,
    sections,
    reportData,
    projectEvidenceSnapshot,
    generatedSelection,
    isStale,
    workflowsError,
    runsError,
    loading,
    error,
    narrativeText,
    narrativeMemoryScopes,
    narrativeError,
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
    resetProjectScope,
  };
});
