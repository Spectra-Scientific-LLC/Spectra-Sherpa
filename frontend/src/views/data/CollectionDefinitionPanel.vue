<template>
  <details class="collection-definition-panel" @toggle="onToggle">
    <summary class="collection-definition-heading">
      <span>
        <strong>Source collection metadata</strong>
        <small>Original files and aligned sample annotations</small>
      </span>
    </summary>
    <div class="collection-definition-body">
      <div class="collection-definition-actions">
        <input
          v-if="canImportCollectionDefinition"
          ref="fileInput"
          class="definition-file-input"
          type="file"
          accept="application/json,.json"
          aria-label="Choose collection definition JSON"
          @change="previewSelectedFile"
        />
        <Button
          v-if="canImportCollectionDefinition"
          :label="receipt?.status === 'attached' ? 'Replace JSON' : 'Choose JSON'"
          icon="pi pi-file-import"
          class="p-button-sm p-button-outlined"
          :disabled="busy"
          @click="fileInput?.click()"
        />
        <Button
          v-if="
            canImportCollectionDefinition &&
            receipt &&
            receipt.status !== 'absent' &&
            receipt.status !== 'preview'
          "
          label="Remove"
          icon="pi pi-times"
          class="p-button-sm p-button-text p-button-danger"
          :disabled="busy"
          @click="removeDefinition"
        />
      </div>

      <div v-if="loading" class="definition-loading" role="status">
        <ProgressSpinner style="width: 22px; height: 22px" />
        Checking definition…
      </div>

      <div v-else-if="error" class="definition-message error" role="alert">
        <i class="pi pi-exclamation-triangle"></i>
        <span>{{ error }}</span>
        <Button label="Retry" class="p-button-sm p-button-text" @click="refresh" />
      </div>

      <template v-else-if="receipt">
        <div
          v-if="governedSource && receipt.status === 'absent'"
          class="definition-status attached"
          role="status"
        >
          <i class="pi pi-verified"></i>
          <div>
            <div class="definition-status-line">
              <Tag value="Catalog governed" severity="success" />
            </div>
            <p>
              Source membership and scientific identity are governed by this catalog reference.
              No separate collection-definition upload is needed.
            </p>
          </div>
        </div>
        <div
          v-else
          class="definition-status"
          :class="receipt.status"
          :role="isRefusal ? 'alert' : 'status'"
        >
          <i :class="statusIcon"></i>
          <div>
            <div class="definition-status-line">
              <Tag :value="statusLabel" :severity="statusSeverity" />
              <strong v-if="receipt.title">{{ receipt.title }}</strong>
            </div>
            <p>{{ receipt.message }}</p>
          </div>
        </div>

        <dl v-if="receipt.definition_sha256" class="definition-receipt">
          <div>
            <dt>Sources</dt>
            <dd>{{ sourceSummary }}</dd>
          </div>
          <div>
            <dt>Samples</dt>
            <dd>{{ receipt.row_count }} rows × {{ receipt.column_count }} columns</dd>
          </div>
          <div>
            <dt>Spectral matrix</dt>
            <dd>{{ shapeText }}</dd>
          </div>
          <div class="definition-columns">
            <dt>Sample metadata</dt>
            <dd>
              {{ receipt.column_count }} fields
              <button
                type="button"
                class="receipt-info"
                :title="metadataFieldsTitle"
                :aria-label="metadataFieldsTitle"
                :aria-expanded="sampleMetadataExpanded"
                @click="sampleMetadataExpanded = !sampleMetadataExpanded"
              >
                <i class="pi pi-info-circle" aria-hidden="true"></i>
              </button>
            </dd>
          </div>
          <div>
            <dt>Targets</dt>
            <dd>
              {{
                receipt.target_present || receipt.sample_classes_present
                  ? "Present — refused"
                  : "Absent"
              }}
            </dd>
          </div>
          <div class="definition-verification">
            <dt>Verification</dt>
            <dd class="verification-chips">
              <button
                v-for="item in verificationItems"
                :key="item.label"
                type="button"
                class="verification-chip"
                :title="item.title"
                :aria-label="item.title"
                :aria-pressed="selectedVerification === item.label"
                @click="
                  selectedVerification = selectedVerification === item.label ? null : item.label
                "
              >
                <i class="pi pi-verified" aria-hidden="true"></i>
                {{ item.label }}
              </button>
            </dd>
          </div>
        </dl>
        <p v-if="sampleMetadataExpanded" class="metadata-fields-detail" role="status">
          {{ metadataFieldsTitle }}
        </p>
        <p v-if="selectedVerificationDetail" class="verification-detail" role="status">
          {{ selectedVerificationDetail }}
        </p>

        <div
          v-if="canImportCollectionDefinition && receipt.status === 'preview'"
          class="preview-actions"
        >
          <p>
            Review this receipt, then attach the exact file. Previewing does not change the dataset.
          </p>
          <Button
            label="Attach verified definition"
            icon="pi pi-check"
            class="p-button-sm"
            :loading="saving"
            @click="attachPreview"
          />
          <Button
            label="Cancel"
            class="p-button-sm p-button-text"
            :disabled="saving"
            @click="cancelPreview"
          />
        </div>
      </template>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Button from "primevue/button";
