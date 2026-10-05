<template>
  <fieldset class="uncertainty-editor">
    <legend>Prediction intervals (optional)</legend>
    <p>Point predictions only unless you explicitly select a calibration record for this exact pipeline.</p>
    <label>Import interval record <input type="file" accept=".json,application/json" :disabled="busy" @change="importRecord" /></label>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="error" type="button" @click="clearRecord">Clear failed selection; use point predictions only</button>
    <div v-if="modelValue">
      <p>Selected record: {{ modelValue.record_digest }}</p>
      <pre>{{ JSON.stringify(modelValue.reference_method, null, 2) }}</pre>
      <p>Intended population: {{ modelValue.intended_population }}</p>
      <label><input v-model="populationAccepted" type="checkbox" :disabled="busy || !!error" />
        I declare that incoming specimens belong to this population and reference measurement basis.
        Compatibility is declared, not verified.
      </label>
      <p>Per-response marginal level: {{ 100 * (1 - Number(modelValue.alpha)) }}%. Independence and exchangeability are declared; this is not laboratory qualification.</p>
      <button type="button" @click="downloadRecord">Export selected record</button>
      <button type="button" @click="clearRecord">Use point predictions only</button>
    </div>
    <details v-if="canonicalArtifactId && workflowId">
      <summary>Calibrate from a separate reference dataset</summary>
      <p>Use one row per distinct specimen with explicit sample labels and retained target values/units. Average repeat measurements first. This dataset must not have been used to fit or select the model.</p>
      <label>Dataset
        <select v-model="experimentId" @change="loadFiles">
          <option :value="null">Select dataset</option>
          <option v-for="experiment in experiments" :key="experiment.id" :value="experiment.id">{{ experiment.name }}</option>
        </select>
      </label>
      <label>Reference file
        <select v-model="fileId">
          <option :value="null">Select file</option>
          <option v-for="file in files" :key="file.id" :value="file.id">{{ file.file_path }} ({{ file.stage }})</option>
        </select>
      </label>
      <label>Asset identity, if file contains several assets <input v-model="assetId" /></label>
      <label>Specimen ID namespace <input v-model="namespace" placeholder="Laboratory specimen register" /></label>
      <label>Reference method <input v-model="method" /></label>
      <label>Reference method version <input v-model="methodVersion" /></label>
      <label>Measurements averaged per reference label <input v-model="replicates" inputmode="numeric" /></label>
      <label>Optional pooled reference precision JSON <textarea v-model="precisionText" placeholder="Blank means unavailable; never estimated from prediction residuals" /></label>
      <label>Miscoverage alpha (e.g. 0.1 for 90%) <input v-model="alpha" inputmode="decimal" /></label>
      <label>Intended population <textarea v-model="population" /></label>
      <label><input type="checkbox" v-model="frozen" /> The complete prediction pipeline was frozen before calibration.</label>
      <label><input type="checkbox" v-model="independent" /> No calibration specimen was used to fit or select this model; rows represent distinct specimens.</label>
      <label><input type="checkbox" v-model="exchangeable" /> Calibration and future reference measurements are exchangeable for this intended population and method.</label>
      <button type="button" :disabled="busy || !frozen || !independent || !exchangeable || !fileId" @click="calibrate">{{ busy ? 'Calibrating…' : 'Calibrate and select record' }}</button>
    </details>
  </fieldset>
</template>

<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from "vue";
import api from "@/api/client";
import type { ExperimentSummary, ExperimentFile } from "@/types";

