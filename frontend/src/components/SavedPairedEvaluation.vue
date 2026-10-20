<template>
  <section aria-label="Saved paired evaluation">
    <p role="status">{{ status || 'Loading evaluation' }}. The source runs are unchanged.</p>
    <p v-if="error" role="alert">{{ error }} <button type="button" @click="load">Retry evaluation status</button></p>
    <p v-if="status === 'running' || status === 'pending'">This development evaluation is running. You may return to this saved run later.</p>
    <p v-else-if="status && status !== 'completed'">Incomplete evaluations do not support comparison. Restart from Runs → Compare creates a new record; resume is unavailable.</p>
    <PairedEvaluationResults v-if="record" :record="record" :run-id="runId" />
    <template v-if="record">
      <label v-if="record.paired_rmsecv_differences.length > 1">Inspect repetition
        <select v-model.number="repetition" @change="load"><option v-for="(_, index) in record.paired_rmsecv_differences" :key="index" :value="index">{{ index + 1 }}</option></select>
      </label>
      <ScientificComparison v-if="comparison" :evidence="comparison" />
      <p v-else>Row-level plots are unavailable for this retained evaluation.</p>
    </template>
  </section>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import api from '@/api/client';
import { useAuthStore } from '@/stores/auth';
import { useProjectStore } from '@/stores/project';
import { useScopedRequest } from '@/composables/useScopedRequest';
import { getErrorMessage } from '@/utils/errors';
import ScientificComparison from './ScientificComparison.vue';
import type { EvidenceComparison } from '@/types/scientificComparison';
import PairedEvaluationResults from './PairedEvaluationResults.vue';
import type { PairedEvaluationRecord } from '@/types/pairedEvaluation';
const props = defineProps<{ runId: number }>();
const comparison = ref<EvidenceComparison | null>(null), repetition = ref(0);
const status = ref(''), error = ref(''), record = ref<PairedEvaluationRecord | null>(null);
let timer: ReturnType<typeof setTimeout> | undefined;
const auth = useAuthStore(), project = useProjectStore();
const identity = () => [auth.user?.id, auth.token, project.currentProjectId, props.runId];
const reads = useScopedRequest(() => [...identity(), repetition.value], () => {
  if (timer) clearTimeout(timer);
});
async function load() {
  const request = reads.begin();
  if (timer) clearTimeout(timer);
  error.value = ''; comparison.value = null;
  try {
    const { data } = await api.get(`/runs/paired-evaluations/${props.runId}`, { params: { repetition: repetition.value }, signal: request.signal });
    if (!request.isCurrent()) return;
    status.value = data.status;
    record.value = data.status === 'completed' ? data.record : null;
    comparison.value = data.status === 'completed' ? data.scientific_comparison ?? null : null;
    if (record.value && record.value.schema_version !== 'spectrasherpa-paired-evaluation/1') {
      record.value = null; throw new Error('Saved evaluation format is unsupported.');
    }
    if (data.error) error.value = data.error;
    if (['pending', 'running'].includes(data.status)) timer = setTimeout(load, 1500);
  } catch (e) { if (request.isCurrent()) error.value = getErrorMessage(e, 'Evaluation status unavailable. Retry to read the saved result.'); }
}
watch(identity, () => { status.value = ''; record.value = null; comparison.value = null; repetition.value = 0; void load(); }, { immediate: true });
onBeforeUnmount(() => { if (timer) clearTimeout(timer); });
</script>
