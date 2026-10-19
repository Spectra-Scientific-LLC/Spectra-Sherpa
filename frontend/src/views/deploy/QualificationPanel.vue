<template>
  <section class="qualification-panel" :class="{ 'qualification-panel--embedded': headingless }">
    <h3 v-if="!headingless">Analytical qualification</h3>
    <MethodHelp topic="qualification" label="Analytical qualification" />
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="error" type="button" class="p-button p-button-sm p-button-outlined" :disabled="busy" @click="loadHistory">Retry</button>
    <button type="button" class="p-button p-button-sm p-button-outlined" :disabled="!records.length || busy" @click="download">Export complete evidence history</button>
    <p v-if="!records.length && !busy">No qualification assessment is retained for this workflow.</p>
    <article v-for="record in records" :key="record.record_digest">
      <h4>{{ record.kind === 'assessment' ? record.payload.assessment : record.payload.decision }}</h4>
      <p>{{ record.record_digest }}</p>
      <p v-if="record.kind === 'assessment'">Population: {{ record.payload.context?.intended_population }} · Policy: {{ record.payload.policy?.policy_name }} {{ record.payload.policy?.policy_version }}</p>
      <ul v-if="record.kind === 'assessment'">
        <li v-for="criterion in record.payload.criteria" :key="criterion.name">{{ criterion.name }}: {{ criterion.state }} — {{ criterion.detail }}</li>
      </ul>
      <p v-if="record.payload.calculation?.independence">
        Recorded identity comparison: {{ record.payload.calculation.independence.identity_separation_status }}.
        Sampling independence: {{ record.payload.calculation.independence.sampling_independence_status }}.
        {{ record.payload.calculation.independence.limitation }}
      </p>
      <details><summary>Exact retained evidence and assumptions</summary><pre>{{ JSON.stringify(record.payload, null, 2) }}</pre></details>
      <button v-if="record.kind === 'assessment'" type="button" class="p-button p-button-sm p-button-outlined" :disabled="busy" @click="selectReview(record)">Review this assessment</button>
    </article>
    <fieldset v-if="review">
      <legend>Human decision for {{ review.record_digest }}</legend>
      <p>Intended use: {{ review.payload.context.intended_use }}</p>
      <p>Population: {{ review.payload.context.intended_population }}</p>
      <p>Instrument: {{ review.payload.context.instrument_id || 'Unavailable' }}</p>
      <label><input v-model="acceptContext" type="checkbox" /> I reviewed this exact policy, intended use, reference method and instrument assumptions.</label>
      <label>Review reason <textarea v-model="reason" /></label>
      <button type="button" class="p-button p-button-sm p-button-outlined" :disabled="busy || !acceptContext || !reason.trim() || review.payload.assessment !== 'criteria_met'" @click="decide('accepted_under_declared_policy')">Accept under declared policy</button>
      <button type="button" class="p-button p-button-sm p-button-outlined" :disabled="busy || !reason.trim()" @click="decide('rejected')">Reject</button>
      <button type="button" class="p-button p-button-sm p-button-outlined" :disabled="busy || !reason.trim()" @click="decide('pending')">Record pending review</button>
    </fieldset>
    <details v-if="canonicalArtifactId">
      <summary>Assess an independent validation cohort</summary>
      <p>Prepare a laboratory policy below, or load an existing policy under Advanced.</p>
      <label>Dataset <select v-model="experimentId" @change="loadFiles"><option :value="null">Select dataset</option><option v-for="experiment in experiments" :key="experiment.id" :value="experiment.id">{{ experiment.name }}</option></select></label>
      <label>Reference file <select v-model="fileId"><option :value="null">Select file</option><option v-for="file in files" :key="file.id" :value="file.id">{{ file.file_path }} ({{ file.stage }})</option></select></label>
      <label>Asset identity, if needed <input v-model="assetId" /></label>
      <QualificationPolicyForm :key="canonicalArtifactId" @prepared="policyText = $event.policy; contextText = $event.context" @changed="policyText = ''; contextText = ''" />
      <details><summary>Advanced: policy JSON and additional evidence</summary>
      <label>Frozen acceptance policy JSON <textarea v-model="policyText" rows="8" /></label>
      <label>Intended-use context and declarations JSON <textarea v-model="contextText" rows="8" /></label>
      <label>Optional recorded independence evidence JSON <textarea v-model="independenceText" rows="5" placeholder="Specimen/batch IDs and their namespaces; blank retains declared or unknown status" /></label>
      <label>Optional interval calibration record JSON <textarea v-model="intervalText" rows="3" placeholder="Blank means interval evidence unavailable" /></label>
      </details>
      <label><input v-model="allowExclusions" type="checkbox" /> Explicitly exclude missing reference rows and retain their identities and reasons. Infinite references and nonfinite predictors still refuse.</label>
      <button type="button" class="p-button p-button-sm p-button-outlined" :disabled="busy || !fileId || !policyText.trim() || !contextText.trim()" @click="assess">Execute frozen application and assess</button>
    </details>
    <p v-else>Import a canonical PLS application to run an assessment.</p>
  </section>
