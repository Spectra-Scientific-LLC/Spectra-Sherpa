import { defineStore } from "pinia";
import { computed, ref } from "vue";
import api from "@/api/client";
import { registerProjectScopeReset } from "@/stores/projectScopeRegistry";
import type { ProjectDataSource } from "@/types";
import { getErrorMessage } from "@/utils/errors";

export interface ProjectDataSourceCreatePayload {
  display_name: string;
  source_type?: string;
  source_ref?: string | null;
  fingerprint?: string | null;
  color?: string;
  metadata?: Record<string, unknown>;
}

export interface ProjectDataSourceUpdatePayload {
  display_name?: string;
  source_type?: string;
  source_ref?: string | null;
  fingerprint?: string | null;
  color?: string | null;
  metadata?: Record<string, unknown> | null;
}

export const useDataSourceStore = defineStore("dataSources", () => {
  const projectId = ref<number | null>(null);
  const dataSources = ref<ProjectDataSource[]>([]);
  const isLoading = ref(false);
  const error = ref<string | null>(null);

  const byId = computed(() => new Map(dataSources.value.map((item) => [item.id, item])));

  function resetProjectScope(): void {
    projectId.value = null;
    dataSources.value = [];
    isLoading.value = false;
    error.value = null;
  }
  registerProjectScopeReset(resetProjectScope);

  async function loadProjectDataSources(targetProjectId: number): Promise<ProjectDataSource[]> {
    isLoading.value = true;
    error.value = null;
    try {
      const { data } = await api.get<ProjectDataSource[]>(
        `/projects/${targetProjectId}/data-sources`
      );
      projectId.value = targetProjectId;
      dataSources.value = data;
      return data;
    } catch (err) {
      error.value = getErrorMessage(err);
      return [];
    } finally {
      isLoading.value = false;
    }
  }

  async function createDataSource(
    targetProjectId: number,
    payload: ProjectDataSourceCreatePayload,
  ): Promise<ProjectDataSource | null> {
    error.value = null;
    try {
      const { data } = await api.post<ProjectDataSource>(
        `/projects/${targetProjectId}/data-sources`,
        payload,
      );
      projectId.value = targetProjectId;
      dataSources.value = [...dataSources.value.filter((item) => item.id !== data.id), data]
        .sort((a, b) => a.sort_order - b.sort_order || a.display_name.localeCompare(b.display_name));
      return data;
    } catch (err) {
      error.value = getErrorMessage(err);
      return null;
    }
  }

  async function updateDataSource(
    targetProjectId: number,
    dataSourceId: number,
    payload: ProjectDataSourceUpdatePayload,
  ): Promise<ProjectDataSource | null> {
    error.value = null;
    try {
      const { data } = await api.put<ProjectDataSource>(
        `/projects/${targetProjectId}/data-sources/${dataSourceId}`,
        payload,
      );
      dataSources.value = dataSources.value.map((item) =>
        item.id === dataSourceId ? data : item
      );
      return data;
    } catch (err) {
      error.value = getErrorMessage(err);
      return null;
    }
  }

  function setFromProjectDetail(targetProjectId: number, items: ProjectDataSource[] = []): void {
    projectId.value = targetProjectId;
    dataSources.value = [...items];
  }

  return {
    projectId,
    dataSources,
    byId,
    isLoading,
    error,
    loadProjectDataSources,
    createDataSource,
    updateDataSource,
    setFromProjectDetail,
    resetProjectScope,
  };
});
