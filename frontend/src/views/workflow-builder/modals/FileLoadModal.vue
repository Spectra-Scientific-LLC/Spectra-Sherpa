<template>
  <Dialog
    v-model:visible="visible"
    header="Load Data Source"
    :style="{ width: '80vw', maxWidth: '1100px' }"
    modal
    :draggable="false"
    class="file-load-modal"
  >
    <div class="file-load-container">
      <!-- Source Type Tabs -->
      <div class="source-tabs">
        <Button
          v-for="tab in sourceTabs"
          :key="tab.key"
          :label="tab.label"
          :icon="tab.icon"
          :disabled="tab.disabled"
          :class="['source-tab', { active: activeSource === tab.key }]"
          @click="selectSource(tab.key)"
        />
      </div>

      <!-- Experiment Browser -->
      <div v-if="activeSource === 'experiment'" class="source-panel">
        <div class="panel-header">
          <h3>Select from Experiment Files</h3>
          <InputText
            v-model="experimentSearch"
            placeholder="Search experiments..."
            class="search-input"
          />
        </div>

        <div class="experiment-browser">
          <Tree
            v-model:selectionKeys="selectedExpKeys"
            :value="experimentTreeNodes"
            selectionMode="checkbox"
            class="experiment-tree"
            :filter="true"
            filterPlaceholder="Filter..."
          >
            <template #default="{ node }">
              <div class="tree-node-content">
                <span class="node-label">{{ node.label }}</span>
                <span v-if="node.data?.file_type" class="file-type-badge">
                  {{ node.data.file_type }}
                </span>
              </div>
            </template>
          </Tree>
        </div>

        <div class="selection-summary">
          <span>{{ selectedExperimentCount }} files selected</span>
        </div>
      </div>

      <!-- NIST Library Browser -->
      <div v-if="activeSource === 'library'" class="source-panel">
        <div class="panel-header">
          <h3>Select from NIST Library</h3>
          <InputText
            v-model="librarySearch"
            placeholder="Search compounds..."
            class="search-input"
          />
        </div>

        <div class="library-browser">
          <DataTable
            v-model:selection="selectedLibraryEntries"
            :value="filteredLibraryEntries"
            selectionMode="multiple"
            dataKey="id"
            :scrollable="true"
            scrollHeight="400px"
            class="library-table"
          >
            <Column selectionMode="multiple" headerStyle="width: 3rem" />
            <Column field="compound_name" header="Compound" sortable />
            <Column field="cas_number" header="CAS Number" sortable />
            <Column field="resolution" header="Resolution" sortable />
            <Column header="Actions" :exportHeader="'Actions'" style="min-width: 8rem">
          <template #body="slotProps">
            <Button
              icon="pi pi-download"
              class="p-button-rounded p-button-text p-button-sm"
              @click.stop="downloadFile(slotProps.data)"
              v-tooltip.top="'Download Dataset'"
            />
          </template>
        </Column>
      </DataTable>
        </div>

        <div class="selection-summary">
          <span>{{ selectedLibraryEntries.length }} compounds selected</span>
        </div>
      </div>

      <!-- Upload New File -->
      <div v-if="activeSource === 'upload'" class="source-panel">
        <div class="panel-header">
          <h3>Upload New File</h3>
        </div>
        <div v-if="dataUploadDisabled" class="upload-disabled-notice">
          {{ uploadDisabledMessage }}
        </div>

        <div class="upload-zone">
          <FileUpload
            mode="advanced"
            :multiple="true"
            :accept="uploadAcceptList"
            :maxFileSize="50000000"
            :auto="false"
            :disabled="dataUploadDisabled"
            @select="onFileSelect"
            class="file-uploader"
          >
            <template #empty>
              <div class="upload-placeholder">
                <i class="pi pi-cloud-upload" />
                <p>Drag and drop files here</p>
                <small>{{ uploadFormatHint }}</small>
                <div v-if="disabledUploadFormats.length" class="upload-format-chips" aria-label="SCP-only formats">
                  <span
                    v-for="format in disabledUploadFormats"
                    :key="format.key"
                    class="upload-format-chip disabled"
                    :title="disabledUploadFormatTitle(format)"
                  >
                    {{ format.name }}
                  </span>
                </div>
              </div>
            </template>
          </FileUpload>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="modal-footer">
        <Button
          label="Cancel"
          class="p-button-text"
          @click="visible = false"
        />
        <Button
          label="Load Selected"
          icon="pi pi-check"
          class="p-button-success"
          :disabled="!hasSelection"
          @click="loadSelected"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
