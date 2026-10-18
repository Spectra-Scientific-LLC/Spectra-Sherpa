<template>
  <Dialog :visible="true" header="Review for promotion" modal :style="{ width: 'min(760px, 95vw)' }" @update:visible="emit('close')">
    <p v-if="loading" role="status">Verifying the fitted model and current evidence…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="review">
      <h3>Use existing fitted model</h3>
      <p>Artifact {{ artifactUid || `canonical:${canonicalArtifactId}` }}. This decision does not refit or add held-out samples.</p>
      <p>Fit on {{ review.population.fitted_count ?? 'an unrecorded number of' }} development samples. Held-out count: {{ review.population.held_out_count ?? 'not recorded' }}.</p>
      <p>{{ review.guidance.reason }}</p>
      <p v-if="review.fitting_plan?.state === 'complete_declared_development_fit'" role="status">All {{ review.fitting_plan.declared_development_count }} declared development samples from saved Run {{ review.source_run_id }} are already fitted in this exact artifact. Reuse it; an unchanged recipe and population do not need another fit.</p>
      <p v-else>Fitted state is available, but full coverage of a declared development population is not established here. Do not infer it from the fitted sample count.</p>
      <details v-if="!canonicalArtifactId"><summary>Change the final fitting recipe or population (optional)</summary>
        <ol><li>Open the training workflow and review its current data selection, exclusions, preprocessing and component count against the saved source run.</li><li>Keep validation and outlier-challenge samples excluded. Any deliberate population change needs a new recorded evaluation and review.</li><li>Save the intended recipe and explicitly click Run. This existing workflow action fits the model and saves a new run/artifact; opening the sheet never runs it.</li><li>Inspect the new run and return to Review for promotion for its new artifact. Previous qualification does not transfer automatically.</li></ol>
        <button v-if="review.workflow_id" type="button" @click="openWorkflow">Open workflow to prepare final fit</button>
      </details>
      <ul><li v-for="blocker in review.blockers" :key="blocker">{{ blocker }}</li></ul>
      <label>Intended use<textarea v-model="intendedUse" rows="2" maxlength="2000" /></label>
      <label>Qualification protocol
        <select v-model="protocol">
          <option value="exploratory">Exploratory use — no independent-validation claim</option>
          <option value="accepted_external_validation" :disabled="review.qualification.state !== 'accepted_under_declared_policy'">Existing accepted external-validation policy</option>
        </select>
      </label>
      <p>Analytical qualification: {{ review.qualification.state }}. {{ review.qualification.reason }}</p>
      <p v-if="protocol === 'accepted_external_validation'">The intended use must match the accepted dossier exactly: {{ review.qualification.intended_use }}</p>
      <label>Decision rationale<textarea v-model="rationale" rows="3" maxlength="4000" /></label>
      <details><summary>Scientific basis and limitations</summary>
        <p>{{ review.guidance.scientific_basis }}</p>
        <ul><li v-for="item in review.limitations" :key="item">{{ item }}</li></ul>
        <p>If the recipe or fitting population must change, return to the workflow, explicitly run the intended development population, then review the new artifact. Validation data must stay excluded from fitting.</p>
        <p v-if="canonicalArtifactId">This imported sheet applies frozen state. To change the fitting population, reproduce the development recipe in a training workflow and review its new artifact.</p>
      </details>
      <ScientificBasisHelp />
      <ModelOutlierChallenge v-if="projectId && (artifactUid || canonicalArtifactId)" :artifact-uid="artifactUid" :canonical-artifact-id="canonicalArtifactId" :project-id="projectId" />
      <details v-if="review.qualification.dataset_use"><summary>Recorded dataset use</summary>
        <p>{{ review.qualification.dataset_use.notice }}</p>
        <ul><li v-for="population in review.qualification.dataset_use.populations" :key="population.identity || 'unknown'">Results available: {{ population.results_revealed === true ? 'yes' : 'unknown' }}. Known selection use: {{ population.influenced_development === true ? 'yes' : 'unknown' }}. Recorded fitting overlap: {{ population.known_fit_overlap_count ?? 'unknown' }}.</li></ul>
      </details>
      <details v-if="projectId"><summary>Validate the frozen artifact (optional for exploratory use)</summary>
        <SavedModelQualification v-if="artifactUid" :artifact-uid="artifactUid" :project-id="projectId" :workflow-id="workflowId" :run-id="runId" @changed="load" />
        <QualificationPanel v-else-if="canonicalArtifactId && workflowId" :canonical-artifact-id="canonicalArtifactId" :workflow-id="workflowId" :project-id="projectId" />
        <button v-if="canonicalArtifactId" type="button" @click="load">Refresh review after validation</button>
      </details>
    </template>
    <template #footer>
      <Button label="Cancel" class="p-button-text" @click="emit('close')" />
      <Button label="Confirm deploy-ready" :loading="saving" :disabled="!review || !!review.blockers.length || !intendedUse.trim() || !rationale.trim()" @click="confirm" />
    </template>
  </Dialog>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import Dialog from 'primevue/dialog';
