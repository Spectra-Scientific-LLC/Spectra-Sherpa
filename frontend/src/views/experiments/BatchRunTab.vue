<template>
  <div class="batch-run-tab">
    <fieldset :disabled="submitting || loading">
      <legend>Execution mode <MethodHelp topic="batch" label="Batch execution modes" /></legend>
      <label><input v-model="mode" type="radio" value="apply_model" /> Apply trained model — no refit</label>
      <label><input v-model="mode" type="radio" value="run_workflow" /> Run workflow — train/evaluate</label>
    </fieldset>
    <p v-if="error" role="alert" class="batch-error">{{ error }}</p>
    <p v-if="loading" role="status">Loading project workflows and dataset definitions…</p>
    <div class="batch-selections">
      <fieldset :disabled="submitting || loading">
        <legend>Workflows</legend>
        <div v-for="workflow in availableWorkflows" :key="workflow.id" class="selection-item">
          <label><input v-model="selectedWorkflowIds" type="checkbox" :value="workflow.id" /> {{ workflow.name }}</label>
          <div v-if="mode === 'apply_model' && selectedWorkflowIds.includes(workflow.id)" class="model-choices">
            <label v-for="artifact in modelsFor(workflow.id)" :key="artifact.artifact_uid">
              <input v-model="selectedArtifactUids" type="checkbox" :value="artifact.artifact_uid" />
              {{ artifact.display_name || artifact.name }} <small>{{ modelContext(artifact) }}</small>
            </label>
            <small v-if="!modelsFor(workflow.id).length">No fitted model is available. Use train/evaluate first.</small>
          </div>
        </div>
        <p v-if="!loading && !availableWorkflows.length">No eligible workflows for this mode. Train a model first, or choose train/evaluate.</p>
      </fieldset>
      <fieldset :disabled="submitting || loading">
        <legend>Dataset definitions</legend>
        <label v-for="definition in definitions" :key="definition.key" class="selection-item">
          <input v-model="selectedDefinitionKeys" type="checkbox" :value="definition.key" /> {{ definition.label }}
        </label>
        <p v-if="!loading && !definitions.length">No dataset definitions in this project.</p>
      </fieldset>
    </div>
    <section aria-label="Batch combinations" class="batch-combinations">
      <h4>Combinations ({{ combinations.length }})</h4>
      <p v-if="!combinations.length" class="batch-hint">Select a workflow and dataset definition.</p>
      <p v-if="checkedCombinationCount > 32" role="alert">Select at most 32 combinations for one batch. Deselect combinations below.</p>
      <ul v-if="combinations.length">
        <li v-for="(combination, index) in combinations" :key="combination.key">
          <label>
            <input type="checkbox" :checked="!excluded.includes(combination.key) && checks[index]?.compatible !== false" :disabled="submitting || checking || checks[index]?.compatible === false"
              @change="toggleCombination(combination.key)" />
            {{ combination.label }}
          </label>
          <small v-if="!checks[index]">Check compatibility before running.</small>
          <small v-else-if="!checks[index]?.compatible" class="batch-error">Unavailable: {{ checks[index]?.reason }}</small>
          <small v-else-if="mode === 'apply_model' && !checks[index]?.metadata?.accuracy_available">Compatible — predictions only; accuracy statistics unavailable.</small>
          <small v-else>Compatible — {{ checks[index]?.metadata?.n_included_samples }} included samples.</small>
          <label
            v-if="mode === 'apply_model' && (checks[index]?.code === 'legacy_ack_required' || acknowledgedLegacyKeys.includes(combination.key))"
            class="legacy-ack">
            <input type="checkbox" :checked="acknowledgedLegacyKeys.includes(combination.key)" :disabled="submitting || checking"
              @change="toggleLegacyAcknowledgement(combination.key)" />
            I acknowledge exploratory use: this older model has no fitted signal identity. I checked that the file's signal units and measurement mode match the training data; this does not verify them.
          </label>
        </li>
      </ul>
      <div class="batch-actions">
        <Button label="Check compatibility" class="p-button-text p-button-sm" :loading="checking" :disabled="!canCheck" @click="checkCompatibility" />
        <Button label="Run selected combinations" class="p-button-sm" icon="pi pi-play" :loading="submitting" :disabled="!canSubmit" @click="handleSubmit" />
      </div>
      <p v-if="progress" role="status">{{ progress }}</p>
    </section>
    <PrivateBatchUpload v-if="mode === 'apply_model' && activeArtifactUids.length === 1"
      :artifact-uid="activeArtifactUids[0]!" @completed="emit('completed', $event)" />
  </div>
</template>

<script setup lang="ts">
import MethodHelp from "@/components/MethodHelp.vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import Button from "primevue/button";
import { useToast } from "primevue/usetoast";
import api from "@/api/client";
import PrivateBatchUpload from "./PrivateBatchUpload.vue";
import { useProjectStore } from "@/stores/project";
import type { ExecutionRunSummary } from "@/types";
import { getErrorMessage } from "@/utils/errors";

