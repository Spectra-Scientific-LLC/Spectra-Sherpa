<template>
  <Panel header="Saved models" toggleable>
    <WorkspaceState v-if="loading" kind="loading" message="Loading saved models…" />
    <WorkspaceState v-else-if="error" kind="error" :message="error"><Button label="Retry" @click="load" /></WorkspaceState>
    <p v-else-if="!models.length">No saved models in this project.</p>
    <ul v-else class="saved-models">
      <li v-for="model in models" :key="model.artifact_uid">
        <span>{{ model.display_name || model.name }} <small>{{ model.model_type }}</small></span>
        <Button :label="model.is_deploy_ready ? 'Review application' : 'Make application'" class="p-button-sm p-button-outlined"
          :aria-label="`${model.is_deploy_ready ? 'Review application' : 'Make application'}: ${model.display_name || model.name}`"
          @click="openModel(model.artifact_uid)" />
      </li>
    </ul>
    <p v-if="models.length" class="model-review-note">Review the model and its validation in Models before promotion.</p>
    <div v-if="offset || models.length === pageSize" class="model-pages">
      <Button label="Previous" class="p-button-text p-button-sm" :disabled="loading || !offset" @click="changePage(-pageSize)" />
      <Button label="Next" class="p-button-text p-button-sm" :disabled="loading || models.length < pageSize" @click="changePage(pageSize)" />
    </div>
  </Panel>
</template>
<script setup lang="ts">
import { ref, watch } from "vue";
import { useRouter } from "vue-router";
import Panel from "primevue/panel";
import Button from "primevue/button";
import WorkspaceState from "@/components/workspace/WorkspaceState.vue";
import api from "@/api/client";
import { useProjectStore } from "@/stores/project";
import { useAuthStore } from "@/stores/auth";
import { useScopedRequest } from "@/composables/useScopedRequest";
const project = useProjectStore(), auth = useAuthStore(), router = useRouter();
const models = ref<Array<{ artifact_uid: string; name: string; display_name?: string | null; model_type: string; is_deploy_ready?: boolean }>>([]);
const loading = ref(false), error = ref(""), offset = ref(0), pageSize = 25;
const read = useScopedRequest(() => [auth.user?.id, auth.sessionRevision, project.currentProjectId, offset.value], () => { models.value = []; loading.value = false; error.value = ""; });
async function load() {
  const ticket = read.begin(), projectId = project.currentProjectId;
  if (projectId == null) return;
  loading.value = true; error.value = "";
  try {
    const response = await api.get<typeof models.value>("/models", { params: { project_id: projectId, offset: offset.value, limit: pageSize }, signal: ticket.signal });
    if (ticket.isCurrent()) models.value = response.data;
  } catch { if (ticket.isCurrent()) error.value = "Saved models could not be loaded."; }
  finally { if (ticket.isCurrent()) loading.value = false; }
}
function changePage(delta: number) { offset.value = Math.max(0, offset.value + delta); void load(); }
function openModel(uid: string) {
  if (!models.value.some(model => model.artifact_uid === uid) || project.currentProjectId == null) return;
  void router.push({ path: "/runs", query: { tab: "models", project: String(project.currentProjectId), artifact: uid } });
}
watch(() => [auth.user?.id, auth.sessionRevision, project.currentProjectId], () => { offset.value = 0; void load(); }, { immediate: true });
</script>
<style scoped>
.saved-models { padding: 0; list-style: none; }
.saved-models li { display: flex; gap: 1rem; align-items: center; justify-content: space-between; padding: .5rem 0; border-bottom: 1px solid var(--surface-border); }
.saved-models small, .model-review-note { color: var(--text-color-secondary); font-size: .8rem; }
.model-pages { display: flex; gap: .5rem; }
</style>
