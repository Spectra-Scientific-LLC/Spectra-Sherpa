<template>
  <details class="processing-step-filter" open>
    <summary>Steps Selection <span>{{ state.selections.value.length }} selected</span>
      <button type="button" class="step-help" aria-label="About Steps Selection"
        title="Packaged Datasets → Data Views → Steps Selection filters the comparison. Select a box to add its spectra; select again to remove. The box matches its curves; its border indicates recipe. Hover a box for metadata. Preview samples up to four original acquisitions per phase within the display row limit; selection includes the full group."
        @click.stop.prevent="showHelp = !showHelp">?</button>
    </summary>
    <p v-if="showHelp" class="filter-note">Select boxes to add or remove groups from Comparison preview. Box fill matches curves; borders indicate recipe. Hover for metadata. Preview samples up to four original acquisitions per phase within the display row limit; selection includes the full group.</p>
    <p v-if="state.loading.value" role="status">Loading processing steps…</p>
    <p v-if="state.error.value" role="alert">{{ state.error.value }}</p>
    <BoschStepMatrix hide-instructions :entries="state.entries.value" v-model="state.selections.value"
      :group-colors="state.groupColors.value" />
  </details>
</template>
<script setup lang="ts">
import { ref, watch } from "vue";
import type { DatasetPlotSource, ExperimentFile } from "@/types";
import BoschStepMatrix from "./BoschStepMatrix.vue";
import { useProcessingStepSelection } from "./composables/useProcessingStepSelection";
const showHelp = ref(false);
const props = defineProps<{ experimentId: number; projectId: number | null; files: ExperimentFile[]; scopeKey: string; fileSelections: Record<number, readonly {id: number}[] | null> }>();
const emit = defineEmits<{ preview: [sources: DatasetPlotSource[]]; loading: [value: boolean]; error: [value: string | null]; sources: [ids: number[]] }>();
const state = useProcessingStepSelection(
  () => [props.scopeKey, props.experimentId, JSON.stringify(props.fileSelections)],
  () => props.projectId,
);
watch(() => [props.scopeKey, props.experimentId, props.files, props.fileSelections] as const,
  async () => { await state.load(Object.keys(props.fileSelections ?? {}).map(Number), props.files, props.experimentId, props.fileSelections); emit("sources", state.sourceExperimentIds.value); }, { immediate: true });
watch(state.selections, () => { void state.compare(); });
watch([state.preview, state.groupColors], () => emit('preview', state.preview.value), { immediate: true });
watch(state.previewLoading, value => emit('loading', value), { immediate: true });
watch(state.previewError, value => emit('error', value), { immediate: true });
</script>
<style scoped>
.processing-step-filter { margin-bottom: 1rem; padding: 1rem; border: 1px solid var(--ss-border-strong); border-radius: 8px; background: var(--ss-surface); }
summary { cursor: pointer; font-weight: 600; }
.step-help { margin-left: 0.5rem; border: 1px solid var(--ss-border-strong); border-radius: 50%; background: var(--ss-surface); color: var(--ss-text); cursor: help; }
summary span { margin-left: 1rem; color: var(--ss-text-muted); font-weight: normal; }
.filter-note { color: var(--ss-text-muted); font-size: 0.85rem; }
</style>
