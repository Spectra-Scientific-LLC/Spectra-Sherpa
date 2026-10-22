<template>
  <section class="run-detail">
    <header class="run-detail__heading">
      <div v-if="detail" class="run-detail__identity">
        <input
          v-model="runNameDraft"
          class="run-detail__name"
          aria-label="Run name"
          maxlength="255"
          :disabled="runNameSaving"
          @blur="saveRunName"
          @keydown.enter.prevent="($event.target as HTMLInputElement).blur()"
        />
        <span>Run #{{ detail.run.id }}</span>
        <Tag :value="detail.run.status" />
        <span :title="detail.run.executed_at">{{ detail.run.run_kind }} · {{ formatTimestamp(detail.run.executed_at) }}</span>
      </div>
      <p v-if="runNameError" role="alert">{{ runNameError }}</p>
    </header>
    <div class="run-detail__actions" role="group" aria-label="Run actions">
      <Button icon="pi pi-arrow-left" label="History" class="p-button-text" aria-label="Back to Runs" @click="backToRuns" />
      <Button v-if="detail?.run.workflow_id && detail.run.project_id && !loading && !error"
        icon="pi pi-sitemap" :label="detail.run.workflow_name ? `Workflow: ${detail.run.workflow_name}` : 'Workflow'" class="p-button-text" @click="openWorkflow" />
      <Button v-if="detail?.run.workflow_id && !loading && !error" icon="pi pi-file" label="Report"
        @click="openReport" />
      <Button v-if="detail?.run.status === 'completed' && detail.run.source_type !== 'paired_evaluation' && !loading && !error" icon="pi pi-send" label="Open Deploy"
        @click="router.push({ path: '/deploy', query: { run: detail.run.id, project: detail.run.project_id, application: `run:${detail.run.id}` } })" />
      <template v-if="detail?.run.produced_artifact_uids?.length && !loading && !error">
        <select v-if="detail.run.produced_artifact_uids.length > 1" v-model="promotionArtifactUid" aria-label="Fitted model for review">
          <option value="">Choose a fitted model</option><option v-for="uid in detail.run.produced_artifact_uids" :key="uid" :value="uid">{{ uid }}</option>
        </select>
        <Button label="Review for promotion" :disabled="detail.run.produced_artifact_uids.length > 1 && !promotionArtifactUid" @click="promotionArtifactUid = promotionArtifactUid || detail.run.produced_artifact_uids[0]; promotionOpen = true" />
      </template>
      <ContextualActions :context="!loading && !error && detail && detail.run.project_id === project.currentProjectId && project.currentProjectId != null
        ? { surface: 'run', projectId: project.currentProjectId, runId: detail.run.id } : null" />
    </div>
    <ModelPromotionReview v-if="promotionOpen && promotionArtifactUid && detail" :artifact-uid="promotionArtifactUid" :project-id="detail.run.project_id" :workflow-id="detail.run.workflow_id" :run-id="detail.run.id" @close="promotionOpen = false" @confirmed="promotionOpen = false" />
    <div v-if="error"><p role="alert">{{ error }}</p><Button icon="pi pi-refresh" label="Retry" @click="loadRun()" /></div>
    <ProgressSpinner v-else-if="loading" />
    <template v-else-if="detail">
      <p v-if="detail.error" role="status" class="evidence-gaps">
        <strong>{{ detail.run.status === 'partial' ? 'Incomplete saved run:' : 'Run issue:' }}</strong>
        {{ detail.error }}
      </p>
      <SavedPairedEvaluation v-if="detail.run.source_type === 'paired_evaluation'" :run-id="detail.run.id" />
      <template v-else>
      <ModelSummaryCard :summary="modelSummary" :can-edit-selection="Boolean(detail.run.workflow_id && detail.run.project_id)"
        @edit-selection="openWorkflow" />
      <p v-if="summaryError" role="status" class="summary-error">{{ summaryError }}</p>
      <SelectButton :model-value="tab" :options="tabs" aria-label="Run view" @update:model-value="setTab" />
      <section v-if="tab === 'Summary'" class="summary">
        <dl>
          <dt>Executed</dt><dd :title="detail.run.executed_at">{{ formatTimestamp(detail.run.executed_at) }}</dd>
          <dt>Recorded run name</dt><dd>{{ detail.run.name }}</dd>
          <dt>Kind</dt><dd>{{ detail.run.run_kind }}</dd>
          <dt v-if="detail.evidence.reason">Evidence note</dt><dd v-if="detail.evidence.reason">{{ detail.evidence.reason }}</dd>
          <dt>Notes</dt><dd>{{ detail.notes || 'None' }}</dd>
        </dl>
        <details class="audit-details">
          <summary>Audit details</summary>
          <dl>
            <dt>Saved workflow revision</dt><dd>{{ detail.integrity_hash || 'Not recorded' }}</dd>
            <dt>Retention</dt><dd>{{ detail.evidence.qualification }}</dd>
            <dt>Executed at (UTC)</dt><dd>{{ detail.run.executed_at }}</dd>
          </dl>
        </details>
        <section v-if="detail.batch" aria-label="Batch verification">
          <h2>Batch verification</h2>
          <dl>
            <dt>Batch</dt><dd>{{ detail.batch.batch_id }} · {{ detail.batch.batch_index }} / {{ detail.batch.batch_size }}</dd>
            <dt>Execution mode</dt><dd>{{ detail.batch.execution_mode === 'apply_model' ? 'Apply trained model — no refit' : 'Run workflow — train/evaluate' }}</dd>
            <dt>Dataset definition</dt><dd>{{ detail.batch.dataset?.name }} — {{ detail.batch.dataset_view?.name || 'Default' }}</dd>
            <dt>Scope</dt><dd>{{ detail.batch.scope_label }}</dd>
            <dt>Included samples</dt><dd>{{ detail.batch.n_included_samples }}</dd>
          </dl>
        </section>
        <section aria-label="Execution environment">
          <h2>Execution environment</h2>
          <template v-if="detail.environment_snapshot">
            <dl>
              <dt>Python</dt><dd>{{ detail.environment_snapshot.python || 'Not recorded' }}</dd>
              <dt>Backend build</dt><dd>{{ detail.environment_snapshot.backend_build_commit || 'Not recorded' }}</dd>
            </dl>
            <SavedValue :value="detail.environment_snapshot.packages" />
            <details><summary>Capture and numerical library details</summary><SavedValue :value="detail.environment_snapshot" /></details>
            <Button label="Export environment evidence" @click="exportEnvironment" />
          </template>
          <p v-else>Not recorded for this run. The current server environment is not substituted.</p>
        </section>
        <template v-if="application">
          <h2>Application</h2>
          <dl>
            <dt>Dataset</dt><dd>{{ application.dataset?.name || 'Not recorded' }}</dd>
            <dt>Scope</dt><dd>{{ application.scope }}</dd>
          </dl>
          <ul>
            <li v-for="item in application.results || []" :key="item.artifact_uid">
              {{ item.artifact_uid }}: {{ item.status }}<span v-if="item.error">. {{ item.error }}</span>
              <span v-if="item.status === 'completed' && !applicationTrust.some(view => view.artifactUid === item.artifact_uid)">. Applicability unavailable: no matching row-level fitted screen was retained.</span>
            </li>
          </ul>
          <section v-for="view in applicationTrust" :key="view.artifactUid" class="application-trust" :aria-label="`Prediction trust for ${view.artifactUid}`">
            <h3>{{ view.modelType.toUpperCase() }} prediction trust · {{ view.artifactUid }}</h3>
            <ReferenceQualityCard
              title="Training reference-value quality"
              :evidence="applicationReference(view.artifactUid, 'training')"
              :calibration-rows="applicationReferenceFitRows(view.artifactUid)"
            />
            <ReferenceQualityCard
              title="Applied cohort reference-value quality"
              :evidence="applicationReference(view.artifactUid, 'evaluation')"
              :unavailable-reason="applicationReference(view.artifactUid, 'evaluation') ? null : 'No measured response declaration is bound to this applied cohort; prediction error cannot be evaluated from this run.'"
            />
            <p>Saved workflow version: {{ applicationVersion(view.artifactUid) ?? 'Unavailable' }}</p>
            <p>{{ view.claimScope }}</p>
            <p>Method: {{ view.method || 'Unavailable' }} · Fitted reference: {{ view.referenceCount ?? 'Unavailable' }} samples · T² limit: {{ view.t2Limit ?? 'Unavailable' }} · Q limit: {{ view.qLimit ?? 'Unavailable' }}</p>
            <p v-if="view.rows.length > 200">Showing the first 200 of {{ view.rows.length }} rows. Download the complete table.</p>
            <Button label="Download prediction trust CSV" @click="exportApplicationTrust(view)" />
            <div class="application-trust__scroll">
              <table>
                <thead><tr><th>Applied dataset position</th><th>Prediction</th><th>Global T²/Q screen</th><th>T²</th><th>Q</th><th>Evidence note</th><th>Advisor</th></tr></thead>
                <tbody>
                  <tr v-for="row in view.rows.slice(0, 200)" :key="row.sampleIndex">
                    <td>{{ row.sampleIndex + 1 }}</td><td>{{ formatPrediction(row.prediction) }}</td>
                    <td>{{ trustLabel(row.status) }}</td><td>{{ row.t2 ?? '—' }}</td><td>{{ row.q ?? '—' }}</td>
                    <td>{{ row.reason || 'Global screening is not proof of prediction correctness.' }}</td>
                    <td><Button label="Ask Sherpa" :disabled="!applicationAdvisorAvailable" @click="askApplicationAdvisor(view, row.sampleIndex)" /></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </template>
        <p v-if="definitionError" role="status">{{ definitionError }}</p>
        <p v-if="applicationError" role="status">{{ applicationError }}</p>
        <section v-if="evidenceGaps.length" class="evidence-gaps" aria-label="Incomplete durable evidence">
          <h2>Incomplete durable evidence</h2>
          <p>The computation may have completed, but these named outputs are not fully recoverable from this saved run.</p>
          <ul>
            <li v-for="gap in evidenceGaps" :key="`${gap.node_id}:${gap.output}`">
              <button type="button" @click="openEvidenceGap(gap)">
                {{ evidenceGapLabel(gap) }}
              </button>
              <Tag :value="evidenceScopeLabel(gap.category)" severity="warn" />
              <span>{{ gap.reason }}</span>
              <small>{{ gap.recovery }}</small>
            </li>
          </ul>
          <Button
            v-if="detail.run.workflow_id && detail.run.project_id"
            label="Open workflow to re-run"
            icon="pi pi-refresh"
            class="p-button-outlined"
            @click="openWorkflow"
          />
        </section>
      </section>
      <section v-else class="inspection">
        <aside aria-label="Saved run nodes">
          <button v-for="node in nodes" :key="node.id" :aria-current="selectedNode === node.id ? 'true' : undefined" @click="selectNode(node.id)">
            <span>{{ node.label }}</span><small>{{ detail.node_statuses[node.id] || 'Not recorded' }}</small>
          </button>
        </aside>
        <div class="result">
          <p v-if="!selectedNode">No node results were retained.</p>
          <ProgressSpinner v-else-if="nodeLoading" />
          <template v-else>
            <h2>{{ selectedDefinition?.label || selectedNode }}</h2>
            <p v-if="nodeFailure" role="alert">{{ nodeFailure }}</p>
            <p v-for="message in outputMessages" :key="message" role="status">{{ message }}</p>
            <template v-if="tab === 'Results'">
              <section v-if="nodeTrust" class="application-trust" aria-label="Retained prediction trust">
                <h3>Per-file prediction trust</h3>
                <p>Fitted model artifact: {{ values.model_id }}</p>
                <p>Applied workflow version: {{ detail.run.workflow_version_id ?? 'Unavailable' }}</p>
                <p>{{ nodeTrust.claimScope }} Method: {{ nodeTrust.method || 'Unavailable' }} · Fitted reference: {{ nodeTrust.referenceCount ?? 'Unavailable' }} samples · T² limit: {{ nodeTrust.t2Limit ?? 'Unavailable' }} · Q limit: {{ nodeTrust.qLimit ?? 'Unavailable' }}</p>
                <p v-if="nodeTrust.rows.length > 200">Showing the first 200 of {{ nodeTrust.rows.length }} rows. Download the complete table.</p>
                <Button label="Download prediction trust CSV" @click="exportApplicationTrust(nodeTrust)" />
                <div class="application-trust__scroll"><table>
                  <thead><tr><th>File dataset position</th><th>Prediction</th><th>Global T²/Q screen</th><th>T²</th><th>Q</th><th>Advisor</th></tr></thead>
                  <tbody><tr v-for="row in nodeTrust.rows.slice(0, 200)" :key="row.sampleIndex">
                    <td>{{ row.sampleIndex + 1 }}</td><td>{{ formatPrediction(row.prediction) }}</td>
                    <td>{{ trustLabel(row.status) }}</td><td>{{ row.t2 ?? '—' }}</td><td>{{ row.q ?? '—' }}</td>
                    <td><Button label="Ask Sherpa" :disabled="!applicationAdvisorAvailable" @click="askRunApplicationAdvisor(row.sampleIndex)" /></td>
                  </tr></tbody>
                </table></div>
              </section>
              <p v-else-if="detail.run.run_kind === 'batch_inference' && selectedDefinition?.node_type === 'model.load_apply'" role="status">
                Applicability unavailable: no matching, exact fitted row-level screen was retained for this applied model.
              </p>
              <Dropdown v-if="presentationOptions.length" :model-value="selectedPresentation?.presentation.presentation_id" :options="presentationOptions"
                option-label="label" option-value="value" aria-label="Scientific result" @update:model-value="selectPresentation" />
              <p v-if="presentationError" role="status">{{ presentationError }}</p>
              <p v-if="presentationAvailabilityNotice" role="status">{{ presentationAvailabilityNotice }}</p>
              <ValidationLedger
                v-if="validationRows.length"
                :rows="validationRows"
                :title="`${detail?.run.name || 'run'}-${selectedNode || 'validation'}`"
              />
              <p v-if="ledgerUnavailableReason" role="status">{{ ledgerUnavailableReason }}</p>
              <SavedValue v-if="!validationRows.length && nodeOutput && selectedPresentation && !selectedPresentation.presentation.modes.includes('plot') && selectedPresentation.presentation.kind !== 'numeric_matrix'" :value="nodeOutput.presentation_value" scientific />
              <QuickPlotModal v-else-if="nodeOutput && selectedDefinition && (!validationRows.length || selectedPresentation?.presentation.modes.includes('plot'))" :key="selectedNode" embedded :model-value="true"
                :table-only="!!selectedPresentation && !selectedPresentation.presentation.modes.includes('plot')"
                :node-output="nodeOutput" :node-type="selectedDefinition.node_type" :node-label="selectedDefinition.label || selectedNode"
                :node-input="nodeInput" :node-inputs="nodeInputs" />
              <p v-else-if="!selectedDefinition">No saved node definition is available for scientific plotting. Retained values are shown below.</p>
              <p v-else-if="!rawNodeOutput">No scientific output was retained for this node.</p>
              <details v-if="Object.keys(values).length" class="audit-details">
                <summary>Raw saved outputs (for audit)</summary>
                <details v-for="(value, port) in values" :key="port" @toggle="rawOpen[port] = ($event.target as HTMLDetailsElement).open"><summary>{{ port }}</summary><pre v-if="rawOpen[port]">{{ JSON.stringify(value, null, 2) }}</pre></details>
              </details>
            </template>
            <template v-else>
              <h3>Diagnostics</h3>
              <SavedValue v-if="diagnostics" :value="diagnostics" scientific />
              <p v-else>No validation diagnostics were retained for this node.</p>
              <h3>Parameters used in this run</h3>
              <SavedValue v-if="effectiveParameters !== undefined" :value="effectiveParameters" />
              <p v-else role="status">
                Not recorded for this run; current defaults are not substituted.
              </p>
              <h3>Parameters set in the workflow</h3>
              <SavedValue v-if="selectedDefinition" :value="selectedDefinition.parameters" />
              <p v-else>Authored parameters were not retained.</p>
            </template>
          </template>
        </div>
      </section>
      </template>
    </template>
  </section>
