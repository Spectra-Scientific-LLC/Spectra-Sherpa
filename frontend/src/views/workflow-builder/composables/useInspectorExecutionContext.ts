import { computed, ref, watch, type Ref } from "vue";
import type { WorkflowNode } from "@/stores/workflow";
import type { ScopeIdentity } from "@/composables/useScopedRequest";
import type { ValidationError } from "../node-detail/composables/useNodeValidation";
import { cloneInspectorParams, stableParamSignature, type InspectorParams } from "./useInspectorParameters";

interface ExecutionContextOptions {
  selectedNode: () => WorkflowNode | null;
  identity: () => readonly ScopeIdentity[];
  disabled: () => boolean;
  disabledReason: () => string;
  localParams: Ref<InspectorParams>;
  lastSyncedParamsSignature: Ref<string>;
  validate: (node: WorkflowNode, params: InspectorParams) => ValidationError[];
  contextualErrors: () => ValidationError[];
  scopeParams: (params: InspectorParams) => InspectorParams;
  update: (nodeId: string, params: InspectorParams) => void;
  execute: (nodeId: string) => void;
}

/** Draft validation and execution admission; never rewrites execution evidence. */
export function useInspectorExecutionContext(options: ExecutionContextOptions) {
  const validationErrors = ref<ValidationError[]>([]);
  watch(() => [...options.identity(), options.selectedNode()?.id], (next, previous) => {
    if (next.some((value, index) => !Object.is(value, previous[index]))) validationErrors.value = [];
  }, { flush: "sync" });
  const hasValidationErrors = computed(() => validationErrors.value.length > 0);
  const getParamError = (name: string) =>
    validationErrors.value.find(error => error.param_name === name)?.message ?? null;
  const runNodeDisabledReason = computed(() =>
    options.disabled() ? options.disabledReason() || "This node cannot run here."
      : hasValidationErrors.value ? "Resolve the parameter validation error before running." : "",
  );
  function validateParams(): void {
    const node = options.selectedNode();
    validationErrors.value = node
      ? [...options.validate(node, options.localParams.value), ...options.contextualErrors()]
      : [];
  }
  function emitParams(): void {
    const node = options.selectedNode();
    if (!node) return;
    const scoped = options.scopeParams(options.localParams.value);
    if (stableParamSignature(scoped) !== stableParamSignature(options.localParams.value)) {
      options.localParams.value = scoped;
    }
    validateParams();
    const params = cloneInspectorParams(options.localParams.value);
    options.lastSyncedParamsSignature.value = stableParamSignature(params);
    options.update(node.id, params);
  }
  function executeNode(): void {
    const node = options.selectedNode();
    if (!node || options.disabled()) return;
    validateParams();
    if (hasValidationErrors.value) return;
    options.update(node.id, options.scopeParams(options.localParams.value));
    options.execute(node.id);
  }
  return { validationErrors, hasValidationErrors, getParamError, runNodeDisabledReason,
    validateParams, emitParams, executeNode };
}
