<template>
  <section class="run-detail">
    <header class="run-detail__heading">
      <h2>Inspect</h2>
      <div v-if="detail" class="run-detail__identity">
        <strong>{{ detail.run.display_name || detail.run.name }}</strong>
        <span>Run #{{ detail.run.id }}</span>
        <Tag :value="detail.run.status" />
        <span>{{ detail.run.run_kind }} · {{ detail.run.executed_at }}</span>
      </div>
      <p>Review the saved computation and its retained scientific evidence.</p>
    </header>
    <div class="run-detail__actions" role="group" aria-label="Run actions">
      <Button icon="pi pi-arrow-left" label="History" class="p-button-text" aria-label="Back to Runs" @click="backToRuns" />
      <Button v-if="detail?.run.workflow_id && detail.run.project_id && !loading && !error"
        icon="pi pi-sitemap" :label="detail.run.workflow_name ? `Workflow: ${detail.run.workflow_name}` : 'Workflow'" class="p-button-text" @click="openWorkflow" />
      <Button v-if="detail?.run.workflow_id && !loading && !error" icon="pi pi-file" label="Report"
        @click="router.push({ path: '/report', query: { workflow: detail.run.workflow_id, run: detail.run.id, project: detail.run.project_id } })" />
      <Button v-if="detail?.run.status === 'completed' && !loading && !error" icon="pi pi-send" label="Open Deploy"
        @click="router.push({ path: '/deploy', query: { run: detail.run.id, project: detail.run.project_id, application: `run:${detail.run.id}` } })" />
      <ContextualActions :context="!loading && !error && detail && detail.run.project_id === project.currentProjectId && project.currentProjectId != null
        ? { surface: 'run', projectId: project.currentProjectId, runId: detail.run.id } : null" />
    </div>
    <div v-if="error"><p role="alert">{{ error }}</p><Button icon="pi pi-refresh" label="Retry" @click="loadRun" /></div>
    <ProgressSpinner v-else-if="loading" />
    <template v-else-if="detail">
      <SelectButton :model-value="tab" :options="tabs" aria-label="Run view" @update:model-value="setTab" />
      <section v-if="tab === 'Summary'" class="summary">
        <dl>
          <dt>Executed</dt><dd>{{ detail.run.executed_at }}</dd>
          <dt>Recorded run name</dt><dd>{{ detail.run.name }}</dd>
          <dt>Kind</dt><dd>{{ detail.run.run_kind }}</dd>
          <dt>Saved workflow revision</dt><dd>{{ detail.integrity_hash || 'Not recorded' }}</dd>
          <dt>Retention</dt><dd>{{ detail.evidence.qualification }}</dd>
          <dt v-if="detail.evidence.reason">Evidence note</dt><dd v-if="detail.evidence.reason">{{ detail.evidence.reason }}</dd>
          <dt v-if="detail.error">Failure</dt><dd v-if="detail.error">{{ detail.error }}</dd>
          <dt>Notes</dt><dd>{{ detail.notes || 'None' }}</dd>
        </dl>
        <section aria-label="Execution environment">
          <h2>Execution environment</h2>
          <template v-if="detail.environment_snapshot">
            <p>Recorded environment evidence. This does not guarantee deterministic replay.</p>
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
            </li>
          </ul>
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
              <SavedValue v-if="nodeOutput && selectedPresentation && !selectedPresentation.presentation.modes.includes('plot') && selectedPresentation.presentation.kind !== 'numeric_matrix'" :value="nodeOutput.presentation_value" />
              <QuickPlotModal v-else-if="nodeOutput && selectedDefinition" :key="selectedNode" embedded :model-value="true"
                :table-only="!!selectedPresentation && !selectedPresentation.presentation.modes.includes('plot')"
                :node-output="nodeOutput" :node-type="selectedDefinition.node_type" :node-label="selectedDefinition.label || selectedNode"
                :node-input="nodeInput" :node-inputs="nodeInputs" />
              <p v-else-if="!selectedDefinition">No saved node definition is available for scientific plotting. Retained values are shown below.</p>
              <p v-else-if="!rawNodeOutput">No scientific output was retained for this node.</p>
              <details v-for="(value, port) in values" :key="port" @toggle="rawOpen[port] = ($event.target as HTMLDetailsElement).open"><summary>{{ port }}: retained value</summary><pre v-if="rawOpen[port]">{{ JSON.stringify(value, null, 2) }}</pre></details>
            </template>
            <template v-else>
              <h3>Saved diagnostics</h3>
              <SavedValue v-if="diagnostics" :value="diagnostics" />
              <p v-else>No validation diagnostics were retained for this node.</p>
              <h3>Effective executed parameters</h3>
              <SavedValue v-if="effectiveParameters !== undefined" :value="effectiveParameters" />
              <p v-else role="status">
                Effective parameters were not retained; current defaults are not substituted.
              </p>
              <h3>Explicit saved graph parameters</h3>
              <SavedValue v-if="selectedDefinition" :value="selectedDefinition.parameters" />
              <p v-else>Authored parameters were not retained.</p>
            </template>
          </template>
        </div>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
