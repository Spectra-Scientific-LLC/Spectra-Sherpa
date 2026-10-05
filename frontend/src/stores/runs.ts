import { defineStore } from "pinia";
import { ref, computed } from "vue";
import api from "@/api/client";
import { registerProjectScopeReset } from "@/stores/projectScopeRegistry";
import type {
  ExecutionRunSummary,
  RunListItem,
  ComparisonResult,
  BatchPredictionResult,
} from "@/types";

interface SaveRunPayload {
  run_id?: number | null;
  name: string;
  notes?: string;
  status: string;
  results_summary: Record<string, Record<string, unknown>>;
  diagnostics?: Record<string, Record<string, unknown>>;
  node_statuses?: Record<string, string>;
  error?: string;
  integrity_hash?: string;
  executed_at: string;
  labels?: string[];
  produced_artifact_uids?: string[];
  run_kind?: string;
  attempted_artifact_uids?: string[];
  succeeded_artifact_uids?: string[];
}

export type RunSortField = "name" | "status" | "run_kind" | "executed_at";
export type RunSortOrder = "asc" | "desc";

export const useRunsStore = defineStore("runs", () => {
  // State
  const runs = ref<RunListItem[]>([]);
  const runsLoading = ref(false);
  const total = ref(0);
  const loadError = ref<string | null>(null);
  let listRequest = 0;
  let comparisonRequest = 0;
  const selectedRunIds = ref<Set<number>>(new Set());
  const comparison = ref<ComparisonResult | null>(null);
  const comparisonLoading = ref(false);

  function resetProjectScope(): void {
    ++listRequest;
    ++comparisonRequest;
    total.value = 0;
    loadError.value = null;
    runs.value = [];
    runsLoading.value = false;
    selectedRunIds.value = new Set();
    comparison.value = null;
    comparisonLoading.value = false;
  }
  registerProjectScopeReset(resetProjectScope);

  // Computed
  const selectedRuns = computed(() =>
    runs.value.filter((r) => selectedRunIds.value.has(r.id))
  );

  const selectedCount = computed(() => selectedRunIds.value.size);

  // Actions
  async function fetchRuns(workflowId: number): Promise<void> {
    const request = ++listRequest;
    runsLoading.value = true;
    try {
      const response = await api.get<{ runs: ExecutionRunSummary[]; total: number }>(
        `/workflows/${workflowId}/runs`
      );
      if (request !== listRequest) return;
      runs.value = response.data.runs;
      total.value = response.data.total;
    } catch (error) {
      console.error("Failed to fetch runs:", error);
      if (request === listRequest) runs.value = [];
    } finally {
      if (request === listRequest) runsLoading.value = false;
    }
  }

  async function fetchProjectRuns(
    projectId: number,
    offset = 0,
    kind?: string,
    artifactUid?: string,
    sortBy: RunSortField = "executed_at",
    sortOrder: RunSortOrder = "desc",
  ): Promise<void> {
    const request = ++listRequest;
    clearSelection();
    runsLoading.value = true;
    loadError.value = null;
    try {
      const response = await api.get<{ runs: RunListItem[]; total: number }>(
        "/runs",
        {
          params: {
            project_id: projectId,
            limit: 50,
            offset,
            kind: kind === "all" ? undefined : kind,
            artifact_uid: artifactUid,
            sort_by: sortBy,
            sort_order: sortOrder,
          },
        }
      );
      if (request !== listRequest) return;
      runs.value = response.data.runs;
      total.value = response.data.total;
    } catch (error) {
      if (request !== listRequest) return;
      console.error("Failed to fetch project runs:", error);
      runs.value = [];
      total.value = 0;
      loadError.value = "Could not load run history. Retry to refresh.";
    } finally {
      if (request === listRequest) runsLoading.value = false;
    }
  }

  async function saveRun(
    workflowId: number,
    payload: SaveRunPayload
  ): Promise<ExecutionRunSummary> {
    if (!Number.isInteger(payload.run_id) || Number(payload.run_id) <= 0)
      throw new Error("The displayed run identity is required to save a run.");
    const response = await api.post<ExecutionRunSummary>(
      `/workflows/${workflowId}/runs`,
      payload
    );
    // Prepend to list (newest first)
    runs.value = [response.data, ...runs.value];
    return response.data;
  }

  async function deleteRun(workflowId: number, runId: number): Promise<void> {
    await api.delete(`/workflows/${workflowId}/runs/${runId}`);
    runs.value = runs.value.filter((r) => r.id !== runId);
    const next = new Set(selectedRunIds.value);
    next.delete(runId);
    selectedRunIds.value = next;
  }

  async function deleteProjectRun(projectId: number, runId: number): Promise<void> {
    await api.delete(`/runs/${runId}`, { params: { project_id: projectId } });
    runs.value = runs.value.filter((r) => r.id !== runId);
    const next = new Set(selectedRunIds.value);
    next.delete(runId);
    selectedRunIds.value = next;
  }

  async function compareRuns(
    workflowId: number,
    runIds: number[]
  ): Promise<ComparisonResult> {
    comparisonLoading.value = true;
    try {
      const response = await api.post<ComparisonResult>(
        `/workflows/${workflowId}/runs/compare`,
        { run_ids: runIds }
      );
      comparison.value = response.data;
      return response.data;
    } finally {
      comparisonLoading.value = false;
    }
  }

  async function compareProjectRuns(
    projectId: number,
    runIds: number[],
    evaluationSelections: import('@/types').EvaluationSelections = {},
  ): Promise<ComparisonResult> {
    const request = ++comparisonRequest;
    comparisonLoading.value = true;
    comparison.value = null;
    try {
      const response = await api.post<ComparisonResult>(
        "/runs/compare",
        { run_ids: runIds, evaluation_selections: evaluationSelections },
        { params: { project_id: projectId } }
      );
      if (request === comparisonRequest) comparison.value = response.data;
      return response.data;
    } finally {
      if (request === comparisonRequest) comparisonLoading.value = false;
    }
  }

  function toggleRunSelection(runId: number): void {
    const next = new Set(selectedRunIds.value);
    if (next.has(runId)) {
      next.delete(runId);
    } else {
      next.add(runId);
    }
    selectedRunIds.value = next;
  }

  function clearSelection(): void {
    ++comparisonRequest;
    comparisonLoading.value = false;
    selectedRunIds.value = new Set();
    comparison.value = null;
  }

  async function reclaimStorage(): Promise<{
    removed_files: number;
    used_bytes: number;
    quota_bytes: number;
    grace_seconds: number;
  }> {
    const response = await api.post("/runs/storage/reclaim");
    return response.data;
  }

  async function fetchPredictions(
    runId: number
  ): Promise<BatchPredictionResult[]> {
    const response = await api.get<{
      predictions: BatchPredictionResult[];
      total: number;
    }>(`/deploy/runs/${runId}/predictions`);
    return response.data.predictions;
  }

  async function updateLabels(
    runId: number,
    labels: string[]
  ): Promise<ExecutionRunSummary> {
    const response = await api.patch<ExecutionRunSummary>(
      `/deploy/runs/${runId}/labels`,
      { labels }
    );
    // Update in local list
    const idx = runs.value.findIndex((r) => r.id === runId);
    if (idx !== -1) {
      runs.value[idx] = { ...runs.value[idx], labels };
    }
    return response.data;
  }

  return {
    reclaimStorage,
    // State
    runs,
    runsLoading,
    total,
    loadError,
    selectedRunIds,
    comparison,
    comparisonLoading,

    // Computed
    selectedRuns,
    selectedCount,

    // Actions
    fetchRuns,
    fetchProjectRuns,
    saveRun,
    deleteRun,
    deleteProjectRun,
    compareRuns,
    compareProjectRuns,
    toggleRunSelection,
    clearSelection,
    fetchPredictions,
    updateLabels,
    resetProjectScope,
  };
});
