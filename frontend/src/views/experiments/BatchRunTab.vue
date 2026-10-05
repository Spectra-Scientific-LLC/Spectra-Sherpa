<template>
  <div class="batch-run-tab">
    <PrivateBatchUpload v-if="effectiveArtifactUids.length === 1" :artifact-uid="effectiveArtifactUids[0]!" @completed="emit('completed', $event)" />
    <div class="batch-form">
      <div class="selection-summary">
        <span class="eyebrow">Selected models</span>
        <strong>{{ effectiveArtifactUids.length }}</strong>
        <small v-if="effectiveArtifactUids.length">Ready for batch prediction.</small>
        <small v-else>Select one or more fitted models.</small>
      </div>

      <div v-if="modelOptions.length" class="form-field">
        <label for="batch-models">Models</label>
        <MultiSelect
          inputId="batch-models"
          v-model="selectedArtifactUids"
          :options="modelOptions"
          optionLabel="label"
          optionValue="value"
          placeholder="Select fitted models"
          display="chip"
          class="w-full"
          :disabled="submitting"
        />
      </div>

      <div v-if="requiresAssetSelection" class="form-field">
        <label for="batch-scientific-asset">Scientific Result</label>
        <Dropdown
          inputId="batch-scientific-asset"
          v-model="selectedAssetId"
          :disabled="submitting || selectedDatasetViewId != null"
          :options="batchAssetOptions"
          optionLabel="title"
          optionValue="asset_id"
          placeholder="Select the exact result for every source file"
          class="w-full"
        >
          <template #option="{ option }">
            <span>{{ option.title || option.asset_id }} · {{ option.asset_id }} · {{ option.shape.join(" × ") }}</span>
          </template>
        </Dropdown>
        <small v-if="!assetSelectionError">The selected result identity is applied consistently to every file in this dataset.</small>
      </div>

      <p v-if="assetSelectionError && selectedDatasetViewId == null" role="alert" class="asset-error">{{ assetSelectionError }}</p>

      <div class="form-row">
        <div class="form-field">
          <label for="batch-dataset">My Dataset</label>
          <Dropdown
            inputId="batch-dataset"
            v-model="selectedExperimentId"
            :disabled="submitting"
            :options="experiments"
            optionLabel="name"
            optionValue="id"
            placeholder="Select a project dataset"
            class="w-full"
            :loading="loadingExperiments"
          />
          <small>Uses raw source files, or synthetic files when raw files are unavailable.</small>
        </div>
        <div v-if="selectedExperimentId != null" class="form-field">
          <label for="batch-dataset-definition">Definition</label>
          <Dropdown
            inputId="batch-dataset-definition"
            v-model="selectedDatasetViewId"
            :disabled="submitting"
            :options="savedViewOptions"
            optionLabel="name"
            optionValue="id"
            class="w-full"
            :loading="loadingDatasetViews"
          />
          <small v-if="datasetViewsError" role="alert">{{ datasetViewsError }}</small>
        </div>
        <div class="form-field">
          <label for="batch-scope">Scope</label>
          <Dropdown
            inputId="batch-scope"
            v-model="scope"
            :disabled="submitting || selectedDatasetViewId != null"
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
          label="Run Batch"
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
        Batch applies the selected fitted models to the chosen durable My Dataset.
        Feature-count and feature-axis contracts are validated before predictions are saved.
        Select up to eight models; the combined display is limited to 100,000 values. Larger inputs are refused without truncation.
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import Button from "primevue/button";
import Dropdown from "primevue/dropdown";
import InputText from "primevue/inputtext";
import MultiSelect from "primevue/multiselect";
import { useToast } from "primevue/usetoast";
import api from "@/api/client";
import PrivateBatchUpload from "./PrivateBatchUpload.vue";
import { useProjectStore } from "@/stores/project";
import type {
  ExecutionRunSummary,
  ExperimentDetail,
  ExperimentFile,
  ExperimentFileAssets,
  ExperimentSummary,
  ScientificAsset,
} from "@/types";
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
    artifacts?: BatchArtifactSummary[];
  }>(),
  {
    artifacts: () => [],
  },
);

const emit = defineEmits<{
  completed: [run: ExecutionRunSummary];
}>();

const projectStore = useProjectStore();
const toast = useToast();

