<template>
  <details class="campaign-reproduction">
    <summary>Reproduce the campaign with local reference data</summary>
    <p>Recompute validation and fitted-model predictions independently. This is separate from applying the model to new samples. Select the original signed package, independently obtained publisher keys, and your local reference file. No provider download is performed.</p>
    <form @submit.prevent="reproduce"><fieldset :disabled="running">
      <label>Campaign package (.sherpa)<input type="file" accept=".sherpa" required @change="selectFile($event, 'package')" /></label>
      <label>Publisher public keys (.json)<input type="file" accept=".json" required @change="selectFile($event, 'publisher_keys')" /></label>
      <label>Local reference file<input type="file" required @change="selectFile($event, 'fixture')" /></label>
      <label>Reference projection ID<input v-model="projection" required placeholder="public-corn-m5-moisture-v1" @input="report = null" /></label>
      <small>Use the same registered instrument and target projection as the campaign. For Corn M5 moisture: public-corn-m5-moisture-v1.</small>
      <button type="submit" :disabled="running">{{ running ? 'Reproducing…' : 'Run local reproduction' }}</button>
    </fieldset></form>
    <p v-if="error" role="alert">{{ error }}</p>
    <section v-if="report" aria-label="Local reproduction results">
      <p>Package {{ report.package_sha256 }}</p>
      <table><thead><tr><th>Check</th><th>Outcome</th><th>Explanation</th></tr></thead>
        <tbody><tr v-for="check in checks" :key="check.key"><th>{{ check.label }}</th><td>{{ report[check.key]?.status }}</td><td>{{ report[check.key]?.reason || '—' }}</td></tr></tbody>
      </table>
      <button type="button" @click="downloadReport">Download reproduction report</button>
    </section>
  </details>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import api from '@/api/client';

const props = defineProps<{ projectId: number }>();
const checks = [
  { key: 'integrity_verified', label: 'Package integrity' },
  { key: 'publisher_authenticated', label: 'Publisher authentication' },
  { key: 'validation_reproduced', label: 'Validation reproduced' },
  { key: 'application_reproduced', label: 'Application reproduced' },
] as const;
type Outcome = { status: string; reason: string | null };
type Report = { package_sha256: string } & Record<(typeof checks)[number]['key'], Outcome>;
type InputName = 'package' | 'fixture' | 'publisher_keys';
const files: Partial<Record<InputName, File>> = {};
const projection = ref('');
const running = ref(false);
const error = ref('');
const report = ref<Report | null>(null);
let requestGeneration = 0;
watch(() => props.projectId, () => { requestGeneration++; report.value = null; error.value = ''; running.value = false; });
function selectFile(event: Event, name: InputName) {
  files[name] = (event.target as HTMLInputElement).files?.[0];
  report.value = null;
}
async function reproduce() {
  const generation = ++requestGeneration;
  report.value = null;
  error.value = '';
  const body = new FormData();
  for (const name of ['package', 'fixture', 'publisher_keys'] as const) {
    if (!files[name]) { error.value = 'Select all three files.'; return; }
    body.append(name, files[name]);
  }
  body.append('projection_id', projection.value.trim());
  running.value = true;
  try {
    const result = await api.post<Report>(`/projects/${props.projectId}/reproduce-campaign`, body);
    if (generation === requestGeneration) report.value = result.data;
  } catch (failure: unknown) {
    const detail = (failure as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
    if (generation === requestGeneration) error.value = typeof detail === 'string' ? detail : 'Reproduction failed. Review the selected package, keys and reference projection.';
  } finally { if (generation === requestGeneration) running.value = false; }
}
function downloadReport() {
  const url = URL.createObjectURL(new Blob([JSON.stringify(report.value, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url; link.download = 'local-reproduction.json'; link.click();
  URL.revokeObjectURL(url);
}
</script>

<style scoped>
.campaign-reproduction { padding: 1rem; }
form, label { display: grid; gap: .5rem; margin-bottom: .75rem; }
th, td { padding: .5rem; text-align: left; }
</style>