</template>

<script setup lang="ts">
import SavedPairedEvaluation from "@/components/SavedPairedEvaluation.vue";
import ModelPromotionReview from "@/components/ModelPromotionReview.vue";
/* eslint-disable @typescript-eslint/no-explicit-any -- saved node payloads use the shared scientific renderer contract. */
import { computed, ref, shallowRef, watch, onBeforeUnmount } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import Button from 'primevue/button';
import SelectButton from 'primevue/selectbutton';
import ProgressSpinner from 'primevue/progressspinner';
import Dropdown from 'primevue/dropdown';
import Tag from 'primevue/tag';
import api from '@/api/client';
import ReferenceQualityCard from '@/components/ReferenceQualityCard.vue';
import type { ReferenceValueEvidence } from '@/types';
import { applicationReferenceEvidence } from '@/utils/referenceQuality';
import { focusSavedRun, releaseSavedRun } from '@/lib/sherpaAttention';
import { useProjectStore } from '@/stores/project';
import { useAuthStore } from '@/stores/auth';
import { useAdvisorStore } from '@/stores/advisor';
import { useAppConfig } from '@/composables/useAppConfig';
import { requestAdvisorPrompt } from '@/lib/advisorPromptActions';
import { buildNodeOutput } from '@/utils/nodeOutput';
import { availableScientificPresentations, resolveScientificPresentation, projectScientificPresentation, presentationResolutionError } from '@/utils/scientificPresentation';
import QuickPlotModal from '@/views/workflow-builder/modals/QuickPlotModal.vue';
import SavedValue from './SavedValue.vue';
import { downloadCsv, downloadJson } from '@/utils/download';
import { applicationTrustView, retainedNodeTrustView, type ApplicationTrustView } from '@/utils/applicationTrust';
import ContextualActions from '@/components/ContextualActions.vue';
import ValidationLedger from '@/components/ValidationLedger.vue';
import ModelSummaryCard from '@/components/ModelSummaryCard.vue';
import { buildModelSummary, primaryModelNode, summarySources, type ModelSummary, type PresentationContracts } from '@/utils/modelSummary';
import { extractValidationLedgerRows, validationLedgerUnavailableReason, type ValidationLedgerRow } from '@/utils/validationLedger';
import { evidenceScopeLabel, visibleEvidenceGapLabel, type EvidenceGap } from '@/utils/runEvidence';
import { formatTimestamp } from '@/utils/format';
import { useScopedRequest, type ScopedRequestTicket } from '@/composables/useScopedRequest';
import { registerProjectScopeReset } from '@/stores/projectScopeRegistry';

