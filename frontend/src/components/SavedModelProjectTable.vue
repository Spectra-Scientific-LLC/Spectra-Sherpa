<template>
  <section class="model-overview" aria-label="Saved model comparison">
    <header>
      <div>
        <h3>Saved model comparison</h3>
        <p>One row per saved model. CV describes development; an independent test is shown only when retained.</p>
      </div>
      <button type="button" :disabled="loading || !rows.length" @click="exportRows">Export this page's evidence</button>
    </header>
    <p v-if="loading" role="status">Reading saved-model evidence…</p>
    <p v-else-if="error" role="alert">{{ error }} <button type="button" @click="load">Retry</button></p>
    <p v-else-if="!rows.length">{{ offset ? 'No more saved models on this page. Go to the previous page.' : 'No saved models in this project.' }}</p>
    <div v-else class="model-overview__scroll">
      <table>
        <caption>Exact saved model evidence; missing values are unavailable, not zero.</caption>
        <thead>
          <tr>
            <th scope="col">Model</th><th scope="col">Target / units</th><th scope="col">Source</th>
            <th scope="col">Preprocessing</th><th scope="col">LVs</th><th scope="col">Calibration</th>
            <th scope="col">Executed validation</th><th scope="col">Classification accuracy</th><th scope="col">RMSEC</th><th scope="col">RMSECV</th>
            <th scope="col">RMSEP</th><th scope="col">R² / Q²</th><th scope="col">Independent n</th>
            <th scope="col">Reference</th><th scope="col">Domain</th><th scope="col">Bias / coverage</th>
            <th scope="col">Exclusions</th><th scope="col">Comparison group</th><th scope="col">Operational / analytical status</th><th scope="col">Evidence</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.artifact_uid">
            <th scope="row">
              <button type="button" :aria-label="`Open saved model ${row.name}, ${row.artifact_uid}`" @click="emit('select', row.artifact_uid)">{{ row.name }}</button>
              <small>{{ row.model_type }}</small>
              <button type="button" :aria-label="`Export evidence dossier for ${row.name}, ${row.artifact_uid}`" @click="exportModel(row)">Export dossier</button>
            </th>
            <td>{{ target(row) }}</td>
            <td>{{ row.training_dataset_id == null ? 'Source unavailable' : `Dataset #${row.training_dataset_id}` }}</td>
            <td>{{ preprocessing(row) }}</td>
            <td>{{ row.components ?? '—' }}</td>
            <td>{{ row.calibration_count ?? '—' }}</td>
            <td :title="row.held_out_validation ? undefined : row.validation?.unavailable_reason || undefined">{{ validation(row) }}</td>
            <td>{{ classificationAccuracy(row) }}</td>
            <td>{{ row.model_type === 'plsda' ? 'n/a' : metric(row.metrics?.rmsec) }}</td>
            <td>{{ row.model_type === 'plsda' ? 'n/a' : metric(row.metrics?.rmsecv) }}</td>
            <td :title="row.model_type === 'plsda' ? undefined : row.metrics?.rmsep == null ? 'No exact external validation evaluation is retained for this model.' : `Executed external validation on ${row.independent_test_count} complete specimens in view #${row.qualification?.validation_view_id}.`">{{ row.model_type === 'plsda' ? 'n/a' : metric(row.metrics?.rmsep) }}</td>
            <td>{{ row.model_type === 'plsda' ? 'n/a' : `${metric(row.metrics?.r2_calibration)} / ${metric(row.metrics?.q2_cv)}` }}</td>
            <td>{{ row.independent_test_count ?? '—' }}<small v-if="row.model_type !== 'plsda' && row.independent_test_count != null">External view #{{ row.qualification?.validation_view_id }}<span v-if="row.qualification?.state === 'stale_for_selected_dataset'"> · differs from selected dataset</span></small></td>
            <td :title="row.reference_quality?.reason || undefined">
              Calibration: {{ row.reference_quality?.method || 'Unknown' }}
              <small v-if="row.reference_quality?.version">v{{ row.reference_quality.version }}</small>
              <small v-if="row.reference_quality?.measurements_per_label">{{ row.reference_quality.measurements_per_label }} measurement{{ row.reference_quality.measurements_per_label === 1 ? '' : 's' }} / label</small>
              <small>External: {{ row.external_reference_quality?.method_id || 'Unavailable' }}<span v-if="row.external_reference_quality?.version"> v{{ row.external_reference_quality.version }}</span></small>
            </td>
            <td>{{ row.applicability_method || 'Unavailable' }}</td>
            <td :title="row.model_type === 'plsda' ? undefined : row.coverage == null ? 'Observed interval coverage unavailable.' : 'Observed interval coverage among screened available validation rows; no population coverage claim.'">
              <template v-if="row.model_type === 'plsda'">n/a</template>
              <template v-else>Bias {{ row.bias == null ? '—' : metric(row.bias) }}
              <small>Observed coverage {{ row.coverage == null ? '—' : metric(row.coverage) }}<span v-if="row.coverage_denominator != null"> ({{ row.coverage_denominator }}/{{ row.independent_test_count }} rows available)</span></small></template>
            </td>
            <td>{{ row.exclusions == null ? 'Unavailable' : row.exclusions.length }}</td>
            <td :title="row.comparison_reason || undefined">{{ groupLabel(row) }}</td>
            <td>
              <span>{{ row.operational_deploy_ready ? 'Operationally deploy-ready' : 'Operational readiness pending' }}</span>
              <small>Analytical qualification: {{ row.qualification?.state || 'unavailable' }}</small>
              <small>{{ row.gaps?.join('; ') || row.unavailable_reason || 'No gaps recorded' }}</small>
            </td>
            <td :title="row.evidence?.component_curve_sha256 || undefined">Artifact {{ row.artifact_uid }} · run #{{ row.evidence?.source_run_id ?? '—' }}<small>Curve {{ row.evidence?.component_curve_sha256?.slice(0, 12) || 'unavailable' }}</small></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="rows.length" class="model-overview__scope">
      {{ comparableGroups.length }} exact comparison group{{ comparableGroups.length === 1 ? '' : 's' }} on this page.
      Rows outside a named group cannot be ranked. Open PCA, PLS, or PLS-DA models for retained diagnostics and Ask Sherpa where available.
    </p>
    <div v-if="rows.length || offset > 0" class="model-overview__paging">
      <button type="button" :disabled="offset === 0 || loading" @click="offset = Math.max(0, offset - pageSize)">Previous</button>
      <span>{{ rows.length ? `Rows ${offset + 1}–${offset + rows.length}` : 'No rows on this page' }}</span>
      <button type="button" :disabled="rows.length < pageSize || loading" @click="offset += pageSize">Next</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import api from '@/api/client';