import ProgressSpinner from "primevue/progressspinner";
import Tag from "primevue/tag";
import api from "@/api/client";
import { getErrorMessage } from "@/utils/errors";

export interface CollectionDefinitionReceipt {
  schema_version: "spectrasherpa-collection-definition-receipt/1";
  status: "absent" | "preview" | "attached" | "stale" | "invalid";
  experiment_id: number;
  definition_sha256: string | null;
  source_manifest_sha256: string | null;
  scientific_collection_sha256: string | null;
  file_count: number;
  row_count: number;
  column_count: number;
  columns: string[];
  shape: number[] | null;
  dataset_id: string | null;
  title: string | null;
  target_present: boolean;
  sample_classes_present: boolean;
  message: string;
}

const props = withDefaults(defineProps<{
  experimentId: number;
  refreshKey: string;
  fileTypes?: string[];
  allowDefinitionImport?: boolean;
  governedSource?: boolean;
}>(), { allowDefinitionImport: true, governedSource: false });
const canImportCollectionDefinition = computed(() => props.allowDefinitionImport !== false);


const emit = defineEmits<{
  changed: [receipt: CollectionDefinitionReceipt];
}>();

const fileInput = ref<HTMLInputElement | null>(null);
interface PendingPreview {
  file: File;
  experimentId: number;
  definitionSha256: string;
}

const pendingPreview = ref<PendingPreview | null>(null);
const receipt = ref<CollectionDefinitionReceipt | null>(null);
const loading = ref(false);
const saving = ref(false);
const error = ref<string | null>(null);
const selectedVerification = ref<string | null>(null);
const sampleMetadataExpanded = ref(false);
const expanded = ref(false);
let requestGeneration = 0;

interface RequestToken {
  generation: number;
  experimentId: number;
}

function beginRequest(): RequestToken {
  return { generation: ++requestGeneration, experimentId: props.experimentId };
}

function isCurrent(token: RequestToken): boolean {
  return token.generation === requestGeneration && token.experimentId === props.experimentId;
}

const busy = computed(() => loading.value || saving.value);
const isRefusal = computed(
  () => receipt.value?.status === "stale" || receipt.value?.status === "invalid",
);
const statusLabel = computed(() => {
  switch (receipt.value?.status) {
    case "attached":
      return "Attached and current";
    case "preview":
      return "Verified preview";
    case "stale":
      return "Stale — modeling blocked";
    case "invalid":
      return "Invalid — modeling blocked";
    default:
      return "Not attached";
  }
});
const statusSeverity = computed(() => {
  switch (receipt.value?.status) {
    case "attached":
      return "success";
    case "preview":
      return "info";
    case "stale":
    case "invalid":
      return "danger";
    default:
      return "secondary";
  }
});
const statusIcon = computed(() => {
  switch (receipt.value?.status) {
    case "attached":
      return "pi pi-verified";
    case "preview":
      return "pi pi-search";
    case "stale":
    case "invalid":
      return "pi pi-exclamation-triangle";
    default:
      return "pi pi-info-circle";
  }
});
const shapeText = computed(
  () => receipt.value?.shape?.join(" × ") || "Unavailable until sources match",
);
const sourceSummary = computed(() => {
  const count = receipt.value?.file_count ?? 0;
  const types = [
    ...new Set((props.fileTypes ?? []).map((value) => value.trim().toUpperCase()).filter(Boolean)),
  ];
  return types.length
    ? `${count} ${types.join(", ")} ${count === 1 ? "file" : "files"}`
    : `${count} files`;
});
const metadataFieldsTitle = computed(() =>
  receipt.value?.columns.length
    ? `Sample metadata fields: ${receipt.value.columns.join(", ")}`
    : "No sample metadata fields are recorded.",
);
const verificationItems = computed(() => {
  const current = receipt.value;
  if (!current?.definition_sha256) return [];
  return [
    {
      label: "Definition",
      title: `Definition identity — binds sample rows and annotations. SHA-256: ${current.definition_sha256}`,
    },
    ...(current.source_manifest_sha256
      ? [
          {
            label: "Source files",
            title: `Source-file identity — detects any source membership or byte change. SHA-256: ${current.source_manifest_sha256}`,
          },
        ]
      : []),
    ...(current.scientific_collection_sha256
      ? [
          {
            label: "Scientific matrix",
            title: `Scientific identity — binds the parsed matrix to its sources and definition. SHA-256: ${current.scientific_collection_sha256}`,
          },
        ]
      : []),
  ];
});
const selectedVerificationDetail = computed(
  () =>
    verificationItems.value.find((item) => item.label === selectedVerification.value)?.title ??
    null,
);

