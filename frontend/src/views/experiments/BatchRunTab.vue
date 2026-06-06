<template>
  <div class="batch-run-tab">
    <div v-if="isDemoMode" class="feature-preflight feature-preflight--error">
      <i class="pi pi-lock"></i>
      <span>Batch inference is disabled in demo mode.</span>
    </div>
    <div class="batch-form">
      <div class="selection-summary">
        <span class="eyebrow">Selected artifacts</span>
        <strong>{{ artifactUids.length }}</strong>
        <small v-if="artifactUids.length">Ready for batch inference.</small>
        <small v-else>Select one or more artifacts in the Artifacts tab.</small>
      </div>

      <div class="form-row">
        <div class="form-field">
          <label for="batch-dataset">My Dataset</label>
          <Dropdown
            inputId="batch-dataset"
            v-model="selectedExperimentId"
            :options="experiments"
            optionLabel="name"
            optionValue="id"
            placeholder="Select a project dataset"
            class="w-full"
            :loading="loadingExperiments"
          />
        </div>
        <div class="form-field">
          <label for="batch-scope">Scope</label>
          <Dropdown
            inputId="batch-scope"
            v-model="scope"
            :options="scopeOptions"
            optionLabel="label"
            optionValue="value"
            class="w-full"
          />
        </div>
      </div>

      <div
        v-if="featurePreflightMessage"
        class="feature-preflight"
        :class="{ 'feature-preflight--warn': featurePreflightSeverity === 'warn' }"
      >
        <i :class="featurePreflightSeverity === 'warn' ? 'pi pi-exclamation-triangle' : 'pi pi-info-circle'"></i>
        <span>{{ featurePreflightMessage }}</span>
      </div>

      <div class="form-field">
        <label for="batch-name">Run Name</label>
        <InputText
          id="batch-name"
          v-model="runName"
          :placeholder="suggestedName"
          class="w-full"
        />
      </div>

      <div class="form-actions">
        <Button
          label="Start Batch Run"
          icon="pi pi-play"
          :loading="submitting"
          :disabled="!canSubmit"
          @click="handleSubmit"
        />
      </div>
    </div>

    <div class="batch-info">
      <i class="pi pi-info-circle"></i>
      <p>
        Batch Run applies the selected saved artifacts to the same durable My Dataset.
        Feature-count and feature-axis contracts are validated before predictions are saved.
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import Button from "primevue/button";
import Dropdown from "primevue/dropdown";
import InputText from "primevue/inputtext";
import { useToast } from "primevue/usetoast";
import api from "@/api/client";
import { useDemoMode } from "@/composables/useDemoMode";
import { useProjectStore } from "@/stores/project";
import type { ExecutionRunSummary, ExperimentDetail, ExperimentSummary } from "@/types";
import { getErrorMessage } from "@/utils/errors";

interface BatchArtifactSummary {
  artifact_uid: string;
  name: string;
  display_name?: string | null;
  model_type: string;
  n_features: number;
}

interface BatchRunItemResult {
  artifact_uid: string;
  status: "completed" | "failed";
  metrics?: Record<string, unknown> | null;
  n_samples?: number | null;
  error?: string | null;
}

interface BatchRunResponse {
  status: "completed" | "partial" | "failed";
  run: ExecutionRunSummary | null;
  results: BatchRunItemResult[];
}

const props = withDefaults(
  defineProps<{
    artifactUids?: string[];
    artifacts?: BatchArtifactSummary[];
  }>(),
  {
    artifactUids: () => [],
    artifacts: () => [],
  },
);

const emit = defineEmits<{
  completed: [run: ExecutionRunSummary];
}>();

const projectStore = useProjectStore();
const toast = useToast();
const { isDemoMode } = useDemoMode();