/* eslint-disable @typescript-eslint/no-explicit-any -- selection nodes combine tree nodes, uploads, and backend records with different shapes. */
import { ref, computed, onMounted } from "vue";
import Dialog from "primevue/dialog";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Tree from "primevue/tree";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import FileUpload from "primevue/fileupload";
import { useWorkflowStore, type LibraryDataset } from "@/stores/workflow";
import { useBuilderStore } from "@/stores/builder";
import { useAppConfig } from "@/composables/useAppConfig";
import { useDemoMode } from "@/composables/useDemoMode";
import { useToast } from "primevue/usetoast";

interface Props {
  modelValue: boolean;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (e: "update:modelValue", value: boolean): void;
  (e: "select", selection: SelectedData): void;
}>();

interface SelectedData {
  source: "experiment" | "library" | "upload";
  items: any[];
}

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

const workflowStore = useWorkflowStore();
const builderStore = useBuilderStore();
const appConfigApi = useAppConfig();
const appConfig = computed(() => appConfigApi.config?.value ?? appConfigApi.appConfig?.value ?? null);
const { isCapabilityDisabled } = appConfigApi;
const { isDemoMode, uploadsLastWeek, uploadsLimitWeek, uploadsResetWeekAt, fetchQuota } = useDemoMode();
const toast = useToast();

// Source tabs
type SourceType = "experiment" | "library" | "upload";
const uploadQuotaExhausted = computed(() => (
  isDemoMode.value
  && uploadsLastWeek.value !== null
  && uploadsLimitWeek.value > 0
  && uploadsLimitWeek.value < 999999
  && uploadsLastWeek.value >= uploadsLimitWeek.value
));
const uploadDisabledMessage = computed(() => {
  if (isCapabilityDisabled("data_upload")) return "File upload is disabled for this deployment.";
  if (uploadQuotaExhausted.value) {
    const reset = uploadsResetWeekAt.value ? new Date(uploadsResetWeekAt.value).toLocaleString() : "later";
    return `Demo upload limit reached. Your next upload is available ${reset}.`;
  }
  return "";
});
const dataUploadDisabled = computed(() => isCapabilityDisabled("data_upload") || uploadQuotaExhausted.value);
const uploadDataFormats = computed(() => appConfig.value?.dataFormats ?? null);
const uploadScpInstallCommand = computed(() => uploadDataFormats.value?.installScpCommand ?? "pip install spectra-sherpa[scp]");
const uploadAcceptList = computed(() => {
  const accepted = uploadDataFormats.value?.acceptedExtensions;
  if (accepted?.length) return accepted.join(",");
  return ".csv,.mat,.jdx,.dx,.npy,.npz";
});
const availableUploadFormats = computed(() => {
  const formats = uploadDataFormats.value?.formats;
  if (!formats?.length) return ["CSV", "MAT", "JCAMP-DX", "NumPy"];
  return formats.filter((format) => format.available).map((format) => format.name);
});
const disabledUploadFormats = computed(() => {
  const formats = uploadDataFormats.value?.formats ?? [];
  return formats.filter((format) => !format.available);
});
function disabledUploadFormatTitle(format: { name: string; unsupportedReason?: string; requiresScp?: boolean }): string {
  if (format.unsupportedReason) return format.unsupportedReason;
  if (format.requiresScp) return `${format.name} requires ${uploadScpInstallCommand.value}`;
  return `${format.name} is not available in this deployment.`;
}
const uploadFormatHint = computed(() => {
  const supported = availableUploadFormats.value.join(", ");
  const disabled = disabledUploadFormats.value;
  if (!disabled.length) return `Supported: ${supported}`;
  const hints: string[] = [];
  if (disabled.some((format) => format.requiresScp)) hints.push(`vendor formats require ${uploadScpInstallCommand.value}`);
  if (disabled.some((format) => format.requiresExport)) hints.push("OMNICxi/Paradigm containers require spectrum export first");
  return `Supported: ${supported}. ${hints.join("; ")}.`;
});
const sourceTabs = computed<{ key: SourceType; label: string; icon: string; disabled?: boolean }[]>(() => [
  { key: "experiment", label: "Experiments", icon: "pi pi-folder" },
  { key: "library", label: "NIST Library", icon: "pi pi-database" },
  { key: "upload", label: "Upload", icon: "pi pi-upload", disabled: dataUploadDisabled.value },
]);
const activeSource = ref<SourceType>("experiment");

