import { defineStore } from "pinia";
import { computed, ref } from "vue";
import api from "@/api/client";
import { registerProjectScopeReset } from "@/stores/projectScopeRegistry";
import { activeProjectScope } from "@/stores/projectScopeRegistry";
import { useAuthStore } from "@/stores/auth";
import { useScopedRequest, type ScopedRequestTicket } from "@/composables/useScopedRequest";
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
  const identity = () => [useAuthStore().user?.id, useAuthStore().sessionRevision, activeProjectScope.value, projectId.value];
  const readScope = useScopedRequest(identity, () => { isLoading.value = false; });
  const mutationScope = useScopedRequest(identity);
  let mutationTicket: ScopedRequestTicket | undefined;
  function captureMutationScope(): ScopedRequestTicket {
    if (!mutationTicket?.isCurrent()) mutationTicket = mutationScope.begin();
    return mutationTicket;
  }

  const byId = computed(() => new Map(dataSources.value.map((item) => [item.id, item])));

  function resetProjectScope(): void {
    readScope.invalidate();
    mutationScope.invalidate();
    projectId.value = null;
    dataSources.value = [];
    isLoading.value = false;
    error.value = null;
  }
  registerProjectScopeReset(resetProjectScope);

  async function loadProjectDataSources(targetProjectId: number): Promise<ProjectDataSource[]> {
    if (projectId.value !== targetProjectId) dataSources.value = [];
    projectId.value = targetProjectId;
    const request = readScope.begin();
    isLoading.value = true;
    error.value = null;
    try {
      const { data } = await api.get<ProjectDataSource[]>(
        `/projects/${targetProjectId}/data-sources`, { signal: request.signal }
      );
      if (!request.isCurrent()) return [];
      projectId.value = targetProjectId;
      dataSources.value = data;
      return data;
    } catch (err) {
      if (request.isCurrent()) error.value = getErrorMessage(err);
      return [];
    } finally {
      if (request.isCurrent()) isLoading.value = false;
    }
  }

  async function createDataSource(
    targetProjectId: number,
    payload: ProjectDataSourceCreatePayload,
  ): Promise<ProjectDataSource | null> {
    const request = captureMutationScope();
    error.value = null;
    try {
      const { data } = await api.post<ProjectDataSource>(
        `/projects/${targetProjectId}/data-sources`,
        payload,
      );
      if (!request.isCurrent()) return data;
      projectId.value = targetProjectId;
      dataSources.value = [...dataSources.value.filter((item) => item.id !== data.id), data]
        .sort((a, b) => a.sort_order - b.sort_order || a.display_name.localeCompare(b.display_name));
      return data;
    } catch (err) {
      if (request.isCurrent()) error.value = getErrorMessage(err);
      return null;
    }
  }

  async function updateDataSource(
    targetProjectId: number,
    dataSourceId: number,
    payload: ProjectDataSourceUpdatePayload,
  ): Promise<ProjectDataSource | null> {
    const request = captureMutationScope();
    error.value = null;
    try {
      const { data } = await api.put<ProjectDataSource>(
        `/projects/${targetProjectId}/data-sources/${dataSourceId}`,
        payload,
      );
      if (!request.isCurrent()) return data;
      dataSources.value = dataSources.value.map((item) =>
        item.id === dataSourceId ? data : item
      );
      return data;
    } catch (err) {
      if (request.isCurrent()) error.value = getErrorMessage(err);
      return null;
    }
  }

  function setFromProjectDetail(targetProjectId: number, items: ProjectDataSource[] = []): void {
    readScope.invalidate();
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