</template>
<script setup lang="ts">
import MethodHelp from "@/components/MethodHelp.vue";
import { ref, watch, onMounted, onBeforeUnmount } from "vue";
import api from "@/api/client";
import QualificationPolicyForm from "@/components/QualificationPolicyForm.vue";
import type { ExperimentSummary, ExperimentFile } from "@/types";
type RecordEntry = { kind: string; record_digest: string; context_digest: string | null; payload: Record<string, any> };
// `headingless` when a parent disclosure already names the section.
const props = defineProps<{ workflowId: number; canonicalArtifactId?: number | null; projectId?: number | null; headingless?: boolean }>();
const records = ref<RecordEntry[]>([]);
const review = ref<RecordEntry | null>(null);
const acceptContext = ref(false);
const reason = ref("");
const error = ref("");
const busy = ref(false);
const experiments = ref<ExperimentSummary[]>([]);
const files = ref<ExperimentFile[]>([]);
const experimentId = ref<number | null>(null);
const fileId = ref<number | null>(null);
const assetId = ref("");
const policyText = ref("");
const contextText = ref("");
const intervalText = ref("");
const independenceText = ref("");
const allowExclusions = ref(false);
let timer: ReturnType<typeof setInterval> | null = null;
const syncEvidence = () => { if (!busy.value && !document.hidden) void loadHistory(); };
onMounted(() => { window.addEventListener("focus", syncEvidence); timer = setInterval(syncEvidence, 15000); });
onBeforeUnmount(() => { window.removeEventListener("focus", syncEvidence); if (timer) clearInterval(timer); });
let generation = 0;
let fileRequest = 0;
let historyRequest = 0;
onBeforeUnmount(() => { generation += 1; fileRequest += 1; });
function fail(e: unknown) { const value = e as {response?: {data?: {detail?: unknown}}; message?: string}; error.value = String(value.response?.data?.detail || value.message || e); }
async function loadHistory() {
  const current = generation;
  const request = ++historyRequest;
  try { const response = await api.get(`/deploy/workflows/${props.workflowId}/qualification`); if (current === generation && request === historyRequest) { records.value = response.data.records; error.value = ""; } }
  catch (e) { if (current === generation) fail(e); }
}
function selectReview(value: RecordEntry) { review.value = value; acceptContext.value = false; reason.value = ""; }
async function decide(decision: string) {
  if (!review.value || busy.value) return;
  const current = generation;
  busy.value = true; error.value = "";
  try {
    await api.post(`/deploy/workflows/${props.workflowId}/qualification/decisions`, { dossier_digest: review.value.record_digest,
      decision, reason: reason.value.trim(), accepted_context_digest: acceptContext.value ? review.value.context_digest : null });
    if (current !== generation) return;
    review.value = null; await loadHistory();
  } catch (e) { if (current === generation) fail(e); }
  finally { if (current === generation) busy.value = false; }
}
async function loadFiles() {
  const current = ++fileRequest; files.value = []; fileId.value = null;
  if (!experimentId.value) return;
  try { const response = await api.get(`/experiments/${experimentId.value}/files`); if (current === fileRequest) files.value = response.data; }
  catch (e) { if (current === fileRequest) fail(e); }
}
async function assess() {
  if (busy.value) return;
  const file = files.value.find(item => item.id === fileId.value); if (!file) return;
  const current = generation; busy.value = true; error.value = "";
  try {
    await api.post(`/deploy/workflows/${props.workflowId}/qualification`, { canonical_artifact_id: props.canonicalArtifactId,
      experiment_id: experimentId.value, file_id: file.id, stage: file.stage, asset_id: assetId.value.trim() || null,
      policy: JSON.parse(policyText.value), context: JSON.parse(contextText.value), allow_missing_reference_exclusion: allowExclusions.value,
      independence_evidence: independenceText.value.trim() ? JSON.parse(independenceText.value) : null,
      uncertainty_record: intervalText.value.trim() ? JSON.parse(intervalText.value) : null });
    if (current === generation) await loadHistory();
  } catch (e) { if (current === generation) fail(e); }
  finally { if (current === generation) busy.value = false; }
}
function download() {
  const url = URL.createObjectURL(new Blob([JSON.stringify({schema_version: "spectrasherpa.qualification-history/1",
    workflow_id: props.workflowId, scope: "Historical declared-use evidence. Imported calculations and approvals are assertions, not authenticated certification.", records: records.value}, null, 2)], {type: "application/json"}));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = `qualification-workflow-${props.workflowId}.json`; anchor.click(); URL.revokeObjectURL(url);
}
watch(() => [props.workflowId, props.canonicalArtifactId, props.projectId], async () => {
  const current = ++generation; fileRequest += 1; records.value = []; review.value = null; acceptContext.value = false;
  reason.value = error.value = ""; busy.value = false; files.value = []; experiments.value = []; experimentId.value = fileId.value = null;
  assetId.value = "";
  policyText.value = contextText.value = intervalText.value = independenceText.value = ""; allowExclusions.value = false;
  await loadHistory();
  if (!props.projectId || current !== generation) return;
  try { const response = await api.get("/experiments", {params: {project_id: props.projectId, limit: 200}}); if (current === generation) experiments.value = response.data; }
  catch (e) { if (current === generation) fail(e); }
}, { immediate: true });
</script>
<style scoped>
.qualification-panel { display: flex; flex-direction: column; align-items: flex-start; gap: .75rem; margin: 1rem 0; padding: 1rem; border: 1px solid var(--surface-border); border-radius: 8px; }
.qualification-panel--embedded { margin: .75rem 0 0; padding: 0; border: 0; }
.qualification-panel > * { margin: 0; }
.qualification-panel p { line-height: 1.5; color: var(--text-color-secondary); }
h3 { font-size: 1rem; }
label { display: block; margin: .6rem 0; }
textarea { display: block; width: 100%; }
pre { overflow: auto; max-height: 24rem; white-space: pre-wrap; }
article, fieldset, details { align-self: stretch; }
article { border-top: 1px solid var(--surface-border); padding-top: .75rem; }
article button, fieldset button, details button { margin: .25rem .5rem .25rem 0; }
</style>
