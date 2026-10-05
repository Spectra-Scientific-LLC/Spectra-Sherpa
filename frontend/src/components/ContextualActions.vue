<template>
  <div v-if="actions.length || error" class="contextual-actions">
    <Button v-for="action in actions" :key="action.key" :label="action.label" :icon="action.icon"
      :loading="running === action.key" :disabled="running !== null" @click="execute(action.key)" />
    <p v-if="error" role="alert">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, watch } from "vue";
import Button from "primevue/button";
import { actionContextRevision, setActionContext, useContextualActions, type ActionContext } from "@/composables/useContextualActions";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";

const props = defineProps<{ context: ActionContext | null }>();
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
.contextual-actions p { flex-basis: 100%; margin: 0; color: var(--red-700); }
</style>
