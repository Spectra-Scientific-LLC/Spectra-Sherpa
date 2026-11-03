<template>
  <aside aria-label="Final fitting context">
    <h3>Prepare final fit using the workflow Run action</h3>
    <p v-if="loading" role="status">Verifying the source model and saved run…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="review">
      <p>Source: saved Run {{ review.source_run_id ?? 'not recorded' }}, model {{ artifactUid }}. Fitted samples: {{ review.population.fitted_count ?? 'not recorded' }}; held-out samples: {{ review.population.held_out_count ?? 'not recorded' }}.</p>
      <p v-if="review.fitting_plan?.state === 'complete_declared_development_fit'">The existing model already fits all {{ review.fitting_plan.declared_development_count }} declared development samples.</p>
      <p>Editable workflow, not a pinned replay of the source run. Opening it has not started a fit; Run creates a new model for review.</p>
    </template>
  </aside>
</template>
<script setup lang="ts">
import { ref, watch } from 'vue';
import api from '@/api/client';
import { getErrorMessage } from '@/utils/errors';
import { useAuthStore } from '@/stores/auth';
import { useScopedRequest } from '@/composables/useScopedRequest';
const props = defineProps<{ artifactUid: string; workflowId: number; sourceRunId: number | null }>();
type Review = { workflow_id: number; source_run_id: number | null; population: { fitted_count: number | null; held_out_count: number | null }; fitting_plan?: { state: string; declared_development_count: number | null } };
const review = ref<Review | null>(null), loading = ref(false), error = ref('');
const auth = useAuthStore();
const identity = () => [auth.user?.id, auth.sessionRevision, props.artifactUid, props.workflowId, props.sourceRunId];
const requests = useScopedRequest(identity);
watch(identity, async () => {
  const request = requests.begin();
  review.value = null; loading.value = true; error.value = '';
  try {
    const { data } = await api.get<Review>(`/models/${encodeURIComponent(props.artifactUid)}/promotion-review`, { signal: request.signal });
    if (!request.isCurrent()) return;
    if (data.workflow_id !== props.workflowId || data.source_run_id !== props.sourceRunId) {
      throw new Error('The source model/run does not belong to this workflow. Return to Review for promotion.');
    }
    review.value = data;
  } catch (e) { if (request.isCurrent()) error.value = getErrorMessage(e, 'Source fitting context is unavailable.'); }
  finally { if (request.isCurrent()) loading.value = false; }
}, { immediate: true });
</script>
<style scoped>
aside { border: 1px solid var(--surface-border); border-radius: .4rem; padding: .8rem; margin: .8rem 0; }
</style>
