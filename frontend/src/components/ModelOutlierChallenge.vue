<template>
  <details>
    <summary>Outlier challenge (optional)</summary>
    <p>Apply the frozen model and its existing detection limits to a separate, declared outlier set. Nothing is refitted. These results stay separate from ordinary validation RMSEP.</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <label>Dataset<select v-model="datasetId" @change="loadViews"><option :value="null">Choose dataset</option><option v-for="d in datasets" :key="d.id" :value="d.id">{{ d.name }}</option></select></label>
    <label>Named selection<select v-model="viewId"><option :value="null">Choose named view</option><option v-for="v in views" :key="v.id" :value="v.id">{{ v.name }}</option></select></label>
    <label>Outlier type<input v-model="outlierType" maxlength="200" placeholder="For example, unexpected matrix constituent" /></label>
    <label>Basis of the labels<textarea v-model="basis" rows="2" maxlength="4000" placeholder="Explain laboratory or sampling evidence for these labels" /></label>
    <label><input v-model="independentLabels" type="checkbox" /> These labels were established independently of this model's detector flags.</label>
    <button type="button" :disabled="busy || !viewId || !outlierType.trim() || !basis.trim() || !independentLabels" @click="run">Run challenge</button>
    <p>ASTM E1655 §18.2.5 recommends a separate outlier validation set when feasible. This exploratory check does not prove population-wide detection or independence.</p>
    <article v-for="record in records" :key="record.record_digest">
      <h4>{{ record.evidence.outlier_type }}</h4>
      <p>{{ record.evidence.detected }} detected · {{ record.evidence.missed }} missed · {{ record.evidence.unavailable }} unavailable / {{ record.evidence.evaluated_count }} evaluated; {{ record.evidence.excluded_count }} excluded.</p>
      <p v-if="!record.digest_verified || !record.matches_artifact_digest" role="alert">Historical evidence no longer verifies against this artifact.</p>
      <p>False-alarm rate: not assessed (no declared in-domain cohort).</p>
      <table><thead><tr><th>Specimen</th><th>Outcome</th><th>Prediction</th></tr></thead><tbody><tr v-for="row in record.evidence.rows" :key="row.specimen_id"><td>{{ row.specimen_id }}</td><td>{{ row.outcome }}</td><td>{{ row.prediction }}</td></tr></tbody></table>
      <details><summary>Frozen limits, prediction errors and provenance</summary><pre>{{ JSON.stringify(record.evidence, null, 2) }}</pre></details>
    </article>
  </details>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import api from '@/api/client';
import { getErrorMessage } from '@/utils/errors';
const props = defineProps<{ artifactUid?: string; canonicalArtifactId?: number; projectId: number }>();
const endpoint = computed(() => props.canonicalArtifactId ? `/deploy/canonical-artifacts/${props.canonicalArtifactId}/outlier-challenges` : `/models/${props.artifactUid}/outlier-challenges`);
type Option = { id: number; name: string };
type Challenge = { record_digest: string; digest_verified: boolean; matches_artifact_digest: boolean; evidence: { outlier_type: string; detected: number; missed: number; unavailable: number; evaluated_count: number; excluded_count: number; rows: { specimen_id: string; outcome: string; prediction: number | number[] }[] } };
const datasets = ref<Option[]>([]), views = ref<Option[]>([]), records = ref<Challenge[]>([]);
const datasetId = ref<number | null>(null), viewId = ref<number | null>(null);
const outlierType = ref(''), basis = ref(''), independentLabels = ref(false), busy = ref(false), error = ref('');
let generation = 0, viewGeneration = 0;
onBeforeUnmount(() => { generation++; viewGeneration++; });
async function loadViews() {
  const request = ++viewGeneration;
  views.value = []; viewId.value = null;
  if (!datasetId.value) return;
  try { const { data } = await api.get<Option[]>(`/experiments/${datasetId.value}/dataset-views`); if (request === viewGeneration) views.value = data; }
  catch (e) { if (request === viewGeneration) error.value = getErrorMessage(e, 'Views unavailable.'); }
}
async function run() {
  if (busy.value) return;
  const request = generation; busy.value = true; error.value = '';
  try {
    await api.post(endpoint.value, { dataset_view_id: viewId.value, outlier_type: outlierType.value.trim(), label_basis: basis.value.trim(), labels_independent_of_detector: independentLabels.value });
    const { data } = await api.get<{ records: Challenge[] }>(endpoint.value);
    if (request === generation) records.value = data.records;
  } catch (e) { if (request === generation) error.value = getErrorMessage(e, 'Challenge failed.'); }
  finally { if (request === generation) busy.value = false; }
}
watch(() => [props.artifactUid, props.canonicalArtifactId, props.projectId], async () => {
  const request = ++generation; viewGeneration++;
  records.value = []; datasets.value = []; views.value = []; error.value = ''; datasetId.value = viewId.value = null;
  busy.value = false; outlierType.value = ''; basis.value = ''; independentLabels.value = false;
  try {
    const [ds, history] = await Promise.all([api.get<Option[]>('/experiments', { params: { project_id: props.projectId, limit: 200 } }), api.get<{ records: Challenge[] }>(endpoint.value)]);
    if (request === generation) { datasets.value = ds.data; records.value = history.data.records; }
  } catch (e) { if (request === generation) error.value = getErrorMessage(e, 'Challenge evidence unavailable.'); }
}, { immediate: true });
</script>
<style scoped>
label { display: grid; gap: .3rem; margin: .8rem 0; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 20rem; overflow: auto; }
table { width: 100%; text-align: left; }
</style>