interface Evidence {
  state: string;
  reason?: string;
  storage?: string;
  sha256?: string;
}
interface Definition {
  nodes: Array<{
    node_id: string;
    node_type: string;
    label?: string;
    parameters: Record<string, unknown>;
  }>;
  edges: Array<{ from_node_id: string; to_node_id: string; from_output: string; to_input: string }>;
}
interface Detail {
  batch?: { batch_id: string; batch_index: number; batch_size: number; execution_mode: string;
    scope_label: string; dataset?: { name: string }; dataset_view?: { name: string }; n_included_samples: number } | null;
  environment_snapshot?: Record<string, unknown> | null;
  params_snapshot?: Record<string, Record<string, unknown>> | null;
  run: {
    id: number;
    project_id: number | null;
    workflow_id?: number | null;
    workflow_version_id?: number | null;
    name: string;
    display_name?: string | null;
    workflow_name?: string | null;
    status: string;
    executed_at: string;
    produced_artifact_uids?: string[] | null;
    run_kind: string;
    source_type?: string | null;
  };
  evidence: {
    qualification: string;
    reason?: string;
    outputs: Record<string, Record<string, Evidence>>;
  };
  evidence_gaps?: EvidenceGap[];
  node_statuses: Record<string, string>;
  integrity_hash?: string;
  error?: string;
  notes?: string;
}
const route = useRoute();
const router = useRouter();
const project = useProjectStore();
const auth = useAuthStore();
const advisor = useAdvisorStore();
const { appConfig, appMode, isFeatureEnabled } = useAppConfig();
const applicationAdvisorAvailable = computed(() => appMode.value !== 'local' &&
  appConfig.value?.advisorContextPolicy !== 'receipt' &&
  (isFeatureEnabled('sherpaAdvisor') || appConfig.value?.siteProfile === 'pro'));