/* eslint-disable @typescript-eslint/no-explicit-any -- saved node payloads use the shared scientific renderer contract. */
import { computed, ref, shallowRef, watch, onBeforeUnmount } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import Button from 'primevue/button';
import SelectButton from 'primevue/selectbutton';
import ProgressSpinner from 'primevue/progressspinner';
import Dropdown from 'primevue/dropdown';
import Tag from 'primevue/tag';
import api from '@/api/client';
import { useProjectStore } from '@/stores/project';
import { useAdvisorStore } from '@/stores/advisor';
import { buildNodeOutput } from '@/utils/nodeOutput';
import { availableScientificPresentations, resolveScientificPresentation, projectScientificPresentation, presentationResolutionError } from '@/utils/scientificPresentation';
import QuickPlotModal from '@/views/workflow-builder/modals/QuickPlotModal.vue';
import SavedValue from './SavedValue.vue';
import { downloadJson } from '@/utils/download';
import ContextualActions from '@/components/ContextualActions.vue';
import ValidationLedger from '@/components/ValidationLedger.vue';
import { extractValidationLedgerRows, validationLedgerUnavailableReason, type ValidationLedgerRow } from '@/utils/validationLedger';
import { evidenceScopeLabel, visibleEvidenceGapLabel, type EvidenceGap } from '@/utils/runEvidence';