const experiments = ref<ExperimentSummary[]>([]);
const loadingExperiments = ref(false);
const selectedExperimentId = ref<number | null>(null);
const scope = ref("all");
const runName = ref("");
const submitting = ref(false);
const selectedExperimentDetail = ref<ExperimentDetail | null>(null);
const loadingExperimentDetail = ref(false);

const scopeOptions = [
  { label: "All samples", value: "all" },
  { label: "Training samples", value: "train" },
  { label: "Test samples", value: "test" },
];

const suggestedName = computed(() => {
  const count = props.artifactUids.length;
  return count > 0
    ? `Batch inference — ${count} artifact${count === 1 ? "" : "s"}`
    : "Batch inference";
});

const canSubmit = computed(
  () =>
    props.artifactUids.length > 0 &&
    selectedExperimentId.value != null &&
    !submitting.value &&
    !isDemoMode.value,
);

const artifactFeatureCounts = computed(() => {
  const counts = new Set<number>();
  for (const artifact of props.artifacts) {
    if (Number.isFinite(artifact.n_features)) counts.add(Number(artifact.n_features));
  }
  return [...counts].sort((a, b) => a - b);
});

const selectedExperimentFeatureCount = computed(() =>
  extractFeatureCount(selectedExperimentDetail.value?.metadata ?? null),
);

const featurePreflightSeverity = computed<"info" | "warn">(() => {
  const artifactCounts = artifactFeatureCounts.value;
  const datasetCount = selectedExperimentFeatureCount.value;
  if (artifactCounts.length > 1 || (artifactCounts.length === 1 && datasetCount != null && artifactCounts[0] !== datasetCount)) {
    return "warn";
  }
  return "info";
});

const featurePreflightMessage = computed(() => {
  if (loadingExperimentDetail.value) return "Checking dataset feature count...";
  const artifactCounts = artifactFeatureCounts.value;
  if (props.artifactUids.length > 0 && props.artifacts.length === 0) {
    return "Selected artifact metadata is unavailable in this view; the server will validate feature contracts before saving.";
  }
  if (artifactCounts.length > 1) {
    return `Selected artifacts have different fitted feature counts (${artifactCounts.join(", ")}). This can be valid after preprocessing or feature selection; the server will validate each full feature contract.`;
  }
  if (selectedExperimentId.value == null || artifactCounts.length === 0) return "";
  const datasetCount = selectedExperimentFeatureCount.value;
  if (datasetCount == null) {
    return "Dataset feature count is not available for preflight; the server will validate the full feature contract before saving.";
  }
  if (artifactCounts[0] !== datasetCount) {
    return `Selected artifact's fitted feature count (${artifactCounts[0]}) differs from the dataset feature count (${datasetCount}). This can be valid after feature selection; the server will validate before saving.`;
  }
  return `Feature-count preflight passed (${datasetCount} features).`;
});

onMounted(fetchExperiments);

watch(
  () => projectStore.currentProjectId,
  () => {
    selectedExperimentId.value = null;
    selectedExperimentDetail.value = null;
    void fetchExperiments();
  },
);

watch(selectedExperimentId, (experimentId) => {
  selectedExperimentDetail.value = null;
  if (experimentId != null) void fetchExperimentDetail(experimentId);
});

async function fetchExperiments(): Promise<void> {
  loadingExperiments.value = true;
  try {
    const projectId = projectStore.currentProjectId;
    if (projectId == null) {
      experiments.value = [];
      return;
    }
    const response = await api.get<ExperimentSummary[]>("/experiments", {
      params: { project_id: projectId },
    });
    experiments.value = response.data;
  } catch (err) {
    experiments.value = [];
    toast.add({
      severity: "error",
      summary: "Datasets unavailable",
      detail: getErrorMessage(err, "Could not load project datasets."),
      life: 4000,
    });
  } finally {
    loadingExperiments.value = false;
  }
}