const emit = defineEmits<{ (event: 'renamed'): void }>();
const detail = ref<Detail | null>(null);
const promotionOpen = ref(false);
const promotionArtifactUid = ref('');
watch(() => detail.value?.run.id, () => { promotionOpen.value = false; promotionArtifactUid.value = ''; });
const runNameDraft = ref('');
const runNameSaving = ref(false);
const runNameError = ref('');
const definition = ref<Definition | null>(null);
const definitionError = ref('');
const loading = ref(false);
const nodeLoading = ref(false);
const error = ref('');
const values = shallowRef<Record<string, any>>({});
const diagnostics = shallowRef<any>(null);
const nodeFailure = computed(() => typeof diagnostics.value?.error === 'string' ? diagnostics.value.error : null);
const descriptors = shallowRef<any>(null);
const presentations = shallowRef<any>(null);
const nodeInputs = shallowRef<Record<string, any>>({});
const application = shallowRef<any>(null);
const applicationOutputs = shallowRef<unknown[]>([]);
const applicationTrust = computed(() => applicationOutputs.value.map(applicationTrustView).filter((value): value is ApplicationTrustView => value !== null));
function applicationMetadata(artifactUid: string): Record<string, unknown> | null {
  const output = applicationOutputs.value.find(item =>
    item && typeof item === 'object' && !Array.isArray(item)
    && (item as Record<string, unknown>).artifact_uid === artifactUid,
  );
  if (!output || typeof output !== 'object' || Array.isArray(output)) return null;
  const metadata = (output as Record<string, unknown>).metadata;
  return metadata && typeof metadata === 'object' && !Array.isArray(metadata)
    ? metadata as Record<string, unknown> : null;
}
function applicationReference(artifactUid: string, population: 'training' | 'evaluation'): ReferenceValueEvidence | null {
  const output = applicationOutputs.value.find(item =>
    item && typeof item === 'object' && !Array.isArray(item)
    && (item as Record<string, unknown>).artifact_uid === artifactUid,
  );
  return applicationReferenceEvidence(output, population);
}
function applicationReferenceFitRows(artifactUid: string): number | null {
  const context = applicationMetadata(artifactUid)?.training_reference_fit_context;
  if (!context || typeof context !== 'object' || Array.isArray(context)) return null;
  const rows = (context as Record<string, unknown>).calibration_rows;
  return typeof rows === 'number' && Number.isSafeInteger(rows) && rows >= 0 ? rows : null;
}
const nodeTrust = computed(() => {
  if (detail.value?.run.run_kind !== 'batch_inference' || selectedDefinition.value?.node_type !== 'model.load_apply' ||
      !selectedNode.value || typeof values.value.model_id !== 'string' || !values.value.model_id ||
      !values.value.applicability) return null;
  const screen = values.value.applicability;
  const predictionPort = Array.isArray(screen.rows) ? 'labels' : 'result';
  const evidence = detail.value.evidence.outputs[selectedNode.value];
  if (!['model_id', 'applicability', predictionPort].every(port => evidence?.[port]?.state === 'exact')) return null;
  const prediction = values.value[predictionPort];
  return retainedNodeTrustView(values.value.model_id, screen, prediction);
});
const applicationError = ref('');
const rawOpen = ref<Record<string, boolean>>({});
const outputMessages = ref<string[]>([]);
const modelSummary = shallowRef<ModelSummary | null>(null);
const summaryError = ref('');
const tabs = ["Summary", "Results", "Validation"];
const tab = computed(() => {
  if (tabs.includes(String(route.query.view))) return String(route.query.view);
  const nodeId = selectedNode.value || preferredNode.value || "";
  const hasOutput = Object.values(detail.value?.evidence.outputs[nodeId] ?? {}).some(
    evidence => evidence.state === "exact",
  );
  return !hasOutput && detail.value?.evidence.outputs.__diagnostics__?.[nodeId]?.state === "exact"
    ? "Validation" : "Results";
});
const selectedNode = computed(() => (typeof route.query.node === "string" ? route.query.node : ""));
function exportEnvironment() {
  if (!detail.value?.environment_snapshot) return;
  downloadJson({ run_id: detail.value.run.id, workflow_integrity_hash: detail.value.integrity_hash,
    environment_snapshot: detail.value.environment_snapshot }, `run-${detail.value.run.id}-environment.json`);
}
const effectiveParameters = computed(() => detail.value?.params_snapshot?.[selectedNode.value]);
const selectedDefinition = computed(() =>
  definition.value?.nodes.find((node) => node.node_id === selectedNode.value),
);
const nodes = computed(() => {
  const ids = new Set([...Object.keys(detail.value?.node_statuses || {}), ...Object.keys(detail.value?.evidence.outputs || {}), ...(definition.value?.nodes.map(node => node.node_id) || [])]);
  return [...ids].filter(id => !id.startsWith('__')).map(id => ({ id, label: definition.value?.nodes.find(node => node.node_id === id)?.label || id }));
});
// Prefer retained scientific evaluation over input/load nodes, while honoring
// explicit node links (including links to missing evidence).
const preferredNode = computed(() => {
  const saved = definition.value?.nodes ?? [];
  const retained = (id: string) => Object.values(detail.value?.evidence.outputs[id] ?? {}).some(
    evidence => evidence.state === 'exact',
  ) || detail.value?.evidence.outputs.__diagnostics__?.[id]?.state === 'exact';
  const evaluation = saved.find(node => /^diagnostics\.(labeled_)?(regression|classification)_evaluator(?:_v2)?$/.test(node.node_type) && retained(node.node_id));
  const model = saved.find(node => /^(model|classification)\./.test(node.node_type) && retained(node.node_id));
  return evaluation?.node_id ?? model?.node_id ?? nodes.value[0]?.id;
});
const evidenceGaps = computed(() => detail.value?.evidence_gaps ?? []);
const evidenceGapLabel = (gap: EvidenceGap): string =>
  visibleEvidenceGapLabel(
    gap,
    Object.fromEntries(nodes.value.map((node) => [node.id, node.label])),
  );