import { downloadJson } from '@/utils/download';

type Row = {
  artifact_uid: string; name: string; model_type: string; unavailable_reason?: string;
  target_names?: string[]; target_units?: (string | null)[]; training_dataset_id?: number | null;
  preprocessing?: {op_id?: string}[] | null; components?: number | null; calibration_count?: number | null;
  validation?: {method?: string | null; folds?: number | null; unavailable_reason?: string | null};
  held_out_validation?: {role?: string; count?: number; rmse?: number} | null;
  classification_metrics?: {calibration_balanced_accuracy?: number | null; cv_balanced_accuracy?: number | null; held_out_balanced_accuracy?: number | null; held_out_accuracy?: number | null} | null;
  metrics?: {rmsec?: number | null; rmsecv?: number | null; rmsep?: number | null; r2_calibration?: number | null; q2_cv?: number | null};
  independent_test_count?: number | null; bias?: number | null; coverage?: number | null;
  reference_quality?: {method?: string | null; version?: string | null; measurements_per_label?: number | null; reason?: string | null}; applicability_method?: string | null;
  external_reference_quality?: {method_id?: string | null; version?: string | null} | null; coverage_denominator?: number | null;
  exclusions?: string[] | null; qualification?: {state?: string; validation_view_id?: number}; gaps?: string[];
  comparison_key?: string | null; comparison_reason?: string | null;
  operational_deploy_ready?: boolean;
  evidence?: {source_run_id?: number | null; component_curve_sha256?: string | null};
};
type ProjectOverviewResponse = {rows: Row[]; comparable_groups: string[][]};
const props = defineProps<{projectId: number; refreshKey?: number}>();
const emit = defineEmits<{select: [uid: string]}>();
const pageSize = 50;
const rows = ref<Row[]>([]);
const comparableGroups = ref<string[][]>([]);
const loading = ref(false);
const error = ref('');
const offset = ref(0);
let request = 0;

async function load(): Promise<void> {
  const current = ++request;
  loading.value = true;
  error.value = '';
  try {
    const response = await api.get<ProjectOverviewResponse>('/models/project-overview', {
      params: {project_id: props.projectId, limit: pageSize, offset: offset.value},
    });
    if (current !== request) return;
    rows.value = response.data.rows;
    comparableGroups.value = response.data.comparable_groups;
  } catch {
    if (current !== request) return;
    rows.value = [];
    comparableGroups.value = [];
    error.value = 'Saved-model evidence could not be verified.';
  } finally {
    if (current === request) loading.value = false;
  }
}
watch(() => [props.projectId, offset.value, props.refreshKey], () => { void load(); }, {immediate: true});
watch(() => props.projectId, () => { offset.value = 0; });

