<template>
  <section aria-label="Shared evidence comparison">
    <p v-if="loading" role="status">Loading retained evaluation evidence…</p>
    <p v-else-if="error" role="alert">{{ error }} <button type="button" @click="load">Retry</button></p>
    <ScientificComparison v-else-if="evidence" :evidence="evidence" />
  </section>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import api from '@/api/client';
import ScientificComparison from '@/components/ScientificComparison.vue';
import type { EvidenceComparison, EvidenceReference } from '@/types/scientificComparison';
const props = defineProps<{ projectId: number; encodedReferences: string }>();
const evidence = ref<EvidenceComparison | null>(null);
const error = ref('');
const loading = ref(false);
let controller: AbortController | null = null;
let generation = 0;
async function load() {
  const current = ++generation;
  controller?.abort(); controller = new AbortController();
  evidence.value = null; error.value = ''; loading.value = true;
  try {
    if (props.encodedReferences.length > 16000) throw new Error('Select 2–10 retained evidence records.');
    const references = JSON.parse(props.encodedReferences) as EvidenceReference[];
    if (!Array.isArray(references) || references.length < 2 || references.length > 10) throw new Error('Select 2–10 retained evidence records.');
    const response = await api.post<EvidenceComparison>('/runs/compare-evidence', { references },
      { params: { project_id: props.projectId }, signal: controller.signal });
    if (current === generation) evidence.value = response.data;
  } catch (failure: unknown) {
    if (current !== generation) return;
    const detail = (failure as {response?: {data?: {detail?: unknown}}}).response?.data?.detail;
    error.value = typeof detail === 'string' ? detail : 'The retained evidence is unavailable. Reopen the comparison from its source.';
  } finally { if (current === generation) loading.value = false; }
}
watch(() => [props.projectId, props.encodedReferences], load, { immediate: true });
onBeforeUnmount(() => { ++generation; controller?.abort(); });
</script>