function openEvidenceGap(gap: EvidenceGap) {
  if (gap.node_id.startsWith('__')) return;
  void router.replace({ query: { ...route.query, view: 'Results', node: gap.node_id } });
}
const rawNodeOutput = computed(() => Object.keys(values.value).length ? buildNodeOutput(values.value, undefined, diagnostics.value, descriptors.value, presentations.value) : null);
const presentationOptions = computed(() => availableScientificPresentations(undefined, rawNodeOutput.value).map(item => ({ value: item.presentation.presentation_id, label: item.presentation.label })));
const selectedPresentationId = computed(() => {
  // An explicit selection must still report absent evidence. On first open,
  // choose a retained, contract-declared presentation, as the canvas does.
  if (typeof route.query.presentation === 'string') return route.query.presentation;
  const preferred = rawNodeOutput.value?.presentation_contract?.payload.default_presentation;
  return presentationOptions.value.some(option => option.value === preferred)
    ? preferred
    : presentationOptions.value[0]?.value ?? preferred;
});
const presentationAvailabilityNotice = computed(() => {
  if (typeof route.query.presentation === 'string') return null;
  const contract = rawNodeOutput.value?.presentation_contract?.payload;
  if (!contract || !selectedPresentationId.value || selectedPresentationId.value === contract.default_presentation) return null;
  const preferred = contract.presentations.find(item => item.presentation_id === contract.default_presentation);
  const shown = presentationOptions.value.find(item => item.value === selectedPresentationId.value);
  return shown && preferred
    ? `${preferred.label} is unavailable for this run. Showing retained ${shown.label}.`
    : null;
});
const selectedPresentation = computed(() => resolveScientificPresentation(undefined, rawNodeOutput.value, selectedPresentationId.value));
const presentationError = computed(() => rawNodeOutput.value?.presentation_contract ? presentationResolutionError(undefined, rawNodeOutput.value, selectedPresentationId.value) : null);
const nodeOutput = computed(() => rawNodeOutput.value?.presentation_contract ? projectScientificPresentation(rawNodeOutput.value, selectedPresentation.value) : rawNodeOutput.value);
const validationRows = computed<ValidationLedgerRow[]>(() =>
  extractValidationLedgerRows(nodeOutput.value?.presentation_value),
);
const ledgerUnavailableReason = computed(() =>
  validationLedgerUnavailableReason(nodeOutput.value?.presentation_value, validationRows.value),
);
const nodeInput = computed(() => Object.values(nodeInputs.value)[0]);
let cache = new Map<string, Promise<any>>();
let activeRunTicket: ScopedRequestTicket | null = null;
let pendingRunNameSave: Promise<void> | null = null;
const runIdentity = () => [
  auth.user?.id, auth.sessionRevision,
  String(route.params.runId ?? ""), String(route.query.project ?? ""), project.currentProjectId,
];
function clearNodeEvidence() {
  values.value = {}; diagnostics.value = null; descriptors.value = null;
  presentations.value = null; nodeInputs.value = {}; outputMessages.value = [];
  rawOpen.value = {}; nodeLoading.value = false;
}
const nodeRequests = useScopedRequest(
  // This lane loads all retained ports for the node. Presentation selection is
  // a projection of those records, not a new owner (and can resolve on arrival).
  () => [...runIdentity(), selectedNode.value, tab.value],
  clearNodeEvidence,
);
const nameRequests = useScopedRequest(runIdentity, () => {
  runNameSaving.value = false;
  runNameError.value = '';
  pendingRunNameSave = null;
});
function clearRunEvidence() {
  activeRunTicket = null;
  nodeRequests.invalidate();
  nameRequests.invalidate();
  releaseSavedRun();
  cache = new Map();
  detail.value = null; definition.value = null; error.value = ''; definitionError.value = '';
  application.value = null; applicationOutputs.value = []; applicationError.value = '';
  modelSummary.value = null; summaryError.value = ''; loading.value = false;
  runNameDraft.value = '';
}
const runRequests = useScopedRequest(runIdentity, clearRunEvidence);
registerProjectScopeReset(runRequests.invalidate);
const failure = (err: any) => String(err?.response?.data?.detail || err?.message || 'Saved evidence could not be loaded.');
function setTab(value: string) { if (value) void router.replace({ query: { ...route.query, view: value } }); }
function selectNode(id: string) { void router.replace({ query: { ...route.query, node: id, presentation: undefined } }); }
function selectPresentation(id: string) { void router.replace({ query: { ...route.query, presentation: id } }); }
function backToRuns() {
  const query = { ...route.query };
  delete query.node; delete query.view; delete query.presentation;
  query.tab = 'run_history';
  void router.push({ path: '/runs', query });
}
function openWorkflow() {
  if (!detail.value?.run.workflow_id || !detail.value.run.project_id) return;
  void router.push({ path: '/workflow', query: {
    project_id: detail.value.run.project_id,
    workflow_id: detail.value.run.workflow_id,
  } });
}
function read(node: string, port: string): Promise<any> {
  const owner = activeRunTicket;
  if (!owner?.isCurrent()) return Promise.reject(new DOMException('Run scope changed.', 'AbortError'));
  const runId = String(route.params.runId);
  const projectId = project.currentProjectId;
  const key = `${projectId}/${runId}/${node}/${port}`;
  const evidence = detail.value?.evidence.outputs[node]?.[port];
  if (!evidence?.storage) return Promise.reject(new Error(evidence?.reason || `No retained output: ${node}/${port}`));
  if (!cache.has(key)) {
    // The cache belongs to the run, not an individual node/view. Node changes
    // reject stale presentation effects without aborting another same-run reader.
    cache.set(key, api.get(`/runs/${runId}/outputs/${encodeURIComponent(node)}/${encodeURIComponent(port)}`, {
      params: { project_id: projectId }, signal: owner.signal,
    }).then(response => response.data.value));
  }
  return cache.get(key)!;
}
async function saveRunName() {
  const run = detail.value?.run;
  const projectId = project.currentProjectId;
  if (runNameSaving.value) return pendingRunNameSave ?? undefined;
  if (!run || projectId == null) return;
  const name = runNameDraft.value.trim();
  if (!name) {
    runNameDraft.value = run.name;
    runNameError.value = 'Enter a run name.';
    return;
  }
  if (name === run.name) {
    runNameDraft.value = name;
    return;
  }
  runNameSaving.value = true;
  runNameError.value = '';
  const request = nameRequests.begin();
  const task = (async () => {
    try {
      const response = await api.patch(`/runs/${run.id}/name`, { name }, {
        params: { project_id: projectId }, signal: request.signal,
      });
      if (!request.isCurrent() || detail.value?.run.id !== run.id) return;
      detail.value.run.name = response.data.name;
      detail.value.run.display_name = response.data.name;
      runNameDraft.value = response.data.name;
      emit('renamed');
    } catch (err) {
      if (request.isCurrent() && detail.value?.run.id === run.id) {
        runNameDraft.value = run.name;
        runNameError.value = failure(err);
      }
    } finally {
      if (request.isCurrent()) runNameSaving.value = false;
    }
  })();
  pendingRunNameSave = task;
  try {
    await task;
  } finally {
    if (pendingRunNameSave === task) pendingRunNameSave = null;
  }
}
async function openReport(): Promise<void> {
  const run = detail.value?.run;
  const owner = activeRunTicket;
  if (!run?.workflow_id || !run.project_id) return;
  if (runNameSaving.value || runNameDraft.value.trim() !== run.name) await saveRunName();
  if (!owner?.isCurrent() || runNameError.value || detail.value?.run.id !== run.id ||
      runNameDraft.value.trim() !== detail.value.run.name) return;
  await router.push({ path: '/report', query: {
    workflow: run.workflow_id, run: run.id, project: run.project_id,
  } });
}
async function loadRun(allowProjectSelection = true) {
  clearRunEvidence();
  const request = runRequests.begin();
  activeRunTicket = request;
  if (!route.params.runId) { loading.value = false; return; }
  loading.value = true;
  try {
    const linkedProjectId = Number(route.query.project);
    if (Number.isSafeInteger(linkedProjectId) && linkedProjectId > 0
      && linkedProjectId !== project.currentProjectId && allowProjectSelection) {
      await project.selectProject(linkedProjectId);
    } else if (allowProjectSelection) {
      await project.ensureProjectForBrowserTab();
    }
    if (!request.isCurrent()) return;
    if (!project.currentProjectId || (route.query.project && Number(route.query.project) !== project.currentProjectId)) throw new Error('Select the project that owns this run.');
    const response = await api.get<Detail>(`/runs/${route.params.runId}/evidence`, {
      params: { project_id: project.currentProjectId }, signal: request.signal,
    });
    if (!request.isCurrent()) return;
    detail.value = response.data;
    runNameDraft.value = response.data.run.name;
    runNameError.value = '';
    focusSavedRun(Number(response.data.run.workflow_id), Number(route.params.runId));
    void advisor.switchScope({ projectId: project.currentProjectId, tabKey: 'models',
      subscopeKey: `run:${route.params.runId}`, resourceType: 'execution_run', resourceId: Number(route.params.runId),
      title: response.data.run.name });
    if (response.data.run.source_type === 'paired_evaluation') return;
    try {
      const saved = await read('__workflow__', 'definition');
      if (!request.isCurrent()) return;
      if (saved?.schema_version !== 1 || !Array.isArray(saved.nodes) || !Array.isArray(saved.edges)) throw new Error('Saved workflow definition is unsupported.');
      definition.value = saved;
    } catch (err) { if (request.isCurrent()) definitionError.value = failure(err); }
    if (!request.isCurrent()) return;
    if (detail.value.evidence.outputs.__application__?.selection?.state === 'exact') {
      try {
        const saved = await read('__application__', 'selection');
        if (!request.isCurrent()) return;
        application.value = saved;
        const successful = Array.isArray(saved?.successful_artifact_uids) ? saved.successful_artifact_uids : [];
        const outputs: unknown[] = [];
        for (const uid of successful) {
          if (typeof uid !== 'string') continue;
          if (detail.value.evidence.outputs[uid]?.default?.state !== 'exact') {
            applicationError.value = `Prediction evidence for ${uid} is unavailable: exact output was not retained.`;
            continue;
          }
          try { outputs.push(await read(uid, 'default')); }
          catch (err) { if (request.isCurrent()) applicationError.value = `Prediction evidence for ${uid} could not be loaded: ${failure(err)}`; }
          if (!request.isCurrent()) return;
        }
        applicationOutputs.value = outputs;
      } catch (err) { if (request.isCurrent()) applicationError.value = failure(err); }
    } else if (detail.value.evidence.outputs.__application__?.selection) {
      applicationError.value = 'Application context unavailable: exact selection evidence was not retained.';
    }
    if (!request.isCurrent()) return;
    if (route.query.trust === '1' && detail.value.run.run_kind === 'batch_inference') {
      const filePrefix = /^file_\d+::/.exec(selectedNode.value)?.[0];
      const modelNode = definition.value?.nodes.find(node => node.node_type === 'model.load_apply' &&
        (!filePrefix || node.node_id.startsWith(filePrefix)));
      if (modelNode && modelNode.node_id !== selectedNode.value) {
        await router.replace({ query: { ...route.query, node: modelNode.node_id } });
        if (!request.isCurrent()) return;
      }
    }
    void loadModelSummary(request);
    if (!selectedNode.value && preferredNode.value) selectNode(preferredNode.value);
    else await loadNode();
  } catch (err) { if (request.isCurrent()) error.value = failure(err); }
  finally { if (request.isCurrent()) loading.value = false; }
}
function formatPrediction(value: unknown): string {
  return Array.isArray(value) ? value.join(', ') : String(value ?? 'Unavailable');
}
function applicationVersion(artifactUid: string): number | null {
  const lineage = Array.isArray(application.value?.artifact_lineage) ? application.value.artifact_lineage : [];
  const record = lineage.find((item: any) => item?.artifact_uid === artifactUid);
  if (Number.isSafeInteger(record?.workflow_version_id)) return record.workflow_version_id;
  return nodeTrust.value?.artifactUid === artifactUid && Number.isSafeInteger(detail.value?.run.workflow_version_id)
    ? detail.value!.run.workflow_version_id! : null;
}
function trustLabel(status: ApplicationTrustView['rows'][number]['status']): string {
  return status === 'outside_global_screen' ? 'Outside global screen'
    : status === 'within_global_screen' ? 'Within global screen; unqualified' : 'Unavailable';
}
function askApplicationAdvisor(view: ApplicationTrustView, sampleIndex: number): void {
  const run = detail.value?.run;
  const record = detail.value?.evidence.outputs[view.artifactUid]?.default;
  if (!applicationAdvisorAvailable.value || !run?.workflow_id || !run.project_id || !record?.sha256) return;
  requestAdvisorPrompt('Explain this applied row\'s retained global predictor-space screen, its limits, and the next check. Do not infer prediction correctness or local support.', {
    diagnosticScope: {
      project_id: run.project_id,
      model_kind: 'application',
      reference: {
        kind: 'saved_application', artifact_uid: view.artifactUid, workflow_id: run.workflow_id,
        run_id: run.id, output_sha256: record.sha256, sample_index: sampleIndex,
      },
    },
  });
}
function askRunApplicationAdvisor(sampleIndex: number): void {
  const run = detail.value?.run;
  const record = detail.value?.evidence.outputs[selectedNode.value]?.applicability;
  if (!applicationAdvisorAvailable.value || !run?.workflow_id || !run.project_id || !record?.sha256) return;
  requestAdvisorPrompt('Explain this saved per-file prediction row\'s retained global predictor-space screen and its limits. Do not infer prediction correctness or local support.', {
    diagnosticScope: {
      project_id: run.project_id, model_kind: 'run_application',
      reference: {
        kind: 'saved_run_application', workflow_id: run.workflow_id, run_id: run.id,
        node_id: selectedNode.value, output_sha256: record.sha256, sample_index: sampleIndex,
      },
    },
  });
}
function safeCsvCell(value: string | number | null): string | number | null {
  if (typeof value !== 'string') return value;
  let index = 0;
  while (index < value.length) {
    const code = value.charCodeAt(index);
    if (code > 32 && code !== 127 && code !== 0xfeff && value[index].trim() !== '') break;
    index += 1;
  }
  return '=+-@'.includes(value[index] ?? '') && index < value.length ? `'${value}` : value;
}
function exportApplicationTrust(view: ApplicationTrustView): void {
  downloadCsv([
    ['artifact_uid', 'workflow_version_id', 'model_type', 'dataset_position', 'prediction', 'global_screen', 't2', 'q', 't2_limit', 'q_limit', 'reference_count', 'method', 'reason'],
    ...view.rows.map(row => [view.artifactUid, applicationVersion(view.artifactUid), view.modelType, row.sampleIndex + 1, formatPrediction(row.prediction), trustLabel(row.status), row.t2, row.q, view.t2Limit, view.qLimit, view.referenceCount, view.method, row.reason].map(value => safeCsvCell(value))),
  ], `prediction-trust-${view.artifactUid.replace(/[^A-Za-z0-9._-]/g, '_')}.csv`);
}
// The model card reads only retained, backend-computed statistics; a record
// that cannot be read is named rather than replaced with a recomputation.
async function loadModelSummary(request: ScopedRequestTicket) {
  if (!detail.value || !definition.value) return;
  try {
    const outputs = detail.value.evidence.outputs.__diagnostics__ ?? {};
    const contracts: PresentationContracts | null = outputs._scientific_presentations
      ? await read('__diagnostics__', '_scientific_presentations') : null;
    if (!request.isCurrent()) return;
    const model = primaryModelNode(definition.value);
    const records: Array<{ source: any; value: unknown }> = [];
    const missing: string[] = [];
    for (const source of summarySources(definition.value, contracts, model?.node_id ?? null)) {
      if (!detail.value?.evidence.outputs[source.nodeId]?.[source.port]?.storage) {
        if (source.port === 'component_curve') missing.push(`${source.nodeId}/component_curve (not retained in this run)`);
        continue;
      }
      try { records.push({ source, value: await read(source.nodeId, source.port) }); }
      catch { missing.push(`${source.nodeId}/${source.port}`); }
      if (!request.isCurrent()) return;
    }
    modelSummary.value = buildModelSummary(definition.value, detail.value?.params_snapshot ?? null, records);
    if (missing.length) summaryError.value = `Some summary statistics could not be loaded: ${missing.join(', ')}.`;
  } catch (err) {
    if (request.isCurrent()) summaryError.value = `Model summary unavailable: ${failure(err)}`;
  }
}
async function loadNode() {
  const request = nodeRequests.begin();
  clearNodeEvidence();
  if (!detail.value || !selectedNode.value || tab.value === 'Summary') return;
  const id = selectedNode.value;
  nodeLoading.value = true;
  const messages: string[] = [];
  const loaded: Record<string, any> = {};
  const inputs: Record<string, any> = {};
  try {
    for (const [port, evidence] of Object.entries(detail.value.evidence.outputs[id] || {})) {
      if (port === '_internal' || port.startsWith('__')) continue;
      if (evidence.state !== 'exact') messages.push(`${port}: ${evidence.state === 'missing' ? 'Not retained. ' : ''}${evidence.reason || evidence.state}`);
      if (!evidence.storage) continue;
      try { loaded[port] = await read(id, port); } catch (err) { messages.push(`${port}: ${failure(err)}`); }
      if (!request.isCurrent()) return;
    }
    const optional = async (port: string) => {
      if (!request.isCurrent()) return null;
      if (!detail.value?.evidence.outputs.__diagnostics__?.[port]) return null;
      try { return await read('__diagnostics__', port); } catch (err) { messages.push(failure(err)); return null; }
    };
    const diag = await optional(id);
    const scientific = await optional('_scientific_values');
    const presentation = await optional('_scientific_presentations');
    if (!request.isCurrent()) return;
    for (const edge of definition.value?.edges.filter(edge => edge.to_node_id === id) || []) {
      try { inputs[edge.to_input] = await read(edge.from_node_id, edge.from_output); }
      catch (err) { messages.push(`Input ${edge.to_input}: ${failure(err)}`); }
      if (!request.isCurrent()) return;
    }
    if (!request.isCurrent()) return;
    values.value = loaded; nodeInputs.value = inputs; diagnostics.value = diag;
    descriptors.value = scientific?.[id];
    const record = presentation?.[id];
    presentations.value = record ? { digest: record.contract_digest, payload: record.contract } : null;
    outputMessages.value = [...new Set(messages)];
  } finally { if (request.isCurrent()) nodeLoading.value = false; }
}
onBeforeUnmount(releaseSavedRun);
// A project dropdown change must not re-select the old run's project.
// Install this before the immediate deep-link load: project selection can
// synchronously invalidate that first request and needs a replacement owner.
watch(() => project.currentProjectId, () => void loadRun(false));
watch([() => auth.user?.id, () => auth.sessionRevision], () => {
  // A validated replacement session may reopen the same route, but must refetch
  // its retained evidence. Logout only clears it; it does not start anonymous IO.
  if (auth.user && project.currentProjectId != null) void loadRun(false);
});
watch([() => route.params.runId, () => route.query.project], () => void loadRun(), { immediate: true });
watch([selectedNode, tab], () => void loadNode());
onBeforeUnmount(() => { runRequests.dispose(); nodeRequests.dispose(); nameRequests.dispose(); cache.clear(); });
</script>

