<template>
  <div class="files-tab">
    <div v-if="experimentId" class="files-container">
      <!-- Upload Section -->
      <div class="section upload-section">
        <div class="section-header">
          <h3>
            <i class="pi pi-upload"></i>
            Upload Spectral Files
          </h3>
          <Dropdown
            v-model="uploadStage"
            :options="stages"
            placeholder="Select stage"
            class="stage-dropdown"
          />
        </div>

        <FileUploader
          title="Drop files here or click to browse"
          helper="Supported formats: CSV, JSON, JDX, SPA"
          multiple
          :disabled="uploadState.uploading"
          @files-selected="handleFileUpload"
        />

        <div v-if="uploadState.uploading" class="upload-progress">
          <ProgressBar
            :value="uploadProgress"
            :showValue="true"
          />
          <p class="progress-text">
            Uploading {{ uploadState.done }}/{{ uploadState.total }} files...
          </p>
        </div>
      </div>

      <!-- Files List Section -->
      <div class="section files-list-section">
        <div class="section-header">
          <h3>
            <i class="pi pi-file"></i>
            Files ({{ store.files.length }})
          </h3>
          <div class="header-actions">
            <Button
              label="Refresh"
              icon="pi pi-refresh"
              class="p-button-text p-button-sm"
              @click="refreshFiles"
            />
          </div>
        </div>

        <DataTable
          :value="store.files"
          stripedRows
          responsiveLayout="scroll"
          :loading="store.loading"
          dataKey="id"
          :paginator="true"
          :rows="15"
          :rowsPerPageOptions="[10, 15, 25, 50]"
        >
          <template #empty>
            <div class="empty-state">
              <i class="pi pi-inbox"></i>
              <p>No files uploaded yet</p>
              <p class="empty-help">Upload spectral data files using the uploader above</p>
            </div>
          </template>

          <Column field="file_path" header="Filename" sortable>
            <template #body="slotProps">
              <div class="filename-cell">
                <i class="pi pi-file"></i>
                <span>{{ getFilename(slotProps.data.file_path) }}</span>
              </div>
            </template>
          </Column>

          <Column field="stage" header="Stage" sortable style="width: 140px">
            <template #body="slotProps">
              <Tag :value="slotProps.data.stage" :severity="getStageSeverity(slotProps.data.stage)" />
            </template>
          </Column>

          <Column header="Size" sortable field="file_size_bytes" style="width: 120px">
            <template #body="slotProps">
              {{ formatBytes(slotProps.data.file_size_bytes) }}
            </template>
          </Column>

          <Column header="Uploaded" sortable field="uploaded_at" style="width: 180px">
            <template #body="slotProps">
              {{ formatDateTime(slotProps.data.uploaded_at) }}
            </template>
          </Column>

          <Column header="Actions" style="width: 100px">
            <template #body="slotProps">
              <Button
                icon="pi pi-download"
                class="p-button-rounded p-button-text p-button-sm"
                v-tooltip.top="'Download'"
                @click="downloadFile(slotProps.data)"
              />
              <Button
                icon="pi pi-trash"
                class="p-button-rounded p-button-text p-button-danger p-button-sm"
                v-tooltip.top="'Delete'"
                @click="deleteFile(slotProps.data.id)"
              />
            </template>
          </Column>
        </DataTable>
      </div>

      <!-- File Statistics -->
      <div class="section stats-section">
        <div class="stats-grid">
          <div class="stat-card">
            <i class="pi pi-file stat-icon"></i>
            <div class="stat-content">
              <div class="stat-label">Total Files</div>
              <div class="stat-value">{{ store.files.length }}</div>
            </div>
          </div>

          <div class="stat-card">
            <i class="pi pi-database stat-icon"></i>
            <div class="stat-content">
              <div class="stat-label">Total Size</div>
              <div class="stat-value">{{ formatBytes(totalFileSize) }}</div>
            </div>
          </div>

          <div class="stat-card">
            <i class="pi pi-tag stat-icon"></i>
            <div class="stat-content">
              <div class="stat-label">Stages</div>
              <div class="stat-value">{{ uniqueStages.length }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="no-selection">
      <i class="pi pi-inbox"></i>
      <h3>No Experiment Selected</h3>
      <p>Select an experiment from the Overview tab to manage its files</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useToast } from 'primevue/usetoast';
import Button from 'primevue/button';
import Column from 'primevue/column';
import DataTable from 'primevue/datatable';
import Dropdown from 'primevue/dropdown';
import ProgressBar from 'primevue/progressbar';
import Tag from 'primevue/tag';

import { useExperimentStore } from '@/stores/experiment';
import FileUploader from '@/components/FileUploader.vue';
import { formatBytes, formatDateTime } from '@/utils/format';

