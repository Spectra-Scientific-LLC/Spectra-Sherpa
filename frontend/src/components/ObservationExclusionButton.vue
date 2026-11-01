<template>
  <span>
    <button
      type="button"
      class="observation-exclusion"
      :class="{
        excluded:
          current?.excluded ||
          current?.restorable === false ||
          (!actions && usedInResult === false),
      }"
      :disabled="!current?.restorable"
      :title="description"
      :aria-label="description"
      @click="toggle"
    >
      <span aria-hidden="true">{{
        !actions && usedInResult != null
          ? usedInResult
            ? "○"
            : "⊗"
          : !current
            ? "?"
            : current.excluded || !current.restorable
              ? "⊗"
              : "○"
      }}</span>
    </button>
  </span>
</template>

<script setup lang="ts">
import { computed, inject } from "vue";
import { useNotifier } from "@/composables/useNotifier";
import {
  WORKFLOW_POPULATION_ACTIONS,
  type WorkflowPopulationActions,
} from "@/utils/workflowPopulation";
const props = defineProps<{ observationRef: string; label?: string; usedInResult?: boolean }>();
const actions = inject<WorkflowPopulationActions | null>(WORKFLOW_POPULATION_ACTIONS, null);
const scope = actions?.scope?.();
const resolve = () =>
  actions?.scope?.() === scope ? actions?.resolve(props.observationRef) : null;
const current = computed(resolve);
const description = computed(() => {
  const state = current.value;
  const action = !actions
    ? props.usedInResult == null
      ? "Not recorded"
      : props.usedInResult
        ? "Used in this result (read-only)"
        : "Not used in this result (read-only)"
    : !state
      ? "Source changed; inspect Load Data."
      : !state.restorable
        ? "Excluded in My Dataset; restore there."
        : `${state.excluded ? "Restore" : "Exclude"} ${props.label || "observation"}.`;
  return action;
});
function toggle() {
  try {
    const state = resolve();
    if (!state?.restorable)
      throw new Error("Inspect Load Data or restore source exclusions in My Dataset.");
    actions!.change([props.observationRef], !state.excluded);
  } catch (failure) {
    useNotifier().notifySystemEvent({
      severity: "error",
      title: "Exclusion not changed",
      message: failure instanceof Error ? failure.message : "Could not update workflow exclusion.",
    });
  }
}
</script>

<style scoped>
.observation-exclusion {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.7rem;
  height: 1.7rem;
  border: 1px solid transparent;
  border-radius: 0.25rem;
  background: transparent;
  color: var(--ss-text-muted);
  cursor: pointer;
  font-size: 1.1rem;
}
.observation-exclusion.excluded {
  color: var(--ss-excluded);
}
.observation-exclusion:hover,
.observation-exclusion:focus-visible {
  border-color: currentColor;
}
.observation-exclusion:disabled {
  cursor: default;
  opacity: 0.7;
}
</style>
