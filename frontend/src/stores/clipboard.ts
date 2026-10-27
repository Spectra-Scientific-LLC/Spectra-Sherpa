import { defineStore } from "pinia";
import { ref, watch } from "vue";
import { useAuthStore } from "./auth";
import type { WorkflowNode, WorkflowEdge } from "./workflow";

export interface ClipboardPayload {
  nodes: WorkflowNode[];          // full node objects with params
  edges: WorkflowEdge[];          // only internal edges (both ends in selection)
  sourceWorkflowId: number | null; // for cross-sheet provenance
}

export const useClipboardStore = defineStore("clipboard", () => {
  const payload = ref<ClipboardPayload | null>(null);
  const auth = useAuthStore();
  watch([() => auth.user?.id, () => auth.sessionRevision], () => {
    payload.value = null;
  }, { flush: "sync" });

  const set = (newPayload: ClipboardPayload) => {
    // Deep clone to prevent mutations
    payload.value = JSON.parse(JSON.stringify(newPayload));
  };

  const get = (): ClipboardPayload | null => {
    // Deep clone on get to ensure unique instances
    if (!payload.value) return null;
    return JSON.parse(JSON.stringify(payload.value));
  };

  const isEmpty = () => {
    return payload.value === null || payload.value.nodes.length === 0;
  };

  return { payload, set, get, isEmpty };
});