interface Artifact { artifact_uid: string; name: string; display_name?: string | null; workflow_id?: number | null;
  source_run_id?: number | null; n_components?: number | null; created_at?: string | null }
interface Workflow { id: number; name: string; purpose?: string }
interface DatasetChoice { id: number; name: string }
interface VerificationResponse { batch_id: string; results: { run_id: number; status: string }[] }
interface Definition { key: string; label: string; experimentId: number; viewId: number | null }
interface Check { compatible: boolean; receipt?: string; reason?: string; code?: string;
  metadata?: { accuracy_available?: boolean; n_included_samples: number } }
const props = withDefaults(defineProps<{ artifacts?: Artifact[] }>(), { artifacts: () => [] });
const emit = defineEmits<{ completed: [run: ExecutionRunSummary] }>();
const projectStore = useProjectStore();
const toast = useToast();
const mode = ref<"apply_model" | "run_workflow">("apply_model");
const workflows = ref<Workflow[]>([]);
const definitions = ref<Definition[]>([]);
const selectedWorkflowIds = ref<number[]>([]);
const selectedDefinitionKeys = ref<string[]>([]);
const selectedArtifactUids = ref<string[]>([]);
const excluded = ref<string[]>([]);
const acknowledgedLegacyKeys = ref<string[]>([]);
const checks = ref<Check[]>([]);
const loading = ref(false);
const checking = ref(false);
const submitting = ref(false);
const error = ref("");
const progress = ref("");
let generation = 0;
let inventoryGeneration = 0;
onBeforeUnmount(() => { ++generation; ++inventoryGeneration; });
const modelContext = (model: Artifact) => [
  model.source_run_id != null ? `Run #${model.source_run_id}` : null,
  model.n_components != null ? `${model.n_components} LV` : null,
  model.created_at && Number.isFinite(Date.parse(model.created_at)) ? new Date(model.created_at).toLocaleString() : null,
].filter(Boolean).join(" · ");
const modelsFor = (id: number) => props.artifacts.filter(model => model.workflow_id === id);
const availableWorkflows = computed(() => workflows.value.filter(workflow =>
  workflow.purpose !== "managed_candidate_authority"
  && (mode.value === "run_workflow" || modelsFor(workflow.id).length > 0),
));
const activeArtifactUids = computed(() => props.artifacts.filter(model =>
  selectedWorkflowIds.value.includes(model.workflow_id ?? -1) && selectedArtifactUids.value.includes(model.artifact_uid),
).map(model => model.artifact_uid));
const combinations = computed(() => availableWorkflows.value.filter(w => selectedWorkflowIds.value.includes(w.id)).flatMap(workflow => {
  const models = mode.value === "apply_model"
    ? modelsFor(workflow.id).filter(model => selectedArtifactUids.value.includes(model.artifact_uid)) : [];
  const choices: (Artifact | null)[] = mode.value === "run_workflow" ? [null] : models;
  return choices.flatMap(model => definitions.value.filter(d => selectedDefinitionKeys.value.includes(d.key)).map(definition => ({
    key: workflow.id + ":" + (model?.artifact_uid ?? "workflow") + ":" + definition.key,
    label: workflow.name + (model ? " / " + (model.display_name || model.name) : "") + " × " + definition.label,
    payload: { workflow_id: workflow.id, artifact_uid: model?.artifact_uid ?? null,
      dataset: { experiment_id: definition.experimentId }, dataset_view_id: definition.viewId },
  })));
}));
const checkedCombinationCount = computed(() => combinations.value.filter(pair => !excluded.value.includes(pair.key)).length);
const pairWithAcknowledgement = (pair: (typeof combinations.value)[number]) => ({
  ...pair.payload,
  acknowledge_legacy_input_uncertainty: acknowledgedLegacyKeys.value.includes(pair.key),
});
const canCheck = computed(() => !loading.value && !checking.value && !submitting.value &&
  checkedCombinationCount.value > 0 && checkedCombinationCount.value <= 32);
const selectedPairs = computed(() => combinations.value.flatMap((pair, index) =>
  checks.value[index]?.compatible && !excluded.value.includes(pair.key)
    ? [{ ...pairWithAcknowledgement(pair), receipt: checks.value[index]!.receipt }] : []));
const canSubmit = computed(() => canCheck.value && selectedPairs.value.length > 0);
watch([mode, combinations], () => {
  ++generation; checks.value = []; excluded.value = []; acknowledgedLegacyKeys.value = [];
  checking.value = false; progress.value = "";
}, { flush: "sync" });

