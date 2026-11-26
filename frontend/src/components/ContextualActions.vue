<template>
  <div v-if="actions.length || error" class="contextual-actions">
    <!-- A journey step shows where the decision sits and what it does, beside its one button. -->
    <section v-for="action in actions" :key="action.key" class="contextual-action"
      :class="{ 'contextual-action--step': action.step }" :aria-label="action.step ? `Next step: ${action.step.title}` : action.label">
      <div v-if="action.step" class="contextual-action__step">
        <ol class="contextual-action__progress" :aria-label="`Step ${action.step.index} of ${action.step.total}`">
          <li v-for="index in action.step.total" :key="index"
            :class="{ done: index < action.step.index, current: index === action.step.index }" />
        </ol>
        <strong>Step {{ action.step.index }} of {{ action.step.total }} · {{ action.step.title }}</strong>
        <span v-if="action.step.detail">{{ action.step.detail }}</span>
      </div>
      <Button :label="action.label" :icon="action.icon"
        :loading="running === action.key" :disabled="running !== null" @click="execute(action.key)" />
    </section>
    <p v-if="error && showError" role="alert">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, watch } from "vue";
import Button from "primevue/button";
import { actionContextRevision, setActionContext, useContextualActions, type ActionContext } from "@/composables/useContextualActions";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";

const props = withDefaults(defineProps<{ context: ActionContext | null; showError?: boolean }>(), { showError: true });
const { actions, error, running, execute } = useContextualActions();
const auth = useAuthStore();
const project = useProjectStore();
const ownerId = auth.user?.id;
let release: (() => void) | undefined;
watch(() => JSON.stringify([
  props.context?.surface ?? null,
  props.context?.projectId ?? null,
  props.context?.surface === "run" ? props.context.runId : null,
  props.context?.surface === "run" ? props.context.nodeId : null,
  props.context?.surface === "deploy" ? props.context.applicationHandle : null,
  props.context?.surface === "dataset" ? props.context.experimentId : null,
  props.context?.surface === "dataset" ? props.context.fileId : null,
  props.context?.surface === "dataset" ? props.context.selectionRevision : null,
  props.context?.surface === "workflow" ? props.context.workflowId : null,
  props.context?.surface === "workflow" ? props.context.workflowHash : null,
  actionContextRevision.value,
  auth.user?.id ?? null,
  project.currentProjectId ?? null,
]), () => {
  release?.();
  const value = auth.user?.id === ownerId && props.context?.projectId === project.currentProjectId
    ? props.context : null;
  release = setActionContext(value);
}, { immediate: true, flush: "post" });
onBeforeUnmount(() => release?.());
</script>

<style scoped>
.contextual-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
.contextual-action { display: flex; align-items: center; gap: 0.75rem; }
.contextual-action--step {
  flex: 1 1 100%; justify-content: space-between; flex-wrap: wrap;
  padding: 0.75rem 1rem; border: 1px solid var(--surface-border); border-radius: 6px; background: var(--surface-card);
}
.contextual-action__step { display: flex; flex-direction: column; gap: 0.25rem; min-width: 0; }
.contextual-action__step span { color: var(--text-color-secondary); }
.contextual-action__progress { display: flex; gap: 0.25rem; margin: 0 0 0.25rem; padding: 0; list-style: none; }
.contextual-action__progress li { width: 1.5rem; height: 0.25rem; border-radius: 2px; background: var(--surface-border); }
.contextual-action__progress li.done { background: var(--ss-action, var(--primary-color)); opacity: 0.5; }
.contextual-action__progress li.current { background: var(--ss-action, var(--primary-color)); }
.contextual-actions p { flex-basis: 100%; margin: 0; color: var(--ss-danger-strong); }
</style>
