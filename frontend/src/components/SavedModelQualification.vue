<template>
  <details class="saved-qualification">
    <summary>Saved-model analytical qualification</summary>
    <MethodHelp path="chemometrics/validation-application/#qualification-and-prediction-intervals" label="Saved-model qualification" />
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="history">Current status: <strong>{{ history.status.state }}</strong> · {{ history.status.reason || history.status.intended_population || 'Review the retained evidence.' }}</p>
    <p v-if="history?.status.state === 'stale_for_selected_dataset'" role="note">This assessment concerns its named validation view. A decision here will not qualify the dataset currently selected in My Dataset.</p>
    <button type="button" :disabled="busy" @click="load">Refresh evidence</button>
    <button type="button" :disabled="!history?.records.length" @click="exportEvidence">Export full history</button>
    <label v-if="responseIdentity.units.length > 1">Response for Ask Sherpa
      <select v-model.number="advisorResponseIndex"><option v-for="(_unit, index) in responseIdentity.units" :key="index" :value="index">{{ responseIdentity.names?.[index] || `Response ${index + 1}` }}</option></select>
    </label>
    <button v-if="advisorAvailable" type="button" :disabled="!canAskAdvisor" @click="askAdvisor">Ask Sherpa about this qualification</button>
    <p v-if="advisorAvailable && history?.records.length && !canAskAdvisor" role="note">Refresh the exact model and named validation view before asking Sherpa about qualification.</p>
    <section v-if="history?.records.length" aria-label="Saved model qualification history">
      <article v-for="record in history.records" :key="record.record_digest">
        <h4>{{ record.kind === 'assessment' ? record.payload.assessment : record.payload.decision }}</h4>
        <p>{{ record.record_digest }} · view #{{ record.validation_view_id }}</p>
        <p v-if="record.kind === 'assessment'">{{ record.payload.context?.intended_population }} · {{ record.payload.policy?.policy_name }} {{ record.payload.policy?.policy_version }}</p>
      <template v-if="record.kind === 'assessment'">
        <p>Validation: {{ record.payload.calculation?.complete_rows ?? '—' }} complete specimens · fitted components {{ record.payload.calculation?.effective_fitted_components ?? '—' }}.</p>
        <p v-for="(response, index) in record.payload.calculation?.responses || []" :key="index">
          {{ record.payload.policy?.response_identity?.names?.[index] || `Response ${index + 1}` }}:
          RMSEP {{ response.metrics?.rmse ?? '—' }} (limit {{ record.payload.policy?.responses?.[index]?.max_rmsep ?? '—' }}),
          bias {{ response.metrics?.bias ?? '—' }} (absolute limit {{ record.payload.policy?.responses?.[index]?.max_absolute_bias ?? '—' }}).
        </p>
        <p>Observed interval coverage among screened available validation rows: {{ record.payload.calculation?.intervals?.observed_coverage_among_available?.join(', ') || 'Unavailable' }}
          ({{ record.payload.calculation?.intervals?.available_rows ?? '—' }}/{{ record.payload.calculation?.complete_rows ?? '—' }} rows available; no population coverage claim).
          Reference: {{ record.payload.context?.reference_method?.method_id || 'Unavailable' }} v{{ record.payload.context?.reference_method?.version || '—' }}.
          Instrument: {{ record.payload.context?.instrument_id || 'Unspecified' }}.</p>
        <p>Identity separation: {{ record.payload.calculation?.independence?.identity_separation_status || 'unavailable' }}.
          Sampling independence: {{ record.payload.calculation?.independence?.sampling_independence_status || 'unavailable' }}.</p>
        <ul><li v-for="criterion in record.payload.criteria || []" :key="criterion.name">{{ criterion.name }}: {{ criterion.state }} — {{ criterion.detail }}</li></ul>
        <p>Limits: {{ record.payload.limitations?.join('; ') || 'See exact evidence.' }}</p>
      </template>
        <details><summary>Exact evidence and assumptions</summary><pre>{{ JSON.stringify(record.payload, null, 2) }}</pre></details>
        <button v-if="canReview && record.kind === 'assessment' && record.record_digest === latestAssessment?.record_digest" type="button" @click="review = record; reason = ''; acceptedContext = false">Review current assessment</button>
      </article>
    </section>
    <fieldset v-if="review && canReview">
      <legend>Human decision for {{ review.record_digest }}</legend>
      <p>Intended use: {{ review.payload.context?.intended_use }}. Population: {{ review.payload.context?.intended_population }}.</p>
      <label><input v-model="acceptedContext" type="checkbox" /> I reviewed this exact intended use, population, policy, reference method, instrument and evidence.</label>
      <label>Reason <textarea v-model="reason" rows="3" /></label>
      <button type="button" :disabled="busy || !acceptedContext || !reason.trim() || review.payload.assessment !== 'criteria_met'" @click="decide('accepted_under_declared_policy')">Accept under declared policy</button>
      <button type="button" :disabled="busy || !reason.trim()" @click="decide('rejected')">Reject</button>
      <button type="button" :disabled="busy || !reason.trim()" @click="decide('pending')">Record pending review</button>
    </fieldset>
    <details>
      <summary>Assess an external validation cohort</summary>
      <p>Select an independent validation view and a frozen acceptance policy.</p>
      <label>External dataset
        <select v-model="experimentId" @change="loadViews"><option :value="null">Choose a dataset</option><option v-for="item in experiments" :key="item.id" :value="item.id">{{ item.name }}</option></select>
      </label>
      <label>Named view
        <select v-model="viewId"><option :value="null">Choose a named view</option><option v-for="view in views" :key="view.id" :value="view.id">{{ view.name }} · {{ view.selection_sha256.slice(0, 12) }}</option></select>
      </label>
      <p>Use the saved model response identity: {{ JSON.stringify(responseIdentity) }}. Enter laboratory thresholds and intended range before execution; the template leaves these blank and every chronology declaration false.</p>
      <QualificationPolicyForm :key="artifactUid" :response-identity="responseIdentity" @prepared="policyText = $event.policy; contextText = $event.context" @changed="policyText = ''; contextText = ''" />
      <details><summary>Advanced: policy JSON and additional evidence</summary>
      <button type="button" @click="fillTemplate">Load policy and context field template</button>
      <label>Frozen acceptance policy JSON <textarea v-model="policyText" rows="7" /></label>
      <label>Intended-use context and declarations JSON <textarea v-model="contextText" rows="7" /></label>
      <label>Optional recorded independence evidence JSON <textarea v-model="independenceText" rows="4" /></label>
      </details>
      <button type="button" :disabled="busy || !viewId || !policyText.trim() || !contextText.trim()" @click="assess">Execute saved model and assess</button>
    </details>
  </details>