const experiments = ref<ExperimentSummary[]>([]);
const loadingExperiments = ref(false);
const selectedExperimentId = ref<number | null>(null);
type SavedDatasetView = { id: number; name: string; selection: { stage: "raw" | "preprocessed" | "synthetic"; asset_id: string | null } };
const savedDatasetViews = ref<SavedDatasetView[]>([]);
const selectedDatasetViewId = ref<number | null>(null);
const loadingDatasetViews = ref(false);
const datasetViewsError = ref("");
const savedViewOptions = computed(() => [{ id: null, name: "Default" }, ...savedDatasetViews.value]);
const scope = ref("all");
const selectedStage = ref<"raw" | "preprocessed" | "synthetic">("raw");
const runName = ref("");
const submitting = ref(false);
const selectedArtifactUids = ref<string[]>([]);
const selectedExperimentDetail = ref<ExperimentDetail | null>(null);
const loadingExperimentDetail = ref(false);
const selectedAssetId = ref<string | null>(null);
const batchAssetOptions = ref<ScientificAsset[]>([]);
const requiresAssetSelection = ref(false);
const assetSelectionError = ref("");
let experimentRequest = 0;
let detailRequest = 0;
let datasetViewRequest = 0;
onBeforeUnmount(() => { ++experimentRequest; ++detailRequest; ++datasetViewRequest; });

const scopeOptions = [
  { label: "Included samples", value: "all" },
  { label: "Included training samples", value: "train" },
  { label: "Included test samples", value: "test" },
];

const modelOptions = computed(() => props.artifacts.map((artifact) => ({
  label: artifact.display_name || artifact.name,
  value: artifact.artifact_uid,
})));
const effectiveArtifactUids = computed(() => selectedArtifactUids.value);
const selectedArtifacts = computed(() => {
  const selected = new Set(effectiveArtifactUids.value);
  return props.artifacts.filter((artifact) => selected.has(artifact.artifact_uid));
});

const suggestedName = computed(() => {
  const count = effectiveArtifactUids.value.length;
  return count > 0
    ? `Batch prediction — ${count} model${count === 1 ? "" : "s"}`
    : "Batch prediction";
});

const canSubmit = computed(
  () =>
    effectiveArtifactUids.value.length > 0 && effectiveArtifactUids.value.length <= 8 &&
    selectedExperimentId.value != null &&
    !loadingExperiments.value && !loadingExperimentDetail.value &&
    selectedExperimentDetail.value != null &&
    (selectedDatasetViewId.value != null || !requiresAssetSelection.value || Boolean(selectedAssetId.value)) &&
    (selectedDatasetViewId.value != null || !assetSelectionError.value) &&
    !loadingDatasetViews.value &&
    !submitting.value,
);

const artifactFeatureCounts = computed(() => {
  const counts = new Set<number>();
  for (const artifact of selectedArtifacts.value) {
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
  if (selectedDatasetViewId.value != null) return "The saved definition's exact source and included cohort will be verified before prediction.";
  if (loadingExperimentDetail.value) return "Checking dataset feature count...";
  const artifactCounts = artifactFeatureCounts.value;
  if (effectiveArtifactUids.value.length > 0 && selectedArtifacts.value.length === 0) {
    return "Selected model metadata is unavailable in this view; the server will validate feature contracts before saving.";
  }
  if (artifactCounts.length > 1) {
    return `Selected models have different fitted feature counts (${artifactCounts.join(", ")}). This can be valid after preprocessing or feature selection; the server will validate each full feature contract.`;
  }
  if (selectedExperimentId.value == null || artifactCounts.length === 0) return "";
  const datasetCount = selectedExperimentFeatureCount.value;
  if (datasetCount == null) {
    return "Dataset feature count is not available for preflight; the server will validate the full feature contract before saving.";
  }
  if (artifactCounts[0] !== datasetCount) {
    return `The fitted model feature count (${artifactCounts[0]}) differs from the dataset feature count (${datasetCount}). This can be valid after feature selection; the server will validate before saving.`;
  }
  return `Feature-count preflight passed (${datasetCount} features).`;
});

onMounted(fetchExperiments);

watch(
  () => projectStore.currentProjectId,
  () => {
    selectedExperimentId.value = null;
    selectedArtifactUids.value = [];
    runName.value = "";
    selectedExperimentDetail.value = null;
    void fetchExperiments();
  },
);

watch(selectedExperimentId, (experimentId) => {
  ++detailRequest;
  loadingExperimentDetail.value = false;
  selectedExperimentDetail.value = null;
  selectedAssetId.value = null;
  batchAssetOptions.value = [];
  requiresAssetSelection.value = false;
  assetSelectionError.value = "";
  selectedDatasetViewId.value = null;
  savedDatasetViews.value = [];
  ++datasetViewRequest;
  if (experimentId != null) {
    void fetchExperimentDetail(experimentId);
    void fetchDatasetViews(experimentId);
  }
}, { flush: "sync" });

watch(selectedDatasetViewId, (viewId) => {
  const view = savedDatasetViews.value.find((candidate) => candidate.id === viewId);
  if (!view) return;
  scope.value = "all";
  selectedStage.value = view.selection.stage;
  selectedAssetId.value = view.selection.asset_id;
});

async function fetchDatasetViews(experimentId: number): Promise<void> {
  const request = ++datasetViewRequest;
  loadingDatasetViews.value = true;
  datasetViewsError.value = "";
  try {
    const response = await api.get<SavedDatasetView[]>(`/experiments/${experimentId}/dataset-views`);
    if (request === datasetViewRequest && selectedExperimentId.value === experimentId) {
      if (!Array.isArray(response.data)) throw new Error("Saved definition list is invalid.");
      savedDatasetViews.value = response.data;
    }
  } catch (error) {
    if (request === datasetViewRequest) datasetViewsError.value = getErrorMessage(error, "Saved definitions are unavailable.");
  } finally {
    if (request === datasetViewRequest) loadingDatasetViews.value = false;
  }
}

async function fetchExperiments(): Promise<void> {
  const request = ++experimentRequest;
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
    if (request !== experimentRequest || projectId !== projectStore.currentProjectId) return;
    experiments.value = response.data;
  } catch (err) {
    if (request !== experimentRequest) return;
    experiments.value = [];
    toast.add({
      severity: "error",
      summary: "Datasets unavailable",
      detail: getErrorMessage(err, "Could not load project datasets."),
      life: 4000,
    });
  } finally {
    if (request === experimentRequest) loadingExperiments.value = false;
  }
}