<style scoped>
.run-detail { min-width: 0; }
.run-detail__heading { margin-bottom: 1rem; }
.run-detail__heading h2 { margin: 0 0 .75rem; font-size: 1.25rem; }
.run-detail__heading p { color: var(--text-color-secondary); margin: .5rem 0 0; }
.run-detail__identity { display: flex; align-items: center; flex-wrap: wrap; gap: .75rem; overflow-wrap: anywhere; }
.run-detail__name { background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 4px; color: var(--text-color); font: inherit; font-size: 1.125rem; font-weight: 600; max-width: min(100%, 30rem); padding: .3rem .45rem; }
.run-detail__name:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.run-detail__identity > span:last-child { color: var(--text-color-secondary); }
.run-detail__actions { display: flex; align-items: center; flex-wrap: wrap; gap: .75rem; padding: 0 0 1rem; margin-bottom: 1rem; border-bottom: 1px solid var(--surface-border); }
.run-detail :deep(.p-button) { max-width: 100%; white-space: normal; overflow-wrap: anywhere; }
.run-detail :deep(.p-selectbutton) { display: flex; flex-wrap: wrap; }
h2 { font-size: 1.15rem; }
.summary { padding: 1rem 0; }
.summary-error { color: var(--text-color-secondary); font-size: .875rem; }
dl { display: grid; grid-template-columns: minmax(8rem, 12rem) minmax(0, 1fr); gap: .75rem; }
dd { margin: 0; overflow-wrap: anywhere; }
.inspection { display: grid; grid-template-columns: minmax(9rem, 14rem) minmax(0, 1fr); gap: 1rem; margin-top: 1rem; }
aside { border-right: 1px solid var(--surface-border); }
aside button { display: flex; flex-direction: column; width: 100%; text-align: left; border: 0; background: transparent; padding: .65rem; color: inherit; cursor: pointer; overflow-wrap: anywhere; }
aside button[aria-current] { background: var(--highlight-bg); color: var(--highlight-text-color); }
small { opacity: .7; }
.result { min-width: 0; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 32rem; overflow: auto; font-size: .8rem; }
details { border-top: 1px solid var(--surface-border); padding: .75rem 0; }
.audit-details > summary { cursor: pointer; color: var(--text-color-secondary); font-size: .875rem; }
.audit-details dl, .audit-details > details { margin-top: .75rem; font-size: .875rem; }
.evidence-gaps { margin-top: 1.25rem; padding: 1rem; border: 1px solid var(--ss-warning); border-radius: .5rem; }
.evidence-gaps ul { display: grid; gap: .75rem; padding-left: 1.25rem; }
.evidence-gaps li { display: grid; grid-template-columns: max-content max-content minmax(0, 1fr); align-items: baseline; gap: .35rem .75rem; }
.evidence-gaps li button { border: 0; padding: 0; background: none; color: var(--primary-color); font: inherit; font-weight: 600; cursor: pointer; text-align: left; }
.evidence-gaps li small { grid-column: 1 / -1; }
.application-trust { margin-top: 1rem; padding: 1rem; border: 1px solid var(--surface-border); border-radius: .5rem; }
.application-trust__scroll { max-height: 28rem; overflow: auto; margin-top: .75rem; }
.application-trust table { border-collapse: collapse; min-width: 100%; text-align: left; }
.application-trust th, .application-trust td { padding: .45rem .6rem; border-bottom: 1px solid var(--surface-border); vertical-align: top; }
@media (max-width: 640px) {
  .inspection { grid-template-columns: minmax(0, 1fr); gap: .5rem; }
  .evidence-gaps li { grid-template-columns: minmax(0, 1fr); }
  dl { grid-template-columns: minmax(0, 1fr); gap: .4rem; }
  .run-detail :deep(.saved-value) { grid-template-columns: minmax(0, 1fr); }
}
</style>
