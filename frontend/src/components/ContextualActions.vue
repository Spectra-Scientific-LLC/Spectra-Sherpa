<template>
  <div v-if="visibleActions.length || (error && showError)" class="contextual-actions">
    <Button v-for="action in visibleActions" :key="action.key" :label="action.label" :icon="action.icon"
      :loading="running === action.key" :disabled="running !== null || action.disabled" @click="execute(action.key)" />
    <p v-if="error && showError" role="alert">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from "vue";
import Button from "primevue/button";
import { actionContextRevision, setActionContext, useContextualActions, type ActionContext } from "@/composables/useContextualActions";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";

const props = withDefaults(defineProps<{ context: ActionContext | null; showError?: boolean }>(), { showError: true });
const { actions, error, running, execute } = useContextualActions();
const visibleActions = computed(() => actions.value.filter(action => !action.placement));
const auth = useAuthStore();
const project = useProjectStore();
const ownerId = auth.user?.id;
let release: (() => void) | undefined;
watch(() => JSON.stringify([
  props.context?.surface ?? null,
  props.context?.projectId ?? null,
  props.context?.surface === "run" ? props.context.runId : null,
  props.context?.surface === "run" ? props.context.nodeId : null,
  props.context?.surface === "model" ? props.context.runId : null,
  props.context?.surface === "model" ? props.context.artifactUid : null,
  props.context?.surface === "deploy" ? props.context.applicationHandle : null,
  props.context?.surface === "dataset" ? props.context.experimentId : null,
  props.context?.surface === "dataset" ? props.context.fileId : null,
  props.context?.surface === "dataset" ? props.context.selectionRevision : null,
  props.context?.surface === "workflow" ? props.context.workflowId : null,
  props.context?.surface === "workflow" ? props.context.workflowHash : null,
  props.context?.surface === "workflow" ? props.context.unsaved : null,
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
.contextual-actions p { flex-basis: 100%; margin: 0; color: var(--ss-danger-strong); }
</style>