async function fetchExperimentDetail(experimentId: number): Promise<void> {
  const request = ++detailRequest;
  const projectId = projectStore.currentProjectId;
  const current = () => request === detailRequest && experimentId === selectedExperimentId.value && projectId === projectStore.currentProjectId;
  loadingExperimentDetail.value = true;
  try {
    const [detailResponse, filesResponse] = await Promise.all([
      api.get<ExperimentDetail>(`/experiments/${experimentId}`),
      api.get<ExperimentFile[]>(`/experiments/${experimentId}/files`, { params: { stage: "raw" } }),
    ]);
    if (!current()) return;
    if (selectedDatasetViewId.value == null) selectedStage.value = filesResponse.data.length ? "raw" : "synthetic";
    const files = filesResponse.data.length ? filesResponse.data : (await api.get<ExperimentFile[]>(
      `/experiments/${experimentId}/files`, { params: { stage: "synthetic" } },
    )).data;
    if (!current()) return;
    if (!files.length) throw new Error("Dataset has no importable source files.");
    const inventories = await Promise.all(
      files.map((file) =>
        api.get<ExperimentFileAssets>(`/experiments/${experimentId}/files/${file.id}/scientific-assets`),
      ),
    );
    const inventoryValues = inventories.map((response) => response.data);
    if (!current()) return;
    selectedExperimentDetail.value = detailResponse.data;
    requiresAssetSelection.value = inventoryValues.some((inventory) => inventory.assets.length > 1);
    if (requiresAssetSelection.value) {
      const commonIds = inventoryValues.reduce<Set<string>>((common, inventory, index) => {
        const ids = new Set(inventory.assets.map((asset) => asset.asset_id));
        return index === 0 ? ids : new Set([...common].filter((assetId) => ids.has(assetId)));
      }, new Set<string>());
      batchAssetOptions.value = (inventoryValues[0]?.assets ?? []).filter((asset) => commonIds.has(asset.asset_id));
      assetSelectionError.value = batchAssetOptions.value.length
        ? ""
        : "Files in this dataset do not share one scientific result identity. Split them into compatible datasets before batch inference.";
    }
  } catch (err) {
    if (!current()) return;
    selectedExperimentDetail.value = null;
    assetSelectionError.value = getErrorMessage(err, "Scientific result inventory could not be loaded.");
  } finally {
    if (current()) loadingExperimentDetail.value = false;
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
  const projectId = projectStore.currentProjectId;
  try {
    const response = await api.post<BatchRunResponse>("/runs/batch", {
      artifact_uids: effectiveArtifactUids.value,
      dataset: {
        experiment_id: selectedExperimentId.value,
        stage: selectedStage.value,
        asset_id: selectedDatasetViewId.value == null ? selectedAssetId.value : null,
      },
      ...(selectedDatasetViewId.value != null ? { dataset_view_id: selectedDatasetViewId.value } : {}),
      scope: scope.value,
      run_name: runName.value.trim() || suggestedName.value,
    });
    if (projectId !== projectStore.currentProjectId) return;
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
        ? `${failures.length} model${failures.length === 1 ? "" : "s"} failed. ${
            response.data.run?.name ?? "No run was saved."
          }`
        : response.data.run?.name ?? "No run was saved.",
      life: response.data.status === "completed" ? 4000 : 7000,
    });
  } catch (err) {
    toast.add({
      severity: "error",
      summary: "Batch run failed",
      detail: getErrorMessage(err, "Could not apply the selected models."),
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

.asset-error {
  color: var(--red-700, #b91c1c);
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
