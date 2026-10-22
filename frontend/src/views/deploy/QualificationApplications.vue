<template>
  <details :open="!!reviewWorkflowId">
    <summary>Review imported fitted applications</summary>
    <MethodHelp topic="qualification" label="Analytical qualification" />
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="loading">Loading qualification candidates…</p>
    <p v-else-if="!applications.length">No imported canonical application is available in this project.</p>
    <label v-else>Application
      <select v-model="selectedId">
        <option :value="null">Select an application</option>
        <option v-for="application in applications" :key="application.canonical_artifact_id" :value="application.canonical_artifact_id">{{ application.name }} — {{ application.artifact_digest }}</option>
      </select>
    </label>
    <button v-if="selected" type="button" @click="reviewOpen = true">Review for promotion</button>
    <ModelPromotionReview v-if="selected && reviewOpen" :key="selected.canonical_artifact_id" :workflow-id="selected.workflow_id" :canonical-artifact-id="selected.canonical_artifact_id" :project-id="projectId" @close="reviewOpen = false" @confirmed="reviewOpen = false" />
  </details>
</template>
<script setup lang="ts">
import MethodHelp from "@/components/MethodHelp.vue";
import { computed, ref, watch } from "vue";
import api from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { useScopedRequest } from "@/composables/useScopedRequest";
import ModelPromotionReview from "@/components/ModelPromotionReview.vue";
const props = defineProps<{ projectId: number; reviewWorkflowId?: number }>();
type Application = { canonical_artifact_id: number; workflow_id: number; name: string; artifact_digest: string };
const applications = ref<Application[]>([]);
const selectedId = ref<number | null>(null);
const selected = computed(() => applications.value.find(item => item.canonical_artifact_id === selectedId.value));
const loading = ref(false);
const reviewOpen = ref(false);
const error = ref("");
const auth = useAuthStore();
const identity = () => [auth.user?.id, auth.sessionRevision, props.projectId, props.reviewWorkflowId];
const requests = useScopedRequest(identity);
watch(identity, async () => {
  const request = requests.begin();
  applications.value = []; selectedId.value = null; reviewOpen.value = false; error.value = ""; loading.value = true;
  try {
    const response = await api.get<Application[]>(`/deploy/projects/${props.projectId}/qualification-applications`, { signal: request.signal });
    if (request.isCurrent()) {
      applications.value = response.data;
      const requested = response.data.find(item => item.workflow_id === props.reviewWorkflowId);
      if (requested) { selectedId.value = requested.canonical_artifact_id; reviewOpen.value = true; }
    }
  } catch (e) {
    if (request.isCurrent()) error.value = "Qualification applications are unavailable. " + String(e);
  } finally { if (request.isCurrent()) loading.value = false; }
}, { immediate: true });
</script>
