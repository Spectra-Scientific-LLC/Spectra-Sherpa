/**
 * Custom Algo Pinia store — manages CRUD and node metadata for
 * project-scoped custom algorithm nodes.
 */

import { defineStore } from "pinia";
import { ref } from "vue";
import api from "@/api/client";
import { useWorkflowStore } from "@/stores/workflow";
import type { NodeTypeMetadata } from "@/types";

export interface CustomAlgo {
  id: number;
  project_id: number;
  user_id: number;
  name: string;
  slug: string;
  description: string | null;
  code: string;
  mode: string;
  icon: string;
  node_type: string;
  created_at: string;
  updated_at: string;
}

export interface CreateCustomAlgo {
  name: string;
  slug: string;
  description?: string;
  code?: string;
  mode?: string;
  icon?: string;
}

export interface UpdateCustomAlgo {
  name?: string;
  description?: string;
  code?: string;
  mode?: string;
  icon?: string;
}

function getErrorMessage(e: unknown): string {
  if (e && typeof e === "object" && "response" in e) {
    const resp = (e as { response?: { data?: { detail?: string } } }).response;
    if (resp?.data?.detail) return resp.data.detail;
  }
  if (e instanceof Error) return e.message;
  return String(e);
}

export const useCustomAlgoStore = defineStore("customAlgo", () => {
  const algos = ref<CustomAlgo[]>([]);
  const nodeMetadata = ref<NodeTypeMetadata[]>([]);
  const isLoading = ref(false);
  const error = ref<string | null>(null);

  async function fetchForProject(projectId: number): Promise<void> {
    isLoading.value = true;
    error.value = null;
    try {
      const { data } = await api.get<CustomAlgo[]>(
        `/projects/${projectId}/custom-algos`
      );
      algos.value = data;
    } catch (e) {
      error.value = getErrorMessage(e);
    } finally {
      isLoading.value = false;
    }
  }

  async function fetchNodesForProject(projectId: number): Promise<void> {
    const workflowStore = useWorkflowStore();
    try {
      const { data } = await api.get<NodeTypeMetadata[]>(
        `/projects/${projectId}/custom-algos/nodes`
      );
      nodeMetadata.value = data;
      workflowStore.replaceProjectScopedNodeMetadata(data);
    } catch (e) {
      console.error("[CustomAlgoStore] Failed to fetch node metadata:", e);
    }
  }

  async function create(
    projectId: number,
    payload: CreateCustomAlgo
  ): Promise<CustomAlgo | null> {
    error.value = null;
    try {
      const { data } = await api.post<CustomAlgo>(
        `/projects/${projectId}/custom-algos`,
        payload
      );
      algos.value.push(data);
      // Refresh node metadata for toolbar
      await fetchNodesForProject(projectId);
      return data;
    } catch (e) {
      error.value = getErrorMessage(e);
      return null;
    }
  }

  async function update(
    projectId: number,
    algoId: number,
    payload: UpdateCustomAlgo
  ): Promise<CustomAlgo | null> {
    error.value = null;
    try {
      const { data } = await api.put<CustomAlgo>(
        `/projects/${projectId}/custom-algos/${algoId}`,
        payload
      );
      const idx = algos.value.findIndex((a) => a.id === algoId);
      if (idx !== -1) algos.value[idx] = data;
      // Refresh node metadata for toolbar
      await fetchNodesForProject(projectId);
      return data;
    } catch (e) {
      error.value = getErrorMessage(e);
      return null;
    }
  }

  async function remove(
    projectId: number,
    algoId: number
  ): Promise<boolean> {
    error.value = null;
    try {
      await api.delete(`/projects/${projectId}/custom-algos/${algoId}`);
      algos.value = algos.value.filter((a) => a.id !== algoId);
      // Refresh node metadata for toolbar
      await fetchNodesForProject(projectId);
      return true;
    } catch (e) {
      error.value = getErrorMessage(e);
      return false;
    }
  }

  function getAlgoByNodeType(nodeType: string): CustomAlgo | undefined {
    return algos.value.find((a) => a.node_type === nodeType);
  }

  function $reset(): void {
    const workflowStore = useWorkflowStore();
    algos.value = [];
    nodeMetadata.value = [];
    workflowStore.replaceProjectScopedNodeMetadata([]);
    isLoading.value = false;
    error.value = null;
  }

  return {
    algos,
    nodeMetadata,
    isLoading,
    error,
    fetchForProject,
    fetchNodesForProject,
    create,
    update,
    remove,
    getAlgoByNodeType,
    $reset,
  };
});