function formFor(file: File): FormData {
  const form = new FormData();
  form.append("file", file, file.name);
  return form;
}

async function refresh(): Promise<void> {
  const token = beginRequest();
  loading.value = true;
  saving.value = false;
  error.value = null;
  pendingPreview.value = null;
  sampleMetadataExpanded.value = false;
  try {
    const response = await api.get<CollectionDefinitionReceipt>(
      `/experiments/${token.experimentId}/collection-definition`,
    );
    if (isCurrent(token) && response.data.experiment_id === token.experimentId)
      receipt.value = response.data;
  } catch (caught: unknown) {
    if (isCurrent(token)) {
      receipt.value = null;
      error.value = getErrorMessage(
        caught,
        "Could not check the scientific collection definition.",
      );
    }
  } finally {
    if (isCurrent(token)) loading.value = false;
  }
}

async function previewSelectedFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] ?? null;
  input.value = "";
  if (!file) return;
  const token = beginRequest();
  loading.value = false;
  saving.value = true;
  error.value = null;
  pendingPreview.value = null;
  try {
    const response = await api.post<CollectionDefinitionReceipt>(
      `/experiments/${token.experimentId}/collection-definition/preview`,
      formFor(file),
    );
    if (
      isCurrent(token) &&
      response.data.experiment_id === token.experimentId &&
      response.data.definition_sha256
    ) {
      pendingPreview.value = {
        file,
        experimentId: token.experimentId,
        definitionSha256: response.data.definition_sha256,
      };
      receipt.value = response.data;
    }
  } catch (caught: unknown) {
    if (isCurrent(token)) {
      pendingPreview.value = null;
      error.value = getErrorMessage(caught, "The selected definition could not be verified.");
    }
  } finally {
    if (isCurrent(token)) saving.value = false;
  }
}

async function attachPreview(): Promise<void> {
  const pending = pendingPreview.value;
  if (
    !pending ||
    pending.experimentId !== props.experimentId ||
    pending.definitionSha256 !== receipt.value?.definition_sha256
  )
    return;
  const token = beginRequest();
  saving.value = true;
  error.value = null;
  try {
    const response = await api.put<CollectionDefinitionReceipt>(
      `/experiments/${token.experimentId}/collection-definition`,
      formFor(pending.file),
    );
    if (isCurrent(token) && response.data.experiment_id === token.experimentId) {
      pendingPreview.value = null;
      receipt.value = response.data;
      emit("changed", response.data);
    }
  } catch (caught: unknown) {
    if (isCurrent(token)) {
      error.value = getErrorMessage(caught, "The verified definition could not be attached.");
    }
  } finally {
    if (isCurrent(token)) saving.value = false;
  }
}

async function removeDefinition(): Promise<void> {
  const token = beginRequest();
  saving.value = true;
  error.value = null;
  try {
    const response = await api.delete<CollectionDefinitionReceipt>(
      `/experiments/${token.experimentId}/collection-definition`,
    );
    if (isCurrent(token) && response.data.experiment_id === token.experimentId) {
      pendingPreview.value = null;
      receipt.value = response.data;
      emit("changed", response.data);
    }
  } catch (caught: unknown) {
    if (isCurrent(token)) {
      error.value = getErrorMessage(caught, "The collection definition could not be removed.");
    }
  } finally {
    if (isCurrent(token)) saving.value = false;
  }
}

