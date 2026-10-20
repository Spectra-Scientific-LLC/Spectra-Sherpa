import { defineStore } from "pinia";
import { ref, computed, watch } from "vue";
import api from "@/api/client";
import type { components } from "@/types/api/v1";
import { runListItem, runSummary, batchPrediction } from "@/api/adapters/runs";
import { activeProjectScope, registerProjectScopeReset } from "@/stores/projectScopeRegistry";
import { useAuthStore } from "@/stores/auth";
import { useScopedRequest, type ScopedRequestTicket } from "@/composables/useScopedRequest";
import type {
  ExecutionRunSummary,
  RunListItem,
  ComparisonResult,
  BatchPredictionResult,
} from "@/types";

type SaveRunPayload = components["schemas"]["SaveRunRequest"];

export type RunSortField = "name" | "status" | "run_kind" | "executed_at";
export type RunSortOrder = "asc" | "desc";

export const useRunsStore = defineStore("runs", () => {
  // State
  const runs = ref<RunListItem[]>([]);
  const runsLoading = ref(false);
  const total = ref(0);
  const loadError = ref<string | null>(null);
  const listOwner = ref("");
  const selectedRunIds = ref<Set<number>>(new Set());
  const comparison = ref<ComparisonResult | null>(null);
  const comparisonLoading = ref(false);
  const identity = () => [useAuthStore().user?.id, useAuthStore().token, activeProjectScope.value, listOwner.value];
  const listScope = useScopedRequest(identity, () => { runsLoading.value = false; });
  const comparisonScope = useScopedRequest(
    () => [...identity(), ...selectedRunIds.value],
    () => { comparisonLoading.value = false; comparison.value = null; },
  );
  const mutationScope = useScopedRequest(identity);
  // Independent writes may complete concurrently. They share a scope lease,
  // not a latest-read lane; a navigation invalidates all their UI effects.
  let mutationTicket: ScopedRequestTicket | undefined;
  function captureMutationScope(): ScopedRequestTicket {
    if (!mutationTicket?.isCurrent()) mutationTicket = mutationScope.begin();
    return mutationTicket;
  }

  function resetProjectScope(): void {
    listScope.invalidate();
    comparisonScope.invalidate();
    mutationScope.invalidate();
    listOwner.value = "";
    total.value = 0;
    loadError.value = null;
    runs.value = [];
    runsLoading.value = false;
    selectedRunIds.value = new Set();
    comparison.value = null;
    comparisonLoading.value = false;
  }
  registerProjectScopeReset(resetProjectScope);
  watch([() => useAuthStore().user?.id, () => useAuthStore().token, () => activeProjectScope.value], resetProjectScope, { flush: "sync" });

  // Computed
  const selectedRuns = computed(() =>
    runs.value.filter((r) => selectedRunIds.value.has(r.id))
  );

  const selectedCount = computed(() => selectedRunIds.value.size);

  // Actions
  async function fetchRuns(workflowId: number): Promise<void> {
    listOwner.value = `workflow:${workflowId}`;
    const request = listScope.begin();
    runsLoading.value = true;
    try {
      const response = await api.get<components["schemas"]["ExecutionRunList"]>(
        `/workflows/${workflowId}/runs`, { signal: request.signal }
      );
      if (!request.isCurrent()) return;
      runs.value = response.data.runs.map(runSummary);
      total.value = response.data.total;
    } catch (error) {
      if (request.isCurrent()) {
        console.error("Failed to fetch runs:", error);
        runs.value = [];
      }
    } finally {
      if (request.isCurrent()) runsLoading.value = false;
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
    listOwner.value = `project:${projectId}`;
    const request = listScope.begin();
    clearSelection();
    runsLoading.value = true;
    loadError.value = null;
    try {
      const response = await api.get<components["schemas"]["RunPage"]>(
        "/runs",
        {
          signal: request.signal,
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
      if (!request.isCurrent()) return;
      runs.value = response.data.runs.map(runListItem);
      total.value = response.data.total;
    } catch (error) {
      if (!request.isCurrent()) return;
      console.error("Failed to fetch project runs:", error);
      runs.value = [];
      total.value = 0;
      loadError.value = "Could not load run history. Retry to refresh.";
    } finally {
      if (request.isCurrent()) runsLoading.value = false;
    }
  }

  async function saveRun(
    workflowId: number,
    payload: SaveRunPayload
  ): Promise<ExecutionRunSummary> {
    if (!Number.isInteger(payload.run_id) || Number(payload.run_id) <= 0)
      throw new Error("The displayed run identity is required to save a run.");
    const request = captureMutationScope();
    const response = await api.post<components["schemas"]["ExecutionRunOut"]>(
      `/workflows/${workflowId}/runs`,
      payload
    );
    // Prepend to list (newest first)
    const run = runSummary(response.data);
    if (request.isCurrent()) runs.value = [run, ...runs.value];
    return run;
  }

  async function deleteRun(workflowId: number, runId: number): Promise<void> {
    const request = captureMutationScope();
    await api.delete(`/workflows/${workflowId}/runs/${runId}`);
    if (!request.isCurrent()) return;
    runs.value = runs.value.filter((r) => r.id !== runId);
    const next = new Set(selectedRunIds.value);
    next.delete(runId);
    selectedRunIds.value = next;
  }

  async function deleteProjectRun(projectId: number, runId: number): Promise<void> {
    const request = captureMutationScope();
    await api.delete(`/runs/${runId}`, { params: { project_id: projectId } });
    if (!request.isCurrent()) return;
    runs.value = runs.value.filter((r) => r.id !== runId);
    const next = new Set(selectedRunIds.value);
    next.delete(runId);
    selectedRunIds.value = next;
  }

  async function compareRuns(
    workflowId: number,
    runIds: number[]
  ): Promise<ComparisonResult> {
    const request = comparisonScope.begin();
    comparisonLoading.value = true;
    try {
      const response = await api.post<ComparisonResult>(
        `/workflows/${workflowId}/runs/compare`,
        { run_ids: runIds }, { signal: request.signal }
      );
      if (request.isCurrent()) comparison.value = response.data;
      return response.data;
    } finally {
      if (request.isCurrent()) comparisonLoading.value = false;
    }
  }

  async function compareProjectRuns(
    projectId: number,
    runIds: number[],
    evaluationSelections: import('@/types').EvaluationSelections = {},
  ): Promise<ComparisonResult> {
    const request = comparisonScope.begin();
    comparisonLoading.value = true;
    comparison.value = null;
    try {
      const response = await api.post<ComparisonResult>(
        "/runs/compare",
        { run_ids: runIds, evaluation_selections: evaluationSelections },
        { params: { project_id: projectId }, signal: request.signal }
      );
      if (request.isCurrent()) comparison.value = response.data;
      return response.data;
    } finally {
      if (request.isCurrent()) comparisonLoading.value = false;
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
    comparisonScope.invalidate();
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
    const response = await api.get<components["schemas"]["BatchPredictionList"]>(
      `/deploy/runs/${runId}/predictions`,
    );
    return response.data.predictions.map(batchPrediction);
  }

  async function updateLabels(
    runId: number,
    labels: string[]
  ): Promise<ExecutionRunSummary> {
    const request = captureMutationScope();
    const response = await api.patch<components["schemas"]["ExecutionRunOut"]>(
      `/deploy/runs/${runId}/labels`,
      { labels }
    );
    // Update in local list
    const idx = runs.value.findIndex((r) => r.id === runId);
    if (request.isCurrent() && idx !== -1) {
      runs.value[idx] = { ...runs.value[idx], labels };
    }
    return runSummary(response.data);
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
