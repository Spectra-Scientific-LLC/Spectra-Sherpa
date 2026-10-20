import { ref, watch } from "vue";
import type { WorkflowNode } from "@/stores/workflow";
import type { NodeParameterMetadata } from "@/types";
import type { ScopeIdentity } from "@/composables/useScopedRequest";

// Parameter payloads include legacy node-specific structures, not just scalars.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type InspectorParams = Record<string, any>;

export function cloneInspectorParams(value: InspectorParams): InspectorParams {
  // Vue proxies may be nested: structuredClone(toRaw(value)) is not sufficient.
  const clone = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(clone);
    if (item && typeof item === "object") {
      return Object.fromEntries(Object.entries(item).map(([key, child]) => [key, clone(child)]));
    }
    return item;
  };
  return clone(value) as InspectorParams;
}

export function stableParamSignature(value: unknown): string {
  const normalize = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(normalize);
    if (item && typeof item === "object") {
      return Object.fromEntries(
        Object.entries(item).sort(([a], [b]) => a.localeCompare(b))
          .map(([key, child]) => [key, normalize(child)]),
      );
    }
    return item;
  };
  return JSON.stringify(normalize(value ?? {}));
}

interface ParameterEditorOptions {
  selectedNode: () => WorkflowNode | null;
  identity: () => readonly ScopeIdentity[];
  defaults: (nodeType: string) => InspectorParams;
  parameters: () => NodeParameterMetadata[];
  fetchReferenceDatasets: () => unknown;
}

/** Owns detached editable drafts only; no retained result is an input. */
export function useInspectorParameters(options: ParameterEditorOptions) {
  const localParams = ref<InspectorParams>({});
  const currentNodeId = ref<string | null>(null);
  const lastSyncedParamsSignature = ref("");
  const dirty = () => stableParamSignature(localParams.value) !== lastSyncedParamsSignature.value;

  function syncLocalParamsFromNode(node: WorkflowNode, { force = false } = {}): boolean {
    if (!force && dirty()) return false;
    currentNodeId.value = node.id;
    localParams.value = cloneInspectorParams({ ...options.defaults(node.type), ...node.params });
    lastSyncedParamsSignature.value = stableParamSignature(localParams.value);
    return true;
  }

  function syncLocalParamsFromExternal(
    nodeType: string,
    params: InspectorParams | undefined,
    { fetchReferenceDatasets = false } = {},
  ): boolean {
    if (dirty()) return false;
    localParams.value = cloneInspectorParams({ ...options.defaults(nodeType), ...params });
    lastSyncedParamsSignature.value = stableParamSignature(localParams.value);
    if (fetchReferenceDatasets && ["eigenvector", "sklearn"].includes(localParams.value.source)) {
      void options.fetchReferenceDatasets();
    }
    return true;
  }

  function resetParamsOutOfScope(params: InspectorParams): InspectorParams {
    const next = cloneInspectorParams(params);
    for (const parameter of options.parameters()) {
      if (!parameter.visible_when) continue;
      const inScope = Object.entries(parameter.visible_when).every(([control, admitted]) =>
        admitted.includes(String(next[control] ?? "")),
      );
      if (!inScope && parameter.default !== undefined) {
        next[parameter.name] = cloneInspectorParams({ value: parameter.default }).value;
      }
    }
    return next;
  }

  // Installed after the component's legacy fallback definitions are initialized.
  function startWatching(): void {
    watch(() => [...options.identity(), options.selectedNode()?.id, options.selectedNode()?.type], (next, previous) => {
      if (previous && next.length === previous.length &&
        next.every((value, index) => Object.is(value, previous[index]))) return;
      const node = options.selectedNode();
      if (node) syncLocalParamsFromNode(node, { force: true });
      else {
        currentNodeId.value = null;
        localParams.value = {};
        lastSyncedParamsSignature.value = "";
      }
    }, { immediate: true, flush: "sync" });
    watch(() => options.selectedNode()?.params, () => {
      const node = options.selectedNode();
      if (node && node.id === currentNodeId.value) syncLocalParamsFromNode(node);
    }, { deep: true });
    watch(options.parameters, () => {
      const node = options.selectedNode();
      if (!node || syncLocalParamsFromNode(node)) return;
      localParams.value = cloneInspectorParams({ ...options.defaults(node.type), ...localParams.value });
    }, { deep: true });
  }

  return {
    localParams, currentNodeId, lastSyncedParamsSignature, syncLocalParamsFromNode,
    syncLocalParamsFromExternal, resetParamsOutOfScope, startWatching,
  };
}
