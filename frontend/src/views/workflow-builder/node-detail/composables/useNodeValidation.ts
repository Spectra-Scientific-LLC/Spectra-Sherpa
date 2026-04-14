import { ref, computed, type Ref } from "vue";
import type { useWorkflowStore } from "@/stores/workflow";

export interface ValidationError {
  param_name: string;
  message: string;
}

type WorkflowStore = ReturnType<typeof useWorkflowStore>;

export function useNodeValidation(
  workflowStore: WorkflowStore,
  nodeType: Ref<string | null | undefined>,
  localParams: Ref<Record<string, unknown>>,
) {
  const validationErrors = ref<ValidationError[]>([]);

  const displayedValidationErrors = computed(() =>
    validationErrors.value.filter((e) => e.param_name !== "_metadata"),
  );

  const hasValidationErrors = computed(() => displayedValidationErrors.value.length > 0);

  const validateParams = () => {
    if (!nodeType.value) {
      validationErrors.value = [];
      return;
    }
    if (workflowStore.isLoadingNodeLibrary) {
      validationErrors.value = [];
      return;
    }
    if (workflowStore.nodeLibraryLoadError || workflowStore.nodeLibrary.size === 0) {
      validationErrors.value = [];
      return;
    }
    validationErrors.value = workflowStore.validateNodeParams(
      nodeType.value,
      localParams.value,
    );
  };

  const getParamError = (paramName: string): string | null => {
    const error = validationErrors.value.find(
      (e) => e.param_name === paramName && e.param_name !== "_metadata",
    );
    return error ? error.message : null;
  };

  return {
    validationErrors,
    displayedValidationErrors,
    hasValidationErrors,
    validateParams,
    getParamError,
  };
}
