import { defineStore } from "pinia";
import { ref, watch } from "vue";

const AUTO_EXECUTE_KEY = "spectra_sherpa_workflow_builder_auto_execute";
const AUTO_SAVE_MEMORY_KEY = "spectra_sherpa_workflow_builder_auto_save_memory";

function loadBoolean(key: string, fallback = false): boolean {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return fallback;
  }
}

export const useWorkflowBuilderConfigStore = defineStore("workflowBuilderConfig", () => {
  const autoExecute = ref(loadBoolean(AUTO_EXECUTE_KEY));
  const autoSaveMemory = ref(loadBoolean(AUTO_SAVE_MEMORY_KEY, true));

  watch(autoExecute, (value) => {
    try {
      localStorage.setItem(AUTO_EXECUTE_KEY, value ? "1" : "0");
    } catch {
      // Ignore storage failures in restricted browser contexts.
    }
  });

  watch(autoSaveMemory, (value) => {
    try {
      localStorage.setItem(AUTO_SAVE_MEMORY_KEY, value ? "1" : "0");
    } catch {
      // Ignore storage failures in restricted browser contexts.
    }
  });

  return {
    autoExecute,
    autoSaveMemory,
  };
});
