/**
 * Onboarding state composable.
 *
 * Fetches the user's first-run state from the backend and exposes
 * reactive flags that the OnboardingBanner component uses to decide
 * what to display.
 *
 * State is cached at module level so multiple components share the same data.
 */
import { ref, computed } from "vue";
import api from "@/api/client";

interface OnboardingSteps {
  hasProject: boolean;
  hasData: boolean;
  hasWorkflow: boolean;
  hasExecuted: boolean;
  hasModel: boolean;
}

interface OnboardingState {
  isFirstRun: boolean;
  steps: OnboardingSteps;
  counts: {
    projects: number;
    experiments: number;
    workflows: number;
    models: number;
  };
}

// Module-level shared state
const state = ref<OnboardingState | null>(null);
const dismissed = ref(localStorage.getItem("onboarding_dismissed") === "true");
const loaded = ref(false);

export function useOnboarding() {
  const showOnboarding = computed(() => {
    if (dismissed.value) return false;
    if (!state.value) return false;
    return state.value.isFirstRun;
  });

  const allStepsComplete = computed(() => {
    if (!state.value) return false;
    const s = state.value.steps;
    return s.hasProject && s.hasData && s.hasWorkflow;
  });

  async function fetchOnboardingState() {
    if (loaded.value) return;
    try {
      const response = await api.get("/health/onboarding");
      const data = response.data;
      state.value = {
        isFirstRun: data.is_first_run,
        steps: {
          hasProject: data.steps.has_project,
          hasData: data.steps.has_data,
          hasWorkflow: data.steps.has_workflow,
          hasExecuted: data.steps.has_executed,
          hasModel: data.steps.has_model,
        },
        counts: data.counts,
      };
      loaded.value = true;

      // Auto-dismiss if all steps complete
      if (state.value.steps.hasProject && state.value.steps.hasData && state.value.steps.hasWorkflow) {
        dismissed.value = true;
      }
    } catch {
      // Silently fail — don't block the app
      loaded.value = true;
    }
  }

  function dismissOnboarding() {
    dismissed.value = true;
    localStorage.setItem("onboarding_dismissed", "true");
  }

  function resetOnboarding() {
    dismissed.value = false;
    loaded.value = false;
    state.value = null;
    localStorage.removeItem("onboarding_dismissed");
  }

  return {
    state,
    showOnboarding,
    allStepsComplete,
    fetchOnboardingState,
    dismissOnboarding,
    resetOnboarding,
  };
}