function selectSource(source: SourceType): void {
  if (source === "upload" && dataUploadDisabled.value) {
    toast.add({
      severity: "warn",
      summary: "Upload Disabled",
      detail: uploadDisabledMessage.value || "File upload is disabled.",
      life: 4000,
    });
    return;
  }
  activeSource.value = source;
}

// Experiment browser
const experimentSearch = ref("");
const selectedExpKeys = ref<Record<string, boolean>>({});

const experimentTreeNodes = computed(() => {
  const datasets = workflowStore.availableDatasets;
  if (!datasets?.experiments) return [];

  return datasets.experiments
    .filter((exp) =>
      !experimentSearch.value ||
      exp.name.toLowerCase().includes(experimentSearch.value.toLowerCase())
    )
    .map((exp) => ({
      key: `exp-${exp.id}`,
      label: `exp_${String(exp.id).padStart(3, "0")}: ${exp.name}`,
      selectable: false,
      children: ["raw", "preprocessed", "synthetic"]
        .filter((stage) => exp.stages[stage as keyof typeof exp.stages]?.length > 0)
        .map((stage) => ({
          key: `exp-${exp.id}-${stage}`,
          label: `${stage}/`,
          selectable: false,
          children: exp.stages[stage as keyof typeof exp.stages].map((file) => ({
            key: `exp-${exp.id}-${stage}-${file.id}`,
            label: `${file.file_path.split("/").pop() || file.file_path}${datasetFileShapeSummary(file)}`,
            data: {
              source: "experiment",
              experiment_id: exp.id,
              stage: stage,
              file_id: file.id,
              file_path: file.file_path,
              file_type: file.file_type,
            },
          })),
        })),
    }));
});

function datasetFileShapeSummary(file: {
  n_samples?: number | null;
  n_features?: number | null;
  is_spectra?: boolean | null;
}): string {
  if (typeof file.n_samples !== "number" || typeof file.n_features !== "number") {
    return "";
  }
  const sampleLabel = file.is_spectra ? "spectra" : "samples";
  const featureLabel = file.is_spectra ? "points" : "features";
  return ` · ${file.n_samples} ${sampleLabel} × ${file.n_features} ${featureLabel}`;
}

const selectedExperimentCount = computed(() => {
  return Object.keys(selectedExpKeys.value).filter((key) =>
    key.includes("-") && selectedExpKeys.value[key]
  ).length;
});

// Library browser
const librarySearch = ref("");
const selectedLibraryEntries = ref<LibraryDataset[]>([]);

const filteredLibraryEntries = computed(() => {
  const datasets = workflowStore.availableDatasets;
  if (!datasets?.library) return [];

  if (!librarySearch.value) return datasets.library;

  const search = librarySearch.value.toLowerCase();
  return datasets.library.filter(
    (entry) =>
      entry.compound_name.toLowerCase().includes(search) ||
      entry.cas_number.toLowerCase().includes(search)
  );
});

// Upload
const uploadedFiles = ref<File[]>([]);
const onFileSelect = (event: any) => {
  if (dataUploadDisabled.value) {
    uploadedFiles.value = [];
    return;
  }
  uploadedFiles.value = event.files;
};

// Selection state
const hasSelection = computed(() => {
  if (activeSource.value === "experiment") {
    return selectedExperimentCount.value > 0;
  } else if (activeSource.value === "library") {
    return selectedLibraryEntries.value.length > 0;
  } else {
    return !dataUploadDisabled.value && uploadedFiles.value.length > 0;
  }
});

// Download a library dataset file
async function downloadFile(entry: LibraryDataset) {
  try {
    await builderStore.downloadDataset(entry.id, entry.compound_name || `dataset_${entry.id}`);
  } catch (error) {
    toast.add({ severity: "error", summary: "Download failed", detail: String(error), life: 4000 });
  }
}

// Load selected data
function loadSelected() {
  if (activeSource.value === "experiment") {
    // Collect selected file data from tree
    const items: any[] = [];
    const collectSelected = (nodes: any[]) => {
      for (const node of nodes) {
        if (node.data && selectedExpKeys.value[node.key]) {
          items.push(node.data);
        }
        if (node.children) {
          collectSelected(node.children);
        }
      }
    };
    collectSelected(experimentTreeNodes.value);

    emit("select", { source: "experiment", items });
  } else if (activeSource.value === "library") {
    emit("select", {
      source: "library",
      items: selectedLibraryEntries.value.map((entry) => ({
        source: "library",
        library_id: entry.id,
        compound_name: entry.compound_name,
        cas_number: entry.cas_number,
        file_path: entry.file_path,
      })),
    });
  } else {
    emit("select", {
      source: "upload",
      items: uploadedFiles.value,
    });
  }

  visible.value = false;
}