import Button from 'primevue/button';
import api from '@/api/client';
import { getErrorMessage } from '@/utils/errors';
import SavedModelQualification from './SavedModelQualification.vue';
import QualificationPanel from '@/views/deploy/QualificationPanel.vue';
import ScientificBasisHelp from './ScientificBasisHelp.vue';
import ModelOutlierChallenge from './ModelOutlierChallenge.vue';
const props = defineProps<{ artifactUid?: string; canonicalArtifactId?: number; projectId?: number | null; workflowId?: number | null; runId?: number | null }>();
const emit = defineEmits<{ close: []; confirmed: [] }>();
const router = useRouter();
async function openWorkflow() {
  if (!review.value?.workflow_id) return;
  await router.push({ path: '/workflow', query: { workflow_id: review.value.workflow_id, project_id: props.projectId ?? undefined, promotion_artifact: props.artifactUid, promotion_source_run: review.value.source_run_id ?? undefined } });
  emit('close');
}
type Review = {
  workflow_id: number | null;
  source_run_id?: number | null;
  fitting_plan?: { state: string; declared_development_count: number | null };
  review_digest: string; population: { fitted_count: number | null; held_out_count: number | null };
  qualification: { state: string; reason?: string; intended_use?: string; dataset_use?: { notice: string; populations: Array<{identity: string | null; results_revealed: boolean | null; influenced_development: boolean | null; known_fit_overlap_count: number | null}> } };
  blockers: string[]; limitations: string[]; guidance: { reason: string; scientific_basis: string };
};
const review = ref<Review | null>(null), loading = ref(false), saving = ref(false), error = ref('');
const intendedUse = ref(''), rationale = ref(''), protocol = ref('exploratory');
const endpoint = computed(() => props.canonicalArtifactId ? `/deploy/canonical-artifacts/${props.canonicalArtifactId}/promotion-review` : `/models/${props.artifactUid}/promotion-review`);
let generation = 0;
onBeforeUnmount(() => { generation++; });
async function load() {
  const current = ++generation;
  loading.value = true; review.value = null; error.value = '';
  try {
    const { data } = await api.get<Review>(endpoint.value);
    if (current !== generation) return;
    review.value = data;
    intendedUse.value = data.qualification.intended_use || '';
  } catch (e) { if (current === generation) error.value = getErrorMessage(e, 'Review unavailable.'); }
  finally { if (current === generation) loading.value = false; }
}
async function confirm() {
  if (!review.value || saving.value) return;
  const current = generation;
  saving.value = true; error.value = '';
  try {
    const promotion_review = {
      review_digest: review.value.review_digest, intended_use: intendedUse.value.trim(), protocol: protocol.value, rationale: rationale.value.trim(),
    };
    if (props.canonicalArtifactId) await api.post(endpoint.value, promotion_review);
    else await api.patch(`/models/${props.artifactUid}`, { is_deploy_ready: true, promotion_review });
    if (current !== generation) return;
    emit('confirmed');
  } catch (e) { if (current === generation) error.value = getErrorMessage(e, 'Readiness was not recorded. Reopen review if evidence changed.'); }
  finally { if (current === generation) saving.value = false; }
}
watch(() => [props.artifactUid, props.canonicalArtifactId], () => { intendedUse.value = ''; rationale.value = ''; protocol.value = 'exploratory'; void load(); }, { immediate: true });
</script>
<style scoped>
label { display: grid; gap: .4rem; margin: 1rem 0; }
textarea, select { width: 100%; padding: .5rem; }
details { margin: 1rem 0; }
</style>