interface Evidence {
  state: string;
  reason?: string;
  storage?: string;
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
  environment_snapshot?: Record<string, unknown> | null;
  params_snapshot?: Record<string, Record<string, unknown>> | null;
  run: {
    id: number;
    project_id: number | null;
    workflow_id?: number | null;
    name: string;
    display_name?: string | null;
    workflow_name?: string | null;
    status: string;
    executed_at: string;
    run_kind: string;
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
const advisor = useAdvisorStore();
const detail = ref<Detail | null>(null);
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
const applicationError = ref('');
const rawOpen = ref<Record<string, boolean>>({});
const outputMessages = ref<string[]>([]);
const tabs = ["Summary", "Results", "Validation"];
const tab = computed(() =>
  tabs.includes(String(route.query.view)) ? String(route.query.view) : "Summary",
);
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
let generation = 0;
let nodeGeneration = 0;
let cache = new Map<string, Promise<any>>();
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
  const key = `${node}/${port}`;
  const evidence = detail.value?.evidence.outputs[node]?.[port];
  if (!evidence?.storage) return Promise.reject(new Error(evidence?.reason || `No retained output: ${node}/${port}`));
  if (!cache.has(key)) {
    cache.set(key, api.get(`/runs/${route.params.runId}/outputs/${encodeURIComponent(node)}/${encodeURIComponent(port)}`, { params: { project_id: project.currentProjectId } }).then(response => response.data.value));
  }
  return cache.get(key)!;
}
async function loadRun() {
  const request = ++generation;
  ++nodeGeneration;
  detail.value = null; definition.value = null; cache = new Map(); error.value = ''; definitionError.value = '';
  values.value = {}; diagnostics.value = null; nodeInputs.value = {};
  application.value = null;
  applicationError.value = '';
  if (!route.params.runId) { loading.value = false; return; }
  loading.value = true;
  try {
    const linkedProjectId = Number(route.query.project);
    if (Number.isSafeInteger(linkedProjectId) && linkedProjectId > 0
      && linkedProjectId !== project.currentProjectId) {
      await project.selectProject(linkedProjectId);
    } else {
      await project.ensureProjectForBrowserTab();
    }
    if (request !== generation) return;
    if (!project.currentProjectId || (route.query.project && Number(route.query.project) !== project.currentProjectId)) throw new Error('Select the project that owns this run.');
    const response = await api.get<Detail>(`/runs/${route.params.runId}/evidence`, { params: { project_id: project.currentProjectId } });
    if (request !== generation) return;
    detail.value = response.data;
    void advisor.switchScope({ projectId: project.currentProjectId, tabKey: 'models',
      subscopeKey: `run:${route.params.runId}`, resourceType: 'execution_run', resourceId: Number(route.params.runId),
      title: response.data.run.name });
    try {
      const saved = await read('__workflow__', 'definition');
      if (request !== generation) return;
      if (saved?.schema_version !== 1 || !Array.isArray(saved.nodes) || !Array.isArray(saved.edges)) throw new Error('Saved workflow definition is unsupported.');
      definition.value = saved;
    } catch (err) { if (request === generation) definitionError.value = failure(err); }
    if (request !== generation) return;
    if (detail.value.evidence.outputs.__application__?.selection) {
      try {
        const saved = await read('__application__', 'selection');
        if (request !== generation) return;
        application.value = saved;
      } catch (err) { if (request === generation) applicationError.value = failure(err); }
    }
    if (request !== generation) return;
    if (!selectedNode.value && nodes.value[0]) selectNode(nodes.value[0].id);
    else await loadNode();
  } catch (err) { if (request === generation) error.value = failure(err); }
  finally { if (request === generation) loading.value = false; }
}
async function loadNode() {
  const request = ++nodeGeneration;
  values.value = {}; diagnostics.value = null; descriptors.value = null; presentations.value = null; nodeInputs.value = {}; outputMessages.value = [];
  rawOpen.value = {}; nodeLoading.value = false;
  if (!detail.value || !selectedNode.value || tab.value === 'Summary') return;
  const id = selectedNode.value;
  nodeLoading.value = true;
  const messages: string[] = [];
  const loaded: Record<string, any> = {};
  const inputs: Record<string, any> = {};
  try {
    for (const [port, evidence] of Object.entries(detail.value.evidence.outputs[id] || {})) {
      if (evidence.state !== 'exact') messages.push(`${port}: ${evidence.state === 'missing' ? 'Not retained. ' : ''}${evidence.reason || evidence.state}`);
      if (!evidence.storage) continue;
      try { loaded[port] = await read(id, port); } catch (err) { messages.push(`${port}: ${failure(err)}`); }
      if (request !== nodeGeneration) return;
    }
    const optional = async (port: string) => {
      if (!detail.value?.evidence.outputs.__diagnostics__?.[port]) return null;
      try { return await read('__diagnostics__', port); } catch (err) { messages.push(failure(err)); return null; }
    };
    const diag = await optional(id);
    const scientific = await optional('_scientific_values');
    const presentation = await optional('_scientific_presentations');
    for (const edge of definition.value?.edges.filter(edge => edge.to_node_id === id) || []) {
      try { inputs[edge.to_input] = await read(edge.from_node_id, edge.from_output); }
      catch (err) { messages.push(`Input ${edge.to_input}: ${failure(err)}`); }
      if (request !== nodeGeneration) return;
    }
    if (request !== nodeGeneration) return;
    values.value = loaded; nodeInputs.value = inputs; diagnostics.value = diag;
    descriptors.value = scientific?.[id];
    const record = presentation?.[id];
    presentations.value = record ? { digest: record.contract_digest, payload: record.contract } : null;
    outputMessages.value = [...new Set(messages)];
  } finally { if (request === nodeGeneration) nodeLoading.value = false; }
}
watch([() => route.params.runId, () => project.currentProjectId], () => void loadRun(), { immediate: true });
watch([selectedNode, tab], () => void loadNode());
onBeforeUnmount(() => { ++generation; ++nodeGeneration; cache.clear(); });
</script>

<style scoped>
.run-detail { min-width: 0; }
.run-detail__heading { margin-bottom: 1rem; }
.run-detail__heading h2 { margin: 0 0 .75rem; font-size: 1.25rem; }
.run-detail__heading p { color: var(--text-color-secondary); margin: .5rem 0 0; }
.run-detail__identity { display: flex; align-items: center; flex-wrap: wrap; gap: .75rem; overflow-wrap: anywhere; }
.run-detail__identity strong { font-size: 1.125rem; }
.run-detail__identity > span:last-child { color: var(--text-color-secondary); }
.run-detail__actions { display: flex; align-items: center; flex-wrap: wrap; gap: .75rem; padding: 0 0 1rem; margin-bottom: 1rem; border-bottom: 1px solid var(--surface-border); }
.run-detail :deep(.p-button) { max-width: 100%; white-space: normal; overflow-wrap: anywhere; }
.run-detail :deep(.p-selectbutton) { display: flex; flex-wrap: wrap; }
h2 { font-size: 1.15rem; }
.summary { padding: 1rem 0; }
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
.evidence-gaps { margin-top: 1.25rem; padding: 1rem; border: 1px solid var(--orange-300); border-radius: .5rem; }
.evidence-gaps ul { display: grid; gap: .75rem; padding-left: 1.25rem; }
.evidence-gaps li { display: grid; grid-template-columns: max-content max-content minmax(0, 1fr); align-items: baseline; gap: .35rem .75rem; }
.evidence-gaps li button { border: 0; padding: 0; background: none; color: var(--primary-color); font: inherit; font-weight: 600; cursor: pointer; text-align: left; }
.evidence-gaps li small { grid-column: 1 / -1; }
@media (max-width: 640px) {
  .inspection { grid-template-columns: minmax(0, 1fr); gap: .5rem; }
  .evidence-gaps li { grid-template-columns: minmax(0, 1fr); }
  dl { grid-template-columns: minmax(0, 1fr); gap: .4rem; }
  .run-detail :deep(.saved-value) { grid-template-columns: minmax(0, 1fr); }
}
</style>
