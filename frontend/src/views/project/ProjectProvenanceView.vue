<template>
  <section class="provenance-page">
    <WorkspacePageHeader title="Provenance" :identity="summary?.project_name ?? projectStore.currentProject?.name" />

    <p v-if="projectAdmissionError" role="alert" class="error-note">{{ projectAdmissionError }}</p>
    <p v-else-if="projectStore.currentProjectId == null" class="empty-note">Select a project to see its evidence.</p>
    <p v-else-if="store.error" role="alert" class="error-note">{{ store.error }}</p>
    <p v-else-if="store.loading && !summary" class="empty-note">Checking project evidence…</p>

    <template v-if="summary">
      <p class="scope-note">Checked {{ new Date(summary.verified_at).toLocaleString() }} · Basic availability <MethodHelp topic="availability" label="Availability lights" /></p>
      <ol class="record-list" aria-label="Current project evidence records">
        <li v-for="record in summary.records" :key="record.kind" class="record-row">
          <span class="record-light" :class="`status-${availabilityState(record)}`" :aria-label="availabilityDetail(record)"></span>
          <div class="record-text">
            <h2>{{ record.label }} <small>{{ record.name ?? (availabilityState(record) === 'healthy' ? 'Available in project' : 'Not recorded') }}</small></h2>
            <p>{{ availabilityDetail(record) }}</p>
            <p>Provenance: {{ record.detail }}</p>
            <code v-if="record.digest">SHA-256 {{ record.digest }}</code>
            <p v-if="record.kind === 'environment' && record.packages" class="package-versions">
              {{ Object.entries(record.packages).map(([name, version]) => `${name} ${version}`).join(" · ") }}
            </p>
          </div>
          <RouterLink
            v-if="record.state !== 'missing' || ['source', 'dataset', 'workflow', 'run', 'model'].includes(record.kind)"
            class="open-link"
            :to="recordLink(record)"
          >Open</RouterLink>
        </li>
      </ol>

      <section class="choice-section" aria-labelledby="dataset-choices">
        <h2 id="dataset-choices">Dataset choices</h2>
        <p v-if="choicesLoading">Loading definitions…</p>
        <ul v-else class="choice-list">
          <li v-for="experiment in projectStore.currentProject?.experiments ?? []" :key="experiment.id">
            <span>{{ experiment.name }}</span>
            <RouterLink :to="datasetLink(experiment.id)">Default</RouterLink>
            <RouterLink
              v-for="view in datasetViews[experiment.id] ?? []"
              :key="view.id"
              :to="datasetLink(experiment.id, view.id)"
            >{{ view.name }}</RouterLink>
          </li>
        </ul>
        <p v-if="choiceError" role="alert" class="error-note">{{ choiceError }}</p>
      </section>

      <section class="choice-section" aria-labelledby="workflow-choices">
        <h2 id="workflow-choices">Workflow choices</h2>
        <ul class="choice-list">
          <li v-for="workflow in analysisWorkflows" :key="workflow.id">
            <RouterLink :to="workflowLink(workflow.id)">{{ workflow.name }}</RouterLink>
          </li>
        </ul>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import WorkspacePageHeader from "@/components/workspace/WorkspacePageHeader.vue";
import { useRoute } from "vue-router";
import { useScopedRequest } from "@/composables/useScopedRequest";
import { navigationRegistry } from "@/navigation/workspace";
import MethodHelp from "@/components/MethodHelp.vue";
import { computed, onScopeDispose, ref, watch } from "vue";
import api from "@/api/client";
import { useProjectStore } from "@/stores/project";
import { availabilityDetail, availabilityState, useProjectProvenanceStore, type ProjectProvenanceRecord } from "@/stores/projectProvenance";
import { getErrorMessage } from "@/utils/errors";

interface DatasetViewChoice { id: number; name: string }

const projectStore = useProjectStore();
const store = useProjectProvenanceStore();
const route = useRoute();
const projectAdmissionError = ref("");
const projectRequests = useScopedRequest(() => [route.path, JSON.stringify(route.query.project ?? route.query.project_id)]);
watch(() => [route.query.project, route.query.project_id], async ([project, alias]) => {
  projectAdmissionError.value = "";
  const ticket = projectRequests.begin();
  const raw = project ?? alias;
  if (raw == null) {
    await projectStore.ensureProjectForBrowserTab({ signal: ticket.signal });
    return;
  }
  const id = typeof raw === "string" ? Number(raw) : NaN;
  if (!Number.isSafeInteger(id) || id < 1 || (project != null && alias != null && project !== alias)) {
    projectAdmissionError.value = "Project unavailable — invalid project link.";
    return;
  }
  const selected = await projectStore.fetchProject(id, { signal: ticket.signal });
  if (ticket.isCurrent() && !selected && projectStore.error) {
    projectAdmissionError.value = "Project unavailable — choose a project.";
  }
}, { immediate: true });
const summary = computed(() => store.projectId === projectStore.currentProjectId ? store.summary : null);
const analysisWorkflows = computed(() => projectStore.currentProject?.workflows.filter((workflow) => workflow.purpose === "analysis") ?? []);
const datasetViews = ref<Record<number, DatasetViewChoice[]>>({});
const choicesLoading = ref(false);
const choiceError = ref<string | null>(null);
let choiceGeneration = 0;