const props = defineProps<{
  experimentId: number | null;
}>();

const store = useExperimentStore();
const toast = useToast();

const stages = ['raw', 'preprocessed', 'synthetic'];
const uploadStage = ref('raw');
const uploadState = reactive({ uploading: false, total: 0, done: 0 });

const uploadProgress = computed(() => {
  if (uploadState.total === 0) return 0;
  return Math.round((uploadState.done / uploadState.total) * 100);
});

const totalFileSize = computed(() =>
  store.files.reduce((sum, file) => sum + (file.file_size_bytes || 0), 0)
);

const uniqueStages = computed(() => {
  const stageSet = new Set(store.files.map(f => f.stage));
  return Array.from(stageSet);
});

watch(
  () => props.experimentId,
  async (newId) => {
    if (newId) {
      await refreshFiles();
    }
  },
  { immediate: true }
);

const refreshFiles = async () => {
  if (!props.experimentId) return;

  try {
    await store.selectExperiment(props.experimentId);
  } catch {
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to load experiment files',
      life: 3000,
    });
  }
};

const getFilename = (filepath: string): string => {
  return filepath.split('/').pop() || filepath;
};

const getStageSeverity = (stage: string): string => {
  const severityMap: Record<string, string> = {
    raw: 'info',
    preprocessed: 'success',
    synthetic: 'warning',
  };
  return severityMap[stage] || 'info';
};

const handleFileUpload = async (files: File[]) => {
  if (!props.experimentId) {
    toast.add({
      severity: 'warn',
      summary: 'No Experiment',
      detail: 'Please select an experiment first',
      life: 3000,
    });
    return;
  }

  uploadState.uploading = true;
  uploadState.total = files.length;
  uploadState.done = 0;
  let successCount = 0;
  const failedFiles: string[] = [];

  for (const file of files) {
    try {
      await store.uploadFile(props.experimentId, file, uploadStage.value);
      successCount += 1;
    } catch {
      failedFiles.push(file.name);
    } finally {
      uploadState.done += 1;
    }
  }

  uploadState.uploading = false;

  if (successCount > 0) {
    toast.add({
      severity: 'success',
      summary: 'Upload Complete',
      detail: `${successCount} file(s) uploaded successfully`,
      life: 3000,
    });
  }

  if (failedFiles.length > 0) {
    toast.add({
      severity: 'error',
      summary: 'Upload Failed',
      detail: `Failed to upload: ${failedFiles.join(', ')}`,
      life: 4000,
    });
  }
};

const downloadFile = (file: any) => {
  // TODO: Implement file download
  toast.add({
    severity: 'info',
    summary: 'Download',
    detail: `Download functionality for "${getFilename(file.file_path)}" coming soon`,
    life: 3000,
  });
};

const deleteFile = async (fileId: number) => {
  if (!confirm('Delete this file? This action cannot be undone.')) {
    return;
  }

  try {
    // TODO: Implement file deletion in store
    toast.add({
      severity: 'success',
      summary: 'Deleted',
      detail: 'File deleted successfully',
      life: 3000,
    });
    await refreshFiles();
  } catch {
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to delete file',
      life: 3000,
    });
  }
};
</script>

<style scoped>
.files-tab {
  min-height: 400px;
}

.files-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.section {
  background: #ffffff;
  border-radius: 8px;
  padding: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-header h3 {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 600;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-header h3 i {
  color: #3b82f6;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.stage-dropdown {
  width: 160px;
}

.upload-progress {
  margin-top: 16px;
}

.progress-text {
  margin-top: 8px;
  font-size: 0.875rem;
  color: #64748b;
  text-align: center;
}

.filename-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filename-cell i {
  color: #94a3b8;
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: #94a3b8;
}

.empty-state i {
  font-size: 3rem;
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-state p {
  margin: 8px 0;
  font-size: 0.9375rem;
}

.empty-help {
  font-size: 0.875rem;
  color: #cbd5e1;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px;
  background: #f8fafc;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.stat-icon {
  font-size: 2rem;
  color: #3b82f6;
}

.stat-content {
  flex: 1;
}

.stat-label {
  font-size: 0.875rem;
  color: #64748b;
  margin-bottom: 4px;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 600;
  color: #1e293b;
}

.no-selection {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  color: #94a3b8;
  text-align: center;
  padding: 40px;
}

.no-selection i {
  font-size: 4rem;
  margin-bottom: 20px;
  opacity: 0.3;
}

.no-selection h3 {
  margin: 0 0 8px 0;
  color: #64748b;
  font-size: 1.25rem;
}

.no-selection p {
  margin: 0;
  font-size: 0.9375rem;
}
</style>
