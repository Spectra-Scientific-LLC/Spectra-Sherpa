import { defineStore } from "pinia";
import { ref } from "vue";
import api from "@/api/client";
import { registerProjectScopeReset } from "@/stores/projectScopeRegistry";
import type {
  FolderWatch,
  ExecutionRunSummary,
} from "@/types";

interface CreateWatchPayload {
  workflow_id: number;
  name: string;
  folder_path: string;
  file_pattern?: string;
  poll_interval_sec?: number;
}

interface UpdateWatchPayload {
  name?: string;
  folder_path?: string;
  file_pattern?: string;
  poll_interval_sec?: number;
  is_enabled?: boolean;
}

export const useDeployStore = defineStore("deploy", () => {
  const watches = ref<FolderWatch[]>([]);
  const deployRuns = ref<ExecutionRunSummary[]>([]);
  const loading = ref(false);
  const runsLoading = ref(false);

  function resetProjectScope(): void {
    watches.value = [];
    deployRuns.value = [];
    loading.value = false;
    runsLoading.value = false;
  }
  registerProjectScopeReset(resetProjectScope);

  async function fetchWatches(): Promise<void> {
    loading.value = true;
    try {
      const response = await api.get<FolderWatch[]>("/deploy/watches");
      watches.value = response.data;
    } catch (error) {
      console.error("Failed to fetch watches:", error);
      watches.value = [];
    } finally {
      loading.value = false;
    }
  }

  async function createWatch(payload: CreateWatchPayload): Promise<FolderWatch> {
    const response = await api.post<FolderWatch>("/deploy/watches", payload);
    watches.value = [response.data, ...watches.value];
    return response.data;
  }

  async function updateWatch(
    watchId: number,
    payload: UpdateWatchPayload
  ): Promise<FolderWatch> {
    const response = await api.patch<FolderWatch>(
      `/deploy/watches/${watchId}`,
      payload
    );
    const idx = watches.value.findIndex((w) => w.id === watchId);
    if (idx !== -1) {
      watches.value[idx] = response.data;
    }
    return response.data;
  }

  async function deleteWatch(watchId: number): Promise<void> {
    await api.delete(`/deploy/watches/${watchId}`);
    watches.value = watches.value.filter((w) => w.id !== watchId);
  }

  async function toggleWatch(watchId: number, enable: boolean): Promise<FolderWatch> {
    const endpoint = enable ? "enable" : "disable";
    const response = await api.post<FolderWatch>(
      `/deploy/watches/${watchId}/${endpoint}`
    );
    const idx = watches.value.findIndex((w) => w.id === watchId);
    if (idx !== -1) {
      watches.value[idx] = response.data;
    }
    return response.data;
  }

  async function fetchDeployRuns(
    sourceType?: string,
    label?: string
  ): Promise<void> {
    runsLoading.value = true;
    try {
      const params: Record<string, string> = {};
      if (sourceType) params.source_type = sourceType;
      if (label) params.label = label;
      const response = await api.get<{
        runs: ExecutionRunSummary[];
        total: number;
      }>("/deploy/runs", { params });
      deployRuns.value = response.data.runs;
    } catch (error) {
      console.error("Failed to fetch deploy runs:", error);
      deployRuns.value = [];
    } finally {
      runsLoading.value = false;
    }
  }

  return {
    watches,
    deployRuns,
    loading,
    runsLoading,
    fetchWatches,
    createWatch,
    updateWatch,
    deleteWatch,
    toggleWatch,
    fetchDeployRuns,
    resetProjectScope,
  };
});
