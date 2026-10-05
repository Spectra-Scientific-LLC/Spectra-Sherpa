<template>
  <details>
    <summary>Analytical qualification of imported applications</summary>
    <p>Operational readiness does not establish intended-use acceptance. Choose an exact imported application to assess and review.</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="loading">Loading qualification candidates…</p>
    <p v-else-if="!applications.length">No imported canonical application is available in this project.</p>
    <label v-else>Application
      <select v-model="selectedId">
        <option :value="null">Select an application</option>
        <option v-for="application in applications" :key="application.canonical_artifact_id" :value="application.canonical_artifact_id">{{ application.name }} — {{ application.artifact_digest }}</option>
      </select>
    </label>
    <QualificationPanel v-if="selected" :key="selected.canonical_artifact_id" :workflow-id="selected.workflow_id" :canonical-artifact-id="selected.canonical_artifact_id" :project-id="projectId" />
  </details>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import api from "@/api/client";
import QualificationPanel from "./QualificationPanel.vue";
const props = defineProps<{ projectId: number }>();
type Application = { canonical_artifact_id: number; workflow_id: number; name: string; artifact_digest: string };
const applications = ref<Application[]>([]);
const selectedId = ref<number | null>(null);
const selected = computed(() => applications.value.find(item => item.canonical_artifact_id === selectedId.value));
const loading = ref(false);
const error = ref("");
let generation = 0;
onBeforeUnmount(() => { generation += 1; });
watch(() => props.projectId, async projectId => {
  const current = ++generation;
  applications.value = []; selectedId.value = null; error.value = ""; loading.value = true;
  try {
    const response = await api.get<Application[]>(`/deploy/projects/${projectId}/qualification-applications`);
    if (current === generation) applications.value = response.data;
  } catch (e) {
    if (current === generation) error.value = "Qualification applications are unavailable. " + String(e);
  } finally { if (current === generation) loading.value = false; }
}, { immediate: true });
</script>