async function fetchExperimentDetail(experimentId: number): Promise<void> {
  loadingExperimentDetail.value = true;
  try {
    const response = await api.get<ExperimentDetail>(`/experiments/${experimentId}`);
    selectedExperimentDetail.value = response.data;
  } catch {
    selectedExperimentDetail.value = null;
  } finally {
    loadingExperimentDetail.value = false;
  }
}

function extractFeatureCount(metadata: Record<string, unknown> | null): number | null {
  if (!metadata) return null;
  const directKeys = ["n_features", "feature_count", "features"];
  for (const key of directKeys) {
    const value = metadata[key];
    if (typeof value === "number" && Number.isFinite(value) && value > 0) return Math.trunc(value);
  }
  const nestedDataset = metadata.dataset;
  if (nestedDataset && typeof nestedDataset === "object") {
    const nested = extractFeatureCount(nestedDataset as Record<string, unknown>);
    if (nested != null) return nested;
  }
  for (const key of ["shape", "dataset_shape", "X_shape", "x_shape"]) {
    const value = metadata[key];
    if (Array.isArray(value) && value.length >= 2) {
      const count = Number(value[1]);
      if (Number.isFinite(count) && count > 0) return Math.trunc(count);
    }
  }
  return null;
}

async function handleSubmit(): Promise<void> {
  if (!canSubmit.value || selectedExperimentId.value == null) return;
  submitting.value = true;
  try {
    const response = await api.post<BatchRunResponse>("/runs/batch", {
      artifact_uids: props.artifactUids,
      dataset: {
        experiment_id: selectedExperimentId.value,
        stage: "raw",
      },
      scope: scope.value,
      run_name: runName.value.trim() || suggestedName.value,
    });
    const failures = response.data.results.filter((result) => result.status === "failed");
    if (response.data.run) {
      emit("completed", response.data.run);
    }
    toast.add({
      severity: response.data.status === "completed" ? "success" : response.data.status === "partial" ? "warn" : "error",
      summary:
        response.data.status === "completed"
          ? "Batch run saved"
          : response.data.status === "partial"
            ? "Batch run partially saved"
            : "Batch run failed",
      detail: failures.length
        ? `${failures.length} artifact${failures.length === 1 ? "" : "s"} failed. ${
            response.data.run?.name ?? "No run was saved."
          }`
        : response.data.run?.name ?? "No run was saved.",
      life: response.data.status === "completed" ? 4000 : 7000,
    });
  } catch (err) {
    toast.add({
      severity: "error",
      summary: "Batch run failed",
      detail: getErrorMessage(err, "Could not apply selected artifacts."),
      life: 6000,
    });
  } finally {
    submitting.value = false;
  }
}
</script>

<style scoped>
.batch-run-tab {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.batch-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  max-width: 760px;
}

.selection-summary {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.15rem 0.75rem;
  align-items: baseline;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--surface-border);
}

.selection-summary .eyebrow {
  grid-column: 1 / -1;
}

.selection-summary strong {
  font-size: 1.75rem;
  font-weight: 500;
}

.selection-summary small {
  color: var(--text-color-secondary);
}

.form-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 180px;
  gap: 1rem;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.form-field label,
.eyebrow {
  color: var(--text-color-secondary);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.form-actions {
  display: flex;
  justify-content: flex-start;
}

.feature-preflight {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  max-width: 760px;
  padding: 0.65rem 0.75rem;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
  line-height: 1.35;
}

.feature-preflight--error {
  border-color: rgba(220, 38, 38, 0.4);
  color: var(--red-700, #b91c1c);
}

.feature-preflight--warn {
  border-color: rgba(217, 119, 6, 0.35);
  color: var(--yellow-800, #92400e);
}

.batch-info {
  display: flex;
  gap: 0.6rem;
  align-items: flex-start;
  max-width: 760px;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
  line-height: 1.45;
}

.batch-info p {
  margin: 0;
}

@media (max-width: 720px) {
  .form-row {
    grid-template-columns: 1fr;
  }
}
</style>
