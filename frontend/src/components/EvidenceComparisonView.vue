<template>
  <section aria-label="Shared evidence comparison">
    <p v-if="loading" role="status">Loading retained evaluation evidence…</p>
    <p v-else-if="error" role="alert">{{ error }} <button type="button" @click="load">Retry</button></p>
    <ScientificComparison v-else-if="evidence" :evidence="evidence" />
  </section>
</template>
<script setup lang="ts">
import { ref, watch } from 'vue';
import api from '@/api/client';
import { useScopedRequest } from '@/composables/useScopedRequest';
import { useAuthStore } from '@/stores/auth';
import ScientificComparison from '@/components/ScientificComparison.vue';
import type { EvidenceComparison, EvidenceReference } from '@/types/scientificComparison';
const props = defineProps<{ projectId: number; encodedReferences: string }>();
const evidence = ref<EvidenceComparison | null>(null);
const error = ref('');
const loading = ref(false);
const auth = useAuthStore();
const identity = () => [auth.user?.id, auth.token, props.projectId, props.encodedReferences];
const requests = useScopedRequest(identity);
async function load() {
  const request = requests.begin();
  evidence.value = null; error.value = ''; loading.value = true;
  try {
    if (props.encodedReferences.length > 16000) throw new Error('Select 2–10 retained evidence records.');
    const references = JSON.parse(props.encodedReferences) as EvidenceReference[];
    if (!Array.isArray(references) || references.length < 2 || references.length > 10) throw new Error('Select 2–10 retained evidence records.');
    const response = await api.post<EvidenceComparison>('/runs/compare-evidence', { references },
      { params: { project_id: props.projectId }, signal: request.signal });
    if (request.isCurrent()) evidence.value = response.data;
  } catch (failure: unknown) {
    if (!request.isCurrent()) return;
    const detail = (failure as {response?: {data?: {detail?: unknown}}}).response?.data?.detail;
    error.value = typeof detail === 'string' ? detail : 'The retained evidence is unavailable. Reopen the comparison from its source.';
  } finally { if (request.isCurrent()) loading.value = false; }
}
watch(identity, load, { immediate: true });
</script>