</template>

<script setup lang="ts">
import MethodHelp from "@/components/MethodHelp.vue";
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import QualificationPolicyForm from './QualificationPolicyForm.vue';
import api from '@/api/client';
import { useAppConfig } from '@/composables/useAppConfig';
import { requestAdvisorPrompt } from '@/lib/advisorPromptActions';
import { downloadJson } from '@/utils/download';

type RecordEntry = {kind: string; record_digest: string; context_digest: string | null; validation_view_id: number; validation_view_digest: string; payload: Record<string, any>};
type History = {status: {state: string; reason?: string; intended_population?: string; dossier_digest?: string; decision_digest?: string; validation_view_digest?: string}; records: RecordEntry[]};
type Dataset = {id: number; name: string};
type View = {id: number; name: string; selection_sha256: string};
type ModelInspection = {manifest: {response_identity?: {names: string[] | null; units: (string | null)[]}}};
const props = defineProps<{artifactUid: string; projectId: number; workflowId?: number | null; runId?: number | null}>();
const { appConfig, appMode, isFeatureEnabled } = useAppConfig();
const emit = defineEmits<{changed: []}>();
const history = ref<History | null>(null);
const experiments = ref<Dataset[]>([]);
const views = ref<View[]>([]);
const experimentId = ref<number | null>(null);
const viewId = ref<number | null>(null);
const policyText = ref('');
const contextText = ref('');
const independenceText = ref('');
const review = ref<RecordEntry | null>(null);
const acceptedContext = ref(false);
const reason = ref('');
const responseIdentity = ref<{names: string[] | null; units: (string | null)[]}>({names: null, units: [null]});
const advisorResponseIndex = ref(0);
const busy = ref(false);
const error = ref('');
const latestAssessment = computed(() => [...(history.value?.records || [])].reverse().find(item => item.kind === 'assessment'));
const canReview = computed(() => !!history.value && ![
  'stale', 'current_source_unverified', 'unavailable',
].includes(history.value.status.state));
const advisorAvailable = computed(() => appMode.value !== 'local' && appConfig.value?.advisorContextPolicy !== 'receipt' && (isFeatureEnabled('sherpaAdvisor') || appConfig.value?.siteProfile === 'pro'));
const canAskAdvisor = computed(() => !!history.value && !!props.workflowId && !!props.runId && !!latestAssessment.value &&
  !!history.value.status.dossier_digest && !!history.value.status.validation_view_digest &&
  ['awaiting_review', 'accepted_under_declared_policy', 'rejected', 'pending', 'criteria_not_met', 'incomplete'].includes(history.value.status.state) &&
  advisorResponseIndex.value < responseIdentity.value.units.length && !busy.value);
