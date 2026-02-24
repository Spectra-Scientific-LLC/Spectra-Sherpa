import { defineStore } from "pinia";
import { ref, computed } from "vue";
import api from "@/api/client";
import type {
  ExecutionRunSummary,
  ExecutionRunDetail,
  ComparisonResult,
  BatchPredictRequest,
  BatchPredictResponse,
  BatchPredictionResult,
} from "@/types";

interface SaveRunPayload {
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
  model_ids?: string[];
}

export const useRunsStore = defineStore("runs", () => {
  // State
  const runs = ref<ExecutionRunSummary[]>([]);
  const runsLoading = ref(false);
  const selectedRunIds = ref<Set<number>>(new Set());
  const comparison = ref<ComparisonResult | null>(null);
  const comparisonLoading = ref(false);

  // Computed
  const selectedRuns = computed(() =>
    runs.value.filter((r) => selectedRunIds.value.has(r.id))
  );

  const selectedCount = computed(() => selectedRunIds.value.size);

  // Actions
  async function fetchRuns(workflowId: number): Promise<void> {
    runsLoading.value = true;
    try {
      const response = await api.get<{ runs: ExecutionRunSummary[]; total: number }>(
        `/workflows/${workflowId}/runs`
      );
      runs.value = response.data.runs;
    } catch (error) {
      console.error("Failed to fetch runs:", error);
      runs.value = [];
    } finally {
      runsLoading.value = false;
    }
  }

  async function saveRun(
    workflowId: number,
    payload: SaveRunPayload
  ): Promise<ExecutionRunSummary> {
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
    selectedRunIds.value = new Set();
    comparison.value = null;
  }

  async function startBatchRun(
    workflowId: number,
    request: BatchPredictRequest
  ): Promise<BatchPredictResponse> {
    const response = await api.post<BatchPredictResponse>(
      `/deploy/workflows/${workflowId}/predict/batch`,
      request
    );
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
    // State
    runs,
    runsLoading,
    selectedRunIds,
    comparison,
    comparisonLoading,

    // Computed
    selectedRuns,
    selectedCount,

    // Actions
    fetchRuns,
    saveRun,
    deleteRun,
    compareRuns,
    toggleRunSelection,
    clearSelection,
    startBatchRun,
    fetchPredictions,
    updateLabels,
  };
});