const props = defineProps<{
  modelValue: Record<string, unknown> | null;
  workflowId?: number;
  canonicalArtifactId?: number;
  projectId?: number | null;
}>();
const emit = defineEmits<{
  (event: "update:modelValue", value: Record<string, unknown> | null): void;
  (event: "valid", value: boolean): void;
}>();
const populationAccepted = ref(false);
const error = ref("");
const busy = ref(false);
watch(() => props.modelValue, () => { populationAccepted.value = false; }, { flush: "sync" });
watch([() => props.modelValue, populationAccepted, error, busy], () => {
  emit("valid", !error.value && !busy.value && (props.modelValue === null || populationAccepted.value));
}, { immediate: true });
const experiments = ref<ExperimentSummary[]>([]);
const files = ref<ExperimentFile[]>([]);
const experimentId = ref<number | null>(null);
const fileId = ref<number | null>(null);
const assetId = ref("");
const namespace = ref("");
const method = ref("");
const methodVersion = ref("");
const replicates = ref("1");
const precisionText = ref("");
const alpha = ref("0.1");
const population = ref("");
const frozen = ref(false);
const independent = ref(false);
const exchangeable = ref(false);
let generation = 0;
let fileRequest = 0;
onBeforeUnmount(() => { generation += 1; fileRequest += 1; });
function fail(reason: unknown) {
  const e = reason as { response?: { data?: { detail?: unknown } }; message?: string };
  error.value = String(e?.response?.data?.detail || e?.message || reason);
  emit("valid", false);
}
function clearRecord() {
  generation += 1;
  busy.value = false;
  error.value = "";
  emit("update:modelValue", null);
  emit("valid", true);
}
async function importRecord(event: Event) {
  if (busy.value) return;
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  const current = ++generation;
  emit("valid", false);
  try {
    if (file.size > 128 * 1024) throw new Error("Interval record exceeds 128 KiB");
    const value = JSON.parse(await file.text());
    if (current !== generation) return;
    if (value?.schema_version !== "spectrasherpa.prediction-uncertainty/1" || typeof value.record_digest !== "string")
      throw new Error("Not a prediction interval calibration record");
    emit("update:modelValue", value);
    error.value = "";
    populationAccepted.value = false;
    emit("valid", false); // Require a fresh declaration for each selected record.
  } catch (e) { if (current === generation) fail(e); }
}
function downloadRecord() {
  if (!props.modelValue) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(props.modelValue, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `prediction-intervals-${String(props.modelValue.record_digest).slice(0, 12)}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}
async function loadFiles() {
  const current = ++fileRequest;
  fileId.value = null;
  files.value = [];
  if (!experimentId.value) return;
  try {
    const response = await api.get<ExperimentFile[]>(`/experiments/${experimentId.value}/files`);
    if (current === fileRequest) files.value = response.data;
  } catch (e) { if (current === fileRequest) fail(e); }
}
async function calibrate() {
  const file = files.value.find(item => item.id === fileId.value);
  if (!file || !props.workflowId || !props.canonicalArtifactId) return;
  const current = ++generation;
  busy.value = true;
  emit("valid", false);
  try {
    const response = await api.post<{record: Record<string, unknown>}>(`/deploy/workflows/${props.workflowId}/uncertainty/calibrate`, {
      canonical_artifact_id: props.canonicalArtifactId, experiment_id: experimentId.value,
      file_id: file.id, stage: file.stage, asset_id: assetId.value.trim() || null,
      specimen_namespace: namespace.value.trim(), reference_method_id: method.value.trim(),
      reference_method_version: methodVersion.value.trim(), measurements_per_label: Number(replicates.value),
      measurement_basis: Number(replicates.value) === 1 ? "single_measurement" : "replicate_mean",
      reference_precision: precisionText.value.trim() ? JSON.parse(precisionText.value) : null,
      alpha: Number(alpha.value), intended_population: population.value.trim(),
      declarations: { model_frozen_before_calibration: frozen.value,
        calibration_not_used_for_fit_or_selection: independent.value, exchangeability_declared: exchangeable.value },
    });
    if (current !== generation) return;
    emit("update:modelValue", response.data.record);
    populationAccepted.value = false;
    emit("valid", false);
    error.value = "";
  } catch (e) { if (current === generation) fail(e); }
  finally { if (current === generation) busy.value = false; }
}
watch(() => [props.projectId, props.workflowId, props.canonicalArtifactId], async () => {
  clearRecord();
  fileRequest += 1;
  experiments.value = [];
  files.value = [];
  experimentId.value = null;
  fileId.value = null;
  frozen.value = independent.value = exchangeable.value = false;
  if (!props.projectId) return;
  const current = generation;
  try {
    const response = await api.get<ExperimentSummary[]>("/experiments", {params: {project_id: props.projectId, limit: 200}});
    if (current === generation) experiments.value = response.data;
  } catch (e) { if (current === generation) fail(e); }
}, { immediate: true });
</script>

<style scoped>
.uncertainty-editor { margin: 1rem 0; min-width: 0; }
label { display: block; margin: .65rem 0; }
input:not([type=checkbox]), textarea, select { display: block; max-width: 100%; width: 100%; }
p { overflow-wrap: anywhere; }
[role=alert] { color: var(--red-500); }
button { margin-right: .5rem; }
</style>