watch(() => projectStore.currentProjectId, async projectId => {
  const request = ++inventoryGeneration;
  ++generation;
  workflows.value = []; definitions.value = []; selectedWorkflowIds.value = [];
  selectedDefinitionKeys.value = []; selectedArtifactUids.value = []; error.value = "";
  loading.value = true;
  try {
    if (projectId == null) return;
    const [workflowResponse, datasetResponse] = await Promise.all([
      api.get<Workflow[]>("/workflows", { params: { project_id: projectId, limit: 200 } }),
      api.get<DatasetChoice[]>("/experiments", { params: { project_id: projectId } }),
    ]);
    const inventories = await Promise.all(datasetResponse.data.map(async dataset => {
      const { data } = await api.get<DatasetChoice[]>(`/experiments/${dataset.id}/dataset-views`);
      if (!Array.isArray(data)) throw new Error("Saved dataset definitions are unavailable.");
      return [{ key: dataset.id + ":default", label: dataset.name + " — Default", experimentId: dataset.id, viewId: null },
        ...data.map(view => ({ key: dataset.id + ":" + view.id, label: dataset.name + " — " + view.name,
          experimentId: dataset.id, viewId: view.id }))];
    }));
    if (request !== inventoryGeneration) return;
    workflows.value = workflowResponse.data;
    definitions.value = inventories.flat();
  } catch (err) {
    if (request === inventoryGeneration) error.value = getErrorMessage(err, "Could not load Batch choices.");
  } finally { if (request === inventoryGeneration) loading.value = false; }
}, { immediate: true });

function toggleCombination(key: string) {
  excluded.value = excluded.value.includes(key) ? excluded.value.filter(value => value !== key) : [...excluded.value, key];
}
function toggleLegacyAcknowledgement(key: string) {
  acknowledgedLegacyKeys.value = acknowledgedLegacyKeys.value.includes(key)
    ? acknowledgedLegacyKeys.value.filter(value => value !== key)
    : [...acknowledgedLegacyKeys.value, key];
  ++generation;
  checks.value = [];
  progress.value = "Check compatibility again after changing the legacy-model acknowledgement.";
}
async function checkCompatibility() {
  if (!canCheck.value) return;
  const request = ++generation;
  checking.value = true; checks.value = []; error.value = "";
  const selected = combinations.value.map((pair, index) => ({ pair, index })).filter(({ pair }) => !excluded.value.includes(pair.key));
  try {
    const { data } = await api.post<{ pairs: Check[] }>("/runs/verification/preflight", {
      project_id: projectStore.currentProjectId, mode: mode.value,
      pairs: selected.map(({ pair }) => pairWithAcknowledgement(pair)),
    });
    if (request === generation) {
      const mapped: Check[] = [];
      selected.forEach(({ index }, resultIndex) => { if (data.pairs[resultIndex]) mapped[index] = data.pairs[resultIndex]!; });
      checks.value = mapped;
    }
  } catch (err) {
    if (request === generation) error.value = getErrorMessage(err, "Batch compatibility check failed.");
  } finally { if (request === generation) checking.value = false; }
}
async function handleSubmit() {
  if (!canSubmit.value) return;
  submitting.value = true; error.value = "";
  progress.value = "Running " + selectedPairs.value.length + " combinations. Each result will appear in Run History.";
  const projectId = projectStore.currentProjectId;
  const request = generation;
  try {
    const { data } = await api.post<VerificationResponse>("/runs/verification", {
      project_id: projectId, mode: mode.value, pairs: selectedPairs.value,
    }, { timeout: 0 });
    if (request !== generation || projectId !== projectStore.currentProjectId) return;
    progress.value = "Batch " + data.batch_id + ": " + data.results.length + " results saved in Run History.";
    const incomplete = data.results.filter(result => result.status !== "completed").length;
    toast.add({ severity: incomplete ? "warn" : "success", summary: incomplete ? "Batch needs review" : "Batch saved",
      detail: progress.value + (incomplete ? " " + incomplete + " combinations need review." : ""), life: 8000 });
    checks.value = [];
    const last = data.results[data.results.length - 1];
    if (last) {
      const result = await api.get<ExecutionRunSummary>(`/runs/${last.run_id}`, { params: { project_id: projectId } });
      if (request === generation) emit("completed", result.data);
    }
  } catch (err) {
    if (request === generation) {
      error.value = getErrorMessage(err, "Batch did not finish. Check Run History before retrying.");
      progress.value = "Check Run History before retrying; earlier combinations may already be saved.";
      checks.value = [];
    }
  } finally { submitting.value = false; }
}
</script>

<style scoped>
.batch-run-tab { display: flex; flex-direction: column; gap: 1rem; }
.batch-selections { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1rem; }
fieldset { border: 1px solid var(--surface-border); border-radius: 8px; padding: 1rem; }
label { display: flex; align-items: baseline; gap: .6rem; padding: .35rem 0; }
input { accent-color: var(--primary-color); }
.model-choices { padding-left: 1.5rem; }
small { display: block; color: var(--text-color-secondary); }
.batch-combinations ul { list-style: none; padding: 0; }
.batch-combinations li { padding: .6rem 0; border-bottom: 1px solid var(--surface-border); }
.batch-error { color: var(--red-600, var(--ss-danger)); }
.batch-actions { display: flex; flex-wrap: wrap; gap: .75rem; margin: .5rem 0; }
.batch-hint { color: var(--text-color-secondary); }
p { margin: .4rem 0; line-height: 1.5; }
</style>