// Fetch datasets on mount
onMounted(async () => {
  await Promise.all([workflowStore.fetchAvailableDatasets(), fetchQuota()]);
});
</script>

<style scoped>
.file-load-modal :deep(.p-dialog-content) {
  padding: 0;
  background: #0f172a;
}

.file-load-container {
  display: flex;
  flex-direction: column;
  min-height: 550px;
}

.source-tabs {
  display: flex;
  gap: 8px;
  padding: 16px 20px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
}

.source-tab {
  background: transparent;
  border: 1px solid #334155;
  color: #94a3b8;
}

.source-tab:hover {
  background: #334155;
  color: #f8fafc;
}

.source-tab.active {
  background: #3b82f6;
  border-color: #3b82f6;
  color: #ffffff;
}

.source-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 20px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.panel-header h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: #f8fafc;
}

.search-input {
  width: 300px;
  background: #0f172a;
  border-color: #334155;
  color: #f8fafc;
}

.experiment-browser,
.library-browser {
  flex: 1;
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 8px;
  overflow: auto;
}

.experiment-tree {
  background: transparent;
  border: none;
  color: #f8fafc;
}

.experiment-tree :deep(.p-tree-container) {
  padding: 8px;
}

.experiment-tree :deep(.p-treenode-content) {
  padding: 8px;
  border-radius: 4px;
}

.experiment-tree :deep(.p-treenode-content:hover) {
  background: #334155;
}

.experiment-tree :deep(.p-checkbox .p-checkbox-box) {
  background: #0f172a;
  border-color: #475569;
}

.experiment-tree :deep(.p-checkbox .p-checkbox-box.p-highlight) {
  background: #3b82f6;
  border-color: #3b82f6;
}

.tree-node-content {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-type-badge {
  padding: 2px 6px;
  background: rgba(59, 130, 246, 0.2);
  color: #60a5fa;
  font-size: 0.7rem;
  border-radius: 4px;
  text-transform: uppercase;
}

.library-table {
  background: transparent;
}

.library-table :deep(.p-datatable-wrapper) {
  background: #0f172a;
}

.library-table :deep(.p-datatable-thead > tr > th) {
  background: #1e293b;
  color: #f8fafc;
  border-color: #334155;
}

.library-table :deep(.p-datatable-tbody > tr) {
  background: #0f172a;
  color: #f8fafc;
}

.library-table :deep(.p-datatable-tbody > tr:hover) {
  background: #334155;
}

.library-table :deep(.p-datatable-tbody > tr > td) {
  border-color: #334155;
}

.selection-summary {
  padding: 12px;
  background: #1e293b;
  border-radius: 0 0 8px 8px;
  font-size: 0.85rem;
  color: #94a3b8;
}

.upload-disabled-notice {
  border: 1px solid #fbbf24;
  background: #451a03;
  color: #fde68a;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 16px;
  font-size: 0.9rem;
}

.upload-zone {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.file-uploader {
  width: 100%;
}

.upload-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
  color: #64748b;
  border: 2px dashed #334155;
  border-radius: 8px;
  background: #0f172a;
}

.upload-placeholder i {
  font-size: 3rem;
  margin-bottom: 16px;
  color: #475569;
}

.upload-placeholder p {
  margin: 0 0 8px;
  font-size: 1rem;
  color: #94a3b8;
}

.upload-placeholder small {
  color: #64748b;
}

.upload-format-chips {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.375rem;
  margin-top: 0.75rem;
}

.upload-format-chip {
  border: 1px solid #334155;
  border-radius: 999px;
  font-size: 0.75rem;
  line-height: 1;
  padding: 0.3rem 0.5rem;
}

.upload-format-chip.disabled {
  color: #64748b;
  background: #111827;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

/* Dialog overrides for dark theme */
:deep(.p-dialog) {
  background: #1e293b;
  border: 1px solid #334155;
}

:deep(.p-dialog-header) {
  background: #1e293b;
  color: #f8fafc;
  border-bottom: 1px solid #334155;
}

:deep(.p-dialog-footer) {
  background: #1e293b;
  border-top: 1px solid #334155;
}

:deep(.p-dialog-header-icon) {
  color: #94a3b8;
}

:deep(.p-dialog-header-icon:hover) {
  background: #334155;
  color: #f8fafc;
}
</style>