function datasetLink(experimentId: number, viewId?: number) {
  return { path: "/data", query: { tab: "my-dataset", experiment: String(experimentId), viewId: viewId == null ? "default" : String(viewId) } };
}

function workflowLink(workflowId: number) {
  return { path: "/workflow", query: { project_id: String(projectStore.currentProjectId), workflow_id: String(workflowId) } };
}

function recordLink(record: ProjectProvenanceRecord) {
  if ((record.kind === "source" || record.kind === "dataset") && record.experiment_id != null) {
    return datasetLink(record.experiment_id, record.dataset_view_id ?? undefined);
  }
  if (record.kind === "workflow" && typeof record.record_id === "number") return workflowLink(record.record_id);
  if (record.kind === "run" && typeof record.record_id === "number") return `/runs/${record.record_id}`;
  return record.destination;
}

async function refresh(): Promise<void> {
  const id = projectStore.currentProjectId;
  if (id == null) return;
  await Promise.all([store.refresh(id), loadChoices(id)]);
}

const releasePrimary = navigationRegistry.register("host", { primaryActions: [{
  id: "project.verify", scope: { pageId: "project", sectionId: "project.provenance" },
  label: "Verify all", accelerator: "CmdOrCtrl+Enter",
  available: ({ projectId }) => !projectAdmissionError.value && projectId != null && projectId === projectStore.currentProjectId,
  disabled: () => store.loading,
  execute: refresh,
}] });
onScopeDispose(releasePrimary);

async function loadChoices(projectId: number): Promise<void> {
  const generation = ++choiceGeneration;
  choicesLoading.value = true;
  choiceError.value = null;
  datasetViews.value = {};
  try {
    if (projectStore.currentProject?.id !== projectId) await projectStore.fetchProject(projectId);
    const experiments = projectStore.currentProject?.id === projectId ? projectStore.currentProject.experiments : [];
    const entries = await Promise.all(experiments.map(async (experiment) => {
      const response = await api.get<DatasetViewChoice[]>(`/experiments/${experiment.id}/dataset-views`);
      return [experiment.id, response.data] as const;
    }));
    if (generation === choiceGeneration) datasetViews.value = Object.fromEntries(entries);
  } catch (cause) {
    if (generation === choiceGeneration) choiceError.value = getErrorMessage(cause, "Dataset choices are unavailable.");
  } finally {
    if (generation === choiceGeneration) choicesLoading.value = false;
  }
}

watch(() => projectStore.currentProjectId, (id) => {
  if (id != null) void refresh();
  else { ++choiceGeneration; datasetViews.value = {}; }
}, { immediate: true });
</script>

<style scoped>
.provenance-page { max-width: 1100px; margin: 0 auto; padding: 24px; color: var(--ss-action-text); }
h1 { margin: 0; font-size: 1.8rem; }
h2 { margin: 0; font-size: 1rem; }
.scope-note, .choice-section p, .record-text p { color: var(--ss-text-muted); }
.record-list { list-style: none; padding: 0; display: grid; gap: 8px; }
.record-row { display: flex; gap: 14px; align-items: start; padding: 14px; border: 1px solid var(--ss-border); border-radius: 10px; background: var(--ss-surface); }
.record-light { flex: 0 0 14px; height: 14px; border-radius: 50%; margin-top: 3px; }
.status-healthy { background: var(--ss-success); }
.status-missing { background: var(--ss-border-strong); }
.status-faulty { background: var(--ss-danger); }
.record-text { min-width: 0; flex: 1; }
.record-text h2 small { margin-left: 8px; font-weight: 400; color: var(--ss-text-secondary); }
.record-text p { margin: 4px 0; font-size: .9rem; }
.record-text code { font-size: .75rem; overflow-wrap: anywhere; }
.package-versions { overflow-wrap: anywhere; }
.open-link, .choice-list a { color: var(--ss-action); }
.choice-section { margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--ss-border); }
.choice-list { display: grid; gap: 10px; padding-left: 22px; }
.choice-list li { display: flex; flex-wrap: wrap; gap: 12px; }
.error-note { color: var(--ss-danger); }
</style>