function cancelPreview(): void {
  void refresh();
}

function onToggle(event: Event): void {
  expanded.value = (event.target as HTMLDetailsElement).open;
  if (expanded.value && !receipt.value && !loading.value && !error.value) void refresh();
}

watch(
  () => [props.experimentId, props.refreshKey] as const,
  () => {
    ++requestGeneration;
    receipt.value = null;
    error.value = null;
    pendingPreview.value = null;
    loading.value = false;
    saving.value = false;
    if (expanded.value) void refresh();
  },
  { immediate: true },
);
</script>

<style scoped>
.collection-definition-panel {
  margin-top: 1rem;
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  background: var(--surface-card);
}

.collection-definition-panel > summary {
  align-items: center;
  cursor: pointer;
  display: flex;
  gap: 0.7rem;
  list-style: none;
  padding: 0.85rem 1rem;
}

.collection-definition-panel > summary::-webkit-details-marker {
  display: none;
}

.collection-definition-panel > summary::before {
  border-bottom: 2px solid currentColor;
  border-right: 2px solid currentColor;
  content: "";
  flex: 0 0 auto;
  height: 0.42rem;
  transform: rotate(-45deg);
  transition: transform 120ms ease;
  width: 0.42rem;
}

.collection-definition-panel[open] > summary::before {
  transform: rotate(45deg);
}

.collection-definition-panel[open] > summary {
  border-bottom: 1px solid var(--surface-border);
}

.collection-definition-body {
  padding: 1rem;
}

.collection-definition-heading,
.collection-definition-actions,
.definition-status,
.definition-status-line,
.definition-loading,
.definition-message,
.preview-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.collection-definition-heading {
  justify-content: space-between;
}

.collection-definition-heading > span {
  flex: 1;
}

.collection-definition-heading strong,
.collection-definition-heading small {
  display: block;
}

.collection-definition-heading small,
.definition-status p,
.preview-actions p {
  margin: 0.2rem 0 0;
  color: var(--text-color-secondary);
  font-size: 0.85rem;
}

.definition-file-input {
  display: none;
}

.definition-loading,
.definition-message,
.definition-status,
.preview-actions {
  margin-top: 0.9rem;
  padding: 0.75rem;
  border-radius: 8px;
  background: var(--surface-ground);
}

.definition-status.attached {
  border-left: 4px solid var(--green-500);
}
.definition-status.preview {
  border-left: 4px solid var(--blue-500);
}
.definition-status.stale,
.definition-status.invalid,
.definition-message.error {
  border-left: 4px solid var(--red-500);
}

.definition-receipt {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.7rem;
  margin: 0.9rem 0 0;
}

.definition-receipt > div {
  min-width: 0;
  padding: 0.65rem;
  border-radius: 7px;
  background: var(--surface-ground);
}

.definition-receipt dt {
  color: var(--text-color-secondary);
  font-size: 0.72rem;
  text-transform: uppercase;
}

.definition-receipt dd {
  margin: 0.25rem 0 0;
  overflow-wrap: anywhere;
}

.definition-verification {
  grid-column: 1 / -1;
}

.receipt-info {
  align-items: center;
  background: transparent;
  border: 0;
  display: inline-flex;
  margin-left: 0.3rem;
  padding: 0.15rem;
  color: var(--primary-color);
  cursor: pointer;
}

.verification-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}

.verification-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--surface-border);
  border-radius: 999px;
  background: var(--surface-card);
  color: var(--text-color-secondary);
  font-size: 0.78rem;
  cursor: help;
  font: inherit;
}

.verification-chip i {
  color: var(--green-500);
}

.verification-detail,
.metadata-fields-detail {
  margin: 0.55rem 0 0;
  padding: 0.55rem 0.7rem;
  border-radius: 7px;
  background: var(--surface-ground);
  overflow-wrap: anywhere;
  font-size: 0.78rem;
}

.preview-actions {
  flex-wrap: wrap;
}

.preview-actions p {
  flex: 1 1 360px;
}

@media (max-width: 800px) {
  .collection-definition-heading {
    align-items: flex-start;
    flex-direction: column;
  }
  .definition-receipt {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
