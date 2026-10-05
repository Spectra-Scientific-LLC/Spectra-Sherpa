<template>
  <section aria-label="Saved-model dry run">
    <p>Choose a settled file already inside this watch's folder. Sherpa applies the exact saved model without refitting.
      This check does not mark the file processed or enable monitoring.</p>
    <label>Representative file name <input v-model="fileName" placeholder="sample.csv" /></label>
    <Button label="Run check" :loading="busy" :disabled="!fileName || busy || loading" @click="run" />
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="receipt">
      <h3>Dry run: {{ receipt.status }}</h3>
      <p v-if="receipt.error" role="alert">{{ receipt.error }}</p>
      <p>Saved run #{{ receipt.run_id }} · {{ receipt.checked_at }}</p>
      <p>Folder: {{ receipt.folder }} · Pattern: {{ receipt.pattern }}</p>
      <p v-if="receipt.matches_current_settings === false" role="alert">This result describes earlier watch settings. You can run another check if useful.</p>
      <p>This optional check does not determine whether the watch can run.</p>
      <pre>{{ JSON.stringify(receipt.result_preview, null, 2) }}</pre>
      <Button label="Save deployment check" @click="save" />
      <details><summary>Model, input and runtime details</summary><pre>{{ JSON.stringify(receipt, null, 2) }}</pre></details>
    </template>
  </section>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue';
import Button from 'primevue/button';
import api from '@/api/client';
import { downloadText } from '@/utils/download';
const props = defineProps<{ watchId: number }>();
const loading = ref(true);
const fileName = ref(''); const busy = ref(false); const error = ref('');
interface Receipt { status: string; matches_current_settings?: boolean; last_activated_at?: string; error?: string; run_id: number; checked_at: string; folder: string; pattern: string; result_preview?: unknown }
const receipt = ref<Receipt | null>(null);
function detail(e: unknown): string {
  const value = e as { response?: { data?: { detail?: unknown } } };
  return typeof value.response?.data?.detail === 'string' ? value.response.data.detail : 'Dry-run check unavailable.';
}
async function run() {
  if (loading.value || busy.value) return;
  busy.value = true; error.value = ''; receipt.value = null;
  try { receipt.value = (await api.post(`/deploy/watches/${props.watchId}/dry-run`, { file_name: fileName.value })).data; }
  catch (e) { error.value = detail(e); }
  finally { busy.value = false; }
}
function save() { downloadText(JSON.stringify(receipt.value, null, 2), `watch-${props.watchId}-dry-run.json`, 'application/json'); }
onMounted(async () => {
  try { receipt.value = (await api.get(`/deploy/watches/${props.watchId}/dry-run`)).data.receipt; }
  catch (e) { error.value = detail(e); }
  finally { loading.value = false; }
});
</script>
<style scoped>
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 24rem; overflow: auto; }
input { margin: 0.5rem; }
</style>
