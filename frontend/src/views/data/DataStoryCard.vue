<template>
  <section class="data-story-card" :class="{ 'data-story-card--unavailable': !available }" aria-label="Data Story">
    <div class="data-story-heading">
      <div>
        <h3>Data Story <span class="ai-label">AI-assisted</span></h3>
      </div>
      <span v-if="available && loading" role="status">Generating…</span>
    </div>
    <div class="data-story-body" aria-live="polite">
      <p v-if="!available">{{ unavailableMessage }}</p>
      <p v-else-if="!ready">{{ unavailableReason || (sourceKey ? "Finishing dataset details…" : "Choose a dataset to review its story.") }}</p>
      <p v-else-if="dataStore.dataStoryText">{{ dataStore.dataStoryText }}</p>
      <p v-else-if="loading">Reviewing the selected spectra and sample metadata…</p>
      <p v-else>Generate a story for this dataset.</p>
    </div>
    <div v-if="available" class="data-story-question">
      <InputText
        v-model="dataStore.dataStoryContext"
        aria-label="Specific Data Story question"
        placeholder="Type in specific questions"
        :disabled="!ready || !available || loading"
        @keydown.enter="regenerate"
      />
      <Button
        label="Regenerate"
        icon="pi pi-sparkles"
        class="p-button-sm"
        :loading="loading"
        :disabled="!ready || !available || loading"
        @click="regenerate"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, watch } from "vue";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import { useAppConfig } from "@/composables/useAppConfig";
import { useDataStore } from "@/stores/data";
import type { SherpaDatasetDict } from "@/types";

const props = defineProps<{
  sourceKey: string | null;
  ready: boolean;
  inspectedSource?: SherpaDatasetDict | null;
  unavailableReason?: string | null;
}>();
const dataStore = useDataStore();
const { appMode, isFeatureEnabled } = useAppConfig();
const available = computed(() => isFeatureEnabled("sherpaDataStory") ||
  (appMode.value === "local" && isFeatureEnabled("chatAssistant")));
const unavailableMessage = computed(() => appMode.value === "local"
  ? "Configure a local chat endpoint in Settings to generate a Data Story."
  : "Data Story is unavailable for this deployment.");
const loading = computed(() => dataStore.dataStoryLoading);
let attemptedKey: string | null = null;
let displayedKey: string | null = null;

function requestStory(force = false): void {
  void dataStore.generateDataStory(props.inspectedSource, { cacheKey: props.sourceKey, force });
}

watch(
  () => [props.sourceKey, props.ready, available.value, loading.value] as const,
  ([key, ready, enabled, busy]) => {
    if (key !== displayedKey) {
      displayedKey = key;
      attemptedKey = null;
      dataStore.invalidateDataStory();
    }
    if (!key || !ready || !enabled || busy || attemptedKey === key) return;
    attemptedKey = key;
    requestStory();
  },
  { immediate: true },
);

function regenerate(): void {
  if (!props.sourceKey || !props.ready || !available.value || loading.value) return;
  attemptedKey = props.sourceKey;
  requestStory(true);
}
</script>

<style scoped>
.data-story-card {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  height: 260px;
  margin-bottom: 16px;
  padding: 16px;
}
.data-story-card--unavailable { height: auto; }
.data-story-card--unavailable .data-story-body p { margin-bottom: 0; }
.data-story-heading,
.data-story-question {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}
.data-story-heading h3 { margin: 0; }
.ai-label { color: var(--text-color-secondary); font-size: 0.7em; font-weight: 500; }
.data-story-body { flex: 1; min-height: 0; overflow: auto; white-space: pre-wrap; }
.data-story-body p { margin: 10px 0; }
.data-story-question input { flex: 1; min-width: 0; }
@media (max-width: 640px) {
  .data-story-card { height: auto; min-height: 260px; }
}
</style>