function askAdvisor(): void {
  if (!canAskAdvisor.value || !advisorAvailable.value || !history.value || !props.workflowId || !props.runId) return;
  requestAdvisorPrompt('Explain this saved model’s current external qualification evidence. Distinguish calculated criteria, human acceptance, operational readiness, and limits of the validation cohort.', {
    diagnosticScope: {
      project_id: props.projectId, model_kind: 'qualification',
      response_label: responseIdentity.value.names?.[advisorResponseIndex.value] || null,
      reference: {
        kind: 'saved_model_qualification', artifact_uid: props.artifactUid,
        workflow_id: props.workflowId, run_id: props.runId,
        dossier_digest: history.value.status.dossier_digest!,
        validation_view_digest: history.value.status.validation_view_digest!,
        decision_digest: history.value.status.decision_digest || null,
        response_index: advisorResponseIndex.value,
      },
    },
  });
}
let generation = 0;
let historyRequest = 0;
let viewRequest = 0;
onBeforeUnmount(() => { generation++; historyRequest++; viewRequest++; });

function fail(value: unknown): void {
  const e = value as {response?: {data?: {detail?: unknown}}; message?: string};
  error.value = String(e.response?.data?.detail || e.message || value);
}
async function load(): Promise<void> {
  const current = generation;
  const request = ++historyRequest;
  history.value = null;
  review.value = null;
  acceptedContext.value = false;
  try {
    const response = await api.get<History>(`/models/${props.artifactUid}/qualification`);
    if (current === generation && request === historyRequest) { history.value = response.data; error.value = ''; }
  } catch (e) { if (current === generation && request === historyRequest) fail(e); }
}
async function loadViews(): Promise<void> {
  const current = generation;
  const request = ++viewRequest;
  const selected = experimentId.value;
  views.value = []; viewId.value = null;
  if (!selected) return;
  try {
    const response = await api.get<View[]>(`/experiments/${selected}/dataset-views`);
    if (current === generation && request === viewRequest && selected === experimentId.value) views.value = response.data;
  } catch (e) { if (current === generation && request === viewRequest) fail(e); }
}
function fillTemplate(): void {
  const identity = responseIdentity.value;
  policyText.value = JSON.stringify({
    schema_version: 'spectrasherpa.declared-qualification-policy/1', policy_name: 'REPLACE_WITH_FROZEN_POLICY', policy_version: '1',
    minimum_independent_specimens: null, minimum_specimens_per_component: null, response_identity: identity,
    responses: identity.units.map(() => ({max_rmsep: null, max_absolute_bias: null, intended_minimum: null, intended_maximum: null})),
    require_reference_precision: false, minimum_screening_available_fraction: null,
    minimum_interval_available_fraction: null, minimum_observed_interval_coverage: null,
    bias_confidence_level: 0.95, bootstrap_resamples: 200, random_seed: 0,
  }, null, 2);
  contextText.value = JSON.stringify({
    intended_use: 'REPLACE_WITH_INTENDED_USE', intended_population: 'REPLACE_WITH_POPULATION', specimen_namespace: 'REPLACE_WITH_SPECIMEN_REGISTER',
    reference_method: {method_id: 'REPLACE_WITH_LAB_METHOD', version: '1', response_identity: identity,
      measurement_basis: 'single_measurement', measurements_per_label: 1, precision: null},
    instrument_id: null, acquisition_configuration_digest: null, domain_coverage_evidence_digest: null,
    policy_frozen_before_validation: false, model_frozen_before_validation: false,
    specimens_not_used_for_fit_selection_or_interval_calibration: false, independent_specimen_sampling_declared: false,
    sampling_design: 'REPLACE_WITH_SAMPLING_DESIGN', evaluation_role: 'external_validation',
  }, null, 2);
}
async function assess(): Promise<void> {
  if (busy.value || !viewId.value) return;
  const current = generation; busy.value = true; error.value = '';
  try {
    await api.post(`/models/${props.artifactUid}/qualification`, {
      dataset_view_id: viewId.value,
      policy: JSON.parse(policyText.value), context: JSON.parse(contextText.value),
      independence_evidence: independenceText.value.trim() ? JSON.parse(independenceText.value) : null,
    });
    if (current === generation) { await load(); emit('changed'); }
  } catch (e) { if (current === generation) fail(e); }
  finally { if (current === generation) busy.value = false; }
}
async function decide(decision: 'accepted_under_declared_policy' | 'rejected' | 'pending'): Promise<void> {
  if (!review.value || busy.value) return;
  const current = generation; busy.value = true; error.value = '';
  try {
    await api.post(`/models/${props.artifactUid}/qualification/decisions`, {
      dossier_digest: review.value.record_digest, decision, reason: reason.value.trim(),
      accepted_context_digest: decision === 'accepted_under_declared_policy' && acceptedContext.value ? review.value.context_digest : null,
    });
    if (current === generation) { review.value = null; await load(); emit('changed'); }
  } catch (e) { if (current === generation) fail(e); }
  finally { if (current === generation) busy.value = false; }
}
function exportEvidence(): void {
  if (!history.value) return;
  downloadJson({schema_version: 'spectrasherpa.saved-model-qualification-history/1', artifact_uid: props.artifactUid,
    claim_scope: 'Server-retained declared-use evidence and operator assertions; no regulatory certification implied.',
    ...history.value}, `saved-model-${props.artifactUid}-qualification.json`);
}
watch(() => [props.artifactUid, props.projectId], async () => {
  const current = ++generation;
  historyRequest++; viewRequest++;
  history.value = null; experiments.value = []; views.value = []; experimentId.value = viewId.value = null;
  advisorResponseIndex.value = 0;
  review.value = null; error.value = ''; busy.value = false;
  await load();
  if (current !== generation) return;
  try {
    const [datasets, inspection] = await Promise.all([
      api.get<Dataset[]>('/experiments', {params: {project_id: props.projectId, limit: 200}}),
      api.get<ModelInspection>(`/models/${props.artifactUid}/inspect`),
    ]);
    if (current === generation) {
      experiments.value = datasets.data;
      responseIdentity.value = inspection.data.manifest.response_identity || {names: null, units: [null]};
    }
  } catch (e) { if (current === generation) fail(e); }
}, {immediate: true});
</script>

<style scoped>
.saved-qualification { border: 1px solid var(--surface-border); padding: 1rem; margin: 1rem 0; }
.saved-qualification p { color: var(--text-color-secondary); }
.saved-qualification article { border-top: 1px solid var(--surface-border); padding: .5rem 0; }
.saved-qualification label { display: block; margin: .5rem 0; }
.saved-qualification textarea { display: block; width: 100%; }
.saved-qualification pre { max-height: 22rem; overflow: auto; white-space: pre-wrap; }
.saved-qualification button { margin: .3rem .5rem .3rem 0; }
</style>