function metric(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? Number(value.toPrecision(5)).toString() : '—';
}
function target(row: Row): string {
  if (!row.target_names?.length) return 'Unavailable';
  return row.target_names.map((name, index) => `${name}${row.model_type === 'plsda' ? '' : row.target_units?.[index] ? ` (${row.target_units[index]})` : ' (units unknown)'}`).join(', ');
}
function preprocessing(row: Row): string {
  if (row.preprocessing == null) return 'Not retained';
  const steps = row.preprocessing.flatMap(step => {
    const op = step.op_id || '';
    if (!op.startsWith('preprocess.') && !op.startsWith('selection.')) return [];
    const labels: Record<string, string> = {
      'preprocess.snv': 'SNV', 'preprocess.msc': 'MSC',
      'preprocess.mean_center': 'Mean center', 'preprocess.normalize': 'Normalize',
    };
    return [labels[op] || op.split('.').pop()!.replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase())];
  });
  return steps.length ? steps.join(' → ') : 'No preprocessing';
}
function groupLabel(row: Row): string {
  const index = comparableGroups.value.findIndex(group => group.includes(row.artifact_uid));
  if (index >= 0) return `Group ${index + 1}`;
  return row.comparison_key ? 'No matching model on this page' : row.model_type === 'plsda' ? 'Not ranked' : 'Incomparable: missing exact cohort or validation receipt';
}
function validation(row: Row): string {
  const cv = row.validation?.method ? `${row.validation.method}${row.validation.folds ? ` · ${row.validation.folds} folds` : ''} (development)` : null;
  const held = row.held_out_validation?.role === 'held_out_test'
    ? `${row.held_out_validation.count} held-out samples`
    : row.held_out_validation?.role === 'within_dataset_held_out_test'
      ? `Within-dataset held-out RMSE ${metric(row.held_out_validation.rmse)} (n=${row.held_out_validation.count})`
      : null;
  return [cv, held].filter(Boolean).join('; ') || 'Unavailable';
}
function classificationAccuracy(row: Row): string {
  const values = row.classification_metrics;
  if (!values) return '—';
  const parts = [
    values.cv_balanced_accuracy == null ? null : `CV balanced ${metric(values.cv_balanced_accuracy)}`,
    values.held_out_balanced_accuracy == null ? null : `Held-out balanced ${metric(values.held_out_balanced_accuracy)}`,
    values.held_out_accuracy == null ? null : `Held-out accuracy ${metric(values.held_out_accuracy)}`,
  ];
  return parts.filter(Boolean).join(' · ') || 'Unavailable';
}
function exportRows(): void {
  downloadJson({schema_version: 'spectrasherpa.saved-model-project-overview/1', project_id: props.projectId,
    page_offset: offset.value, page_limit: pageSize, page_row_count: rows.value.length,
    claim_scope: 'Saved evidence only. CV is development evidence; no regulatory qualification is implied.',
    rows: rows.value, comparable_groups: comparableGroups.value}, `project-${props.projectId}-saved-model-evidence-page-${offset.value}.json`);
}
function exportModel(row: Row): void {
  downloadJson({
    schema_version: 'spectrasherpa.saved-model-evidence-dossier/1',
    project_id: props.projectId,
    claim_scope: 'Exact retained evidence and declared-use qualification status only when current model and source verification pass; no regulatory certification implied.',
    model: row,
  }, `saved-model-${row.artifact_uid}-evidence.json`);
}
</script>

<style scoped>
.model-overview { border: 1px solid var(--surface-border); border-radius: 8px; padding: 1rem; margin: 1rem 0; }
.model-overview header { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.model-overview h3 { margin: 0; font-size: 1.1rem; }
.model-overview p { color: var(--text-color-secondary); margin: .35rem 0; }
.model-overview__scroll { overflow-x: auto; max-width: 100%; }
.model-overview table { border-collapse: collapse; font-size: .86rem; min-width: 1450px; width: 100%; }
.model-overview caption { text-align: left; padding: .5rem 0; }
.model-overview th, .model-overview td { border-bottom: 1px solid var(--surface-border); padding: .55rem; text-align: left; vertical-align: top; }
.model-overview tbody th { min-width: 135px; }
.model-overview tbody th small, .model-overview td small { display: block; color: var(--text-color-secondary); margin-top: .2rem; }
.model-overview__paging { display: flex; align-items: center; justify-content: flex-end; gap: 1rem; margin-top: .75rem; }
</style>
