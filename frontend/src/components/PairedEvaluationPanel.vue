<template>
  <section class="paired-evaluation" aria-label="Common protocol and paired robustness">
    <h3>Evaluate under a common protocol</h3>
    <p>Optional development check for two saved PLS recipes. Each recipe uses the same training rows and folds. Held-out samples stay excluded; repeated CV is not independent validation.</p>
    <template v-if="recipes.length === 2">
      <label>Development population
        <select v-model.number="population" :disabled="busy" @change="clearPreview">
          <option v-for="recipe in recipes" :key="recipe.run_id" :value="recipe.run_id">{{ recipe.label }}</option>
        </select>
      </label>
      <label>Folds <input v-model.number="folds" type="number" min="2" max="20" :disabled="busy" @input="clearPreview" /></label>
      <label>Repetitions <input v-model.number="repetitions" type="number" min="1" max="10" :disabled="busy" @input="clearPreview" /></label>
      <p>Use one repetition for common CV or five for a paired robustness check. Grouped data supports one intact-group assessment; randomized grouped repetitions are refused.</p>
      <details><summary>Advanced settings</summary>
        <label>First random seed <input v-model.number="seed" type="number" min="0" :disabled="busy" @input="clearPreview" /></label>
        <label>Meaningful RMSECV difference (response units)
          <input v-model.number="margin" type="number" min="0" step="any" :disabled="busy" @input="clearPreview" />
        </label>
        <p>Zero reports numerical direction only. Set a scientifically meaningful difference before execution. No significance claim is made from overlapping repetitions.</p>
      </details>
      <button type="button" :disabled="busy" @click="previewProtocol">Review evaluation protocol</button>
      <div v-if="preview">
        <p>Fit within {{ preview.development_count }} development samples; exclude {{ preview.held_out_count }} held-out samples. {{ preview.fits }} fold fits across both recipes.</p>
        <p>{{ preview.notice }}</p>
        <button type="button" :disabled="busy" @click="start">Run evaluation</button>
      </div>
      <button v-if="busy && jobId" type="button" @click="cancel">Cancel evaluation</button>
      <p v-if="busy" role="status">Evaluation running. You can leave this view; its status is retained in Runs. Cancellation stops between recipe evaluations.</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="status && !busy">{{ status }}. {{ status === 'completed' ? 'The source runs are unchanged.' : 'Incomplete evaluations do not support comparison. Restart creates a new record; resume is unavailable.' }}</p>
      <button v-if="runId" type="button" @click="router.push({ path: `/runs/${runId}` })">Open saved evaluation</button>
      <PairedEvaluationResults v-if="record && runId" :record="record" :run-id="runId" />
    </template>
    <p v-else>Select exactly two saved fitted PLS model outputs to review an evaluation protocol.</p>
  </section>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import api from '@/api/client';
import { useRouter } from 'vue-router';
import PairedEvaluationResults from './PairedEvaluationResults.vue';
import type { PairedEvaluationRecord } from '@/types/pairedEvaluation';
const router = useRouter();

const props = defineProps<{ recipes: Array<{ run_id: number; model_node_id: string; label: string }> }>();
const emit = defineEmits<{ completed: [runId: number] }>();
const population = ref(props.recipes[0]?.run_id ?? 0);
const folds = ref(5), repetitions = ref(1), seed = ref(42), margin = ref(0);
const busy = ref(false), error = ref(''), status = ref('');
const runId = ref<number>(), jobId = ref<number>();
const preview = ref<{ development_count: number; held_out_count: number; fits: number; notice: string }>();
const record = ref<PairedEvaluationRecord>();
let timer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
function clearPreview() { preview.value = undefined; }
watch(() => props.recipes, () => { population.value = props.recipes[0]?.run_id ?? 0; clearPreview(); }, { deep: true });
const payload = () => ({ recipes: props.recipes.map(({ run_id, model_node_id }) => ({ run_id, model_node_id })), population_run_id: population.value, folds: folds.value, repetitions: repetitions.value, seed: seed.value, meaningful_rmsecv_difference: margin.value });
function message(e: unknown): string {
  const value = e as { response?: { data?: { detail?: unknown } }; message?: string };
  return typeof value.response?.data?.detail === 'string' ? value.response.data.detail : value.message || 'Evaluation request failed. Check the declared protocol and try again.';
}
async function previewProtocol() {
  error.value = ''; preview.value = undefined;
  try { preview.value = (await api.post('/runs/paired-evaluations/preview', payload())).data; } catch (e) { error.value = message(e); }
}
async function start() {
  error.value = ''; record.value = undefined; status.value = ''; runId.value = undefined; jobId.value = undefined; busy.value = true;
  try { const { data } = await api.post('/runs/paired-evaluations', payload()); runId.value = data.run_id; jobId.value = data.job_id; await poll(); }
  catch (e) { error.value = message(e); busy.value = false; }
}
async function poll() {
  if (disposed || !runId.value) return;
  if (timer) clearTimeout(timer);
  try {
    const { data } = await api.get(`/runs/paired-evaluations/${runId.value}`);
    status.value = data.status;
    busy.value = ['pending', 'running'].includes(data.status);
    record.value = data.record ?? undefined;
    if (data.error) error.value = data.error;
    if (data.status === 'completed') emit('completed', runId.value);
    if (busy.value && !disposed) timer = setTimeout(poll, 1500);
  } catch (e) { error.value = message(e); busy.value = false; }
}
async function cancel() {
  try { await api.delete(`/jobs/${jobId.value}`); await poll(); } catch (e) { error.value = message(e); }
}
onBeforeUnmount(() => { disposed = true; if (timer) clearTimeout(timer); });
</script>
<style scoped>
.paired-evaluation { padding: 1rem; border: 1px solid var(--surface-border); border-radius: .5rem; }
label { display: inline-flex; flex-direction: column; gap: .25rem; margin: .5rem 1rem .5rem 0; }
input { max-width: 8rem; } table { width: 100%; border-collapse: collapse; } th, td { text-align: left; padding: .5rem; border-bottom: 1px solid var(--surface-border); }
button { margin: .5rem; }
</style>
