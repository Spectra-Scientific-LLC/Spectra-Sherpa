<template>
  <Panel header="Imported Models" toggleable :collapsed="!reviewWorkflowId">
    <MethodHelp topic="qualification" label="Analytical qualification" />
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="loading">Loading imported models…</p>
    <p v-else-if="!applications.length">No imported canonical application is available in this project.</p>
    <label v-else>Application
      <select v-model="selectedId" class="p-inputtext p-inputtext-sm">
        <option :value="null">Select an application</option>
        <option v-for="application in applications" :key="application.canonical_artifact_id" :value="application.canonical_artifact_id">{{ application.name }} — {{ application.artifact_digest }}</option>
      </select>
    </label>
    <Button v-if="selected && isLocalApplication" label="Open Deploy" :disabled="openingApplication" class="p-button-text p-button-sm" @click="openLocalApplication" />
    <Button v-if="selected && !isLocalApplication" label="Review for promotion" class="p-button-text p-button-sm" @click="reviewOpen = true" />
    <ModelPromotionReview v-if="selected && reviewOpen && !isLocalApplication" :key="selected.canonical_artifact_id" :workflow-id="selected.workflow_id" :canonical-artifact-id="selected.canonical_artifact_id" :project-id="projectId" @close="reviewOpen = false" @confirmed="reviewOpen = false" />
  </Panel>
</template>
<script setup lang="ts">
import MethodHelp from "@/components/MethodHelp.vue";
import Panel from "primevue/panel";
import Button from "primevue/button";
import { computed, ref, watch } from "vue";
import api from "@/api/client";
import { useRouter } from "vue-router";
import { useAppConfig } from "@/composables/useAppConfig";
import { useDeployStore } from "@/stores/deploy";
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
const router = useRouter();
const deploy = useDeployStore();
const { appMode } = useAppConfig();
const isLocalApplication = computed(() => appMode?.value === "local");
const openingApplication = ref(false);
const opening = useScopedRequest(() => [auth.user?.id, auth.sessionRevision, props.projectId, appMode?.value, selectedId.value],
  () => { openingApplication.value = false; });
async function openLocalApplication(): Promise<void> {
  const application = selected.value;
  if (!isLocalApplication.value || !application || openingApplication.value) return;
  const ticket = opening.begin();
  openingApplication.value = true; error.value = "";
  try {
    await deploy.fetchApplications(props.projectId);
    if (!ticket.isCurrent()) return;
    const released = deploy.applications.find(item => item.canonical_artifact_id === application.canonical_artifact_id
      && item.workflow_id === application.workflow_id && item.deploy_ready);
    if (!released?.application_handle) throw new Error("not_available");
    await router.push({ path: "/deploy", query: { project: String(props.projectId), application: released.application_handle } });
  } catch {
    if (ticket.isCurrent()) error.value = "This application is unavailable. Check its saved model compatibility and dependencies.";
  } finally { if (ticket.isCurrent()) openingApplication.value = false; }
}
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
      if (requested) { selectedId.value = requested.canonical_artifact_id; reviewOpen.value = !isLocalApplication.value; }
    }
  } catch (e) {
    if (request.isCurrent()) error.value = "Qualification applications are unavailable. " + String(e);
  } finally { if (request.isCurrent()) loading.value = false; }
}, { immediate: true });
</script>
