<template>
  <div class="versions-tab">
    <div v-if="experimentId" class="versions-container">
      <!-- Version History Section -->
      <div class="section versions-section">
        <div class="section-header">
          <h3>
            <i class="pi pi-history"></i>
            Version History
          </h3>
          <Button
            label="Create Snapshot"
            icon="pi pi-camera"
            class="p-button-sm"
            @click="openVersionDialog"
          />
        </div>

        <div v-if="store.versions.length > 0" class="version-tree-container">
          <VersionTree
            :versions="formattedVersions"
            @restore="restoreVersion"
          />
        </div>
        <div v-else class="empty-state">
          <i class="pi pi-history"></i>
          <p>No version snapshots yet</p>
          <p class="empty-help">Create a snapshot to preserve the current state</p>
        </div>
      </div>

      <!-- Export Section -->
      <div class="section export-section">
        <div class="section-header">
          <h3>
            <i class="pi pi-download"></i>
            Export Experiment
          </h3>
        </div>

        <p class="section-description">
          Export experiment data, metadata, and files in various formats
        </p>

        <div class="export-options">
          <div class="export-card">
            <div class="export-icon">
              <i class="pi pi-file"></i>
            </div>
            <div class="export-info">
              <h4>JSON Export</h4>
              <p>Full experiment data including metadata and file references</p>
            </div>
            <Button
              label="Export JSON"
              icon="pi pi-download"
              class="p-button-outlined"
              @click="exportExperiment('json')"
            />
          </div>

          <div class="export-card">
            <div class="export-icon">
              <i class="pi pi-table"></i>
            </div>
            <div class="export-info">
              <h4>CSV Export</h4>
              <p>Separate CSV files for file list and version history</p>
            </div>
            <Button
              label="Export CSV"
              icon="pi pi-download"
              class="p-button-outlined"
              @click="exportExperiment('csv')"
            />
          </div>

          <div class="export-card">
            <div class="export-icon">
              <i class="pi pi-file-pdf"></i>
            </div>
            <div class="export-info">
              <h4>ZIP Archive</h4>
              <p>Complete package with all data and files</p>
            </div>
            <Button
              label="Export ZIP"
              icon="pi pi-download"
              class="p-button-outlined"
              @click="exportExperiment('zip')"
            />
          </div>
        </div>

        <div class="export-stats">
          <div class="stat-item">
            <i class="pi pi-database"></i>
            <span>Total export size: {{ formatBytes(totalFileSize) }}</span>
          </div>
          <div class="stat-item">
            <i class="pi pi-file"></i>
            <span>{{ store.files.length }} file(s)</span>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="no-selection">
      <i class="pi pi-inbox"></i>
      <h3>No Experiment Selected</h3>
      <p>Select an experiment from the Overview tab to view versions and export options</p>
    </div>

    <!-- Version Snapshot Dialog -->
    <Dialog
      v-model:visible="versionDialogVisible"
      header="Create Version Snapshot"
      :modal="true"
      style="width: min(500px, 90vw)"
    >
      <div class="dialog-content">
        <div class="field">
          <label for="version-name">Version Name <span class="required">*</span></label>
          <InputText
            id="version-name"
            v-model="versionDraft.name"
            placeholder="e.g., v1.0, baseline"
          />
        </div>

        <div class="field">
          <label for="version-desc">Description</label>
          <Textarea
            id="version-desc"
            v-model="versionDraft.description"
            rows="3"
            placeholder="Describe what makes this version unique"
          />
        </div>

        <div class="field">
          <label for="version-stages">Include Stages</label>
          <MultiSelect
            id="version-stages"
            v-model="versionDraft.stages"
            :options="stages"
            placeholder="Select stages to include"
            display="chip"
          />
        </div>
      </div>

      <template #footer>
        <Button
          label="Cancel"
          icon="pi pi-times"
          class="p-button-text"
          @click="versionDialogVisible = false"
        />
        <Button
          label="Create Snapshot"
          icon="pi pi-check"
          :disabled="!versionDraft.name"
          @click="createVersion"
        />
      </template>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useToast } from 'primevue/usetoast';
import Button from 'primevue/button';
import Dialog from 'primevue/dialog';
import InputText from 'primevue/inputtext';
import MultiSelect from 'primevue/multiselect';
import Textarea from 'primevue/textarea';

import { useExperimentStore } from '@/stores/experiment';
import VersionTree from '@/components/VersionTree.vue';
import { downloadBlob, downloadCsv, downloadJson } from '@/utils/download';
import { formatBytes, formatDateTime } from '@/utils/format';

import { zipSync, strToU8 } from 'fflate';

const props = defineProps<{
  experimentId: number | null;
}>();

const store = useExperimentStore();
const toast = useToast();

const versionDialogVisible = ref(false);
const stages = ['raw', 'preprocessed', 'synthetic'];

const versionDraft = ref({
  name: '',
  description: '',
  stages: ['raw'] as string[],
});

const formattedVersions = computed(() =>
  store.versions.map((version) => ({
    ...version,
    created_at: formatDateTime(version.created_at),
  }))
);

const totalFileSize = computed(() =>
  store.files.reduce((sum, file) => sum + (file.file_size_bytes || 0), 0)
);

watch(
  () => props.experimentId,
  async (newId) => {
    if (newId) {
      await loadVersions();
    }
  },
  { immediate: true }
);

const loadVersions = async () => {
  if (!props.experimentId) return;

  try {
    await store.selectExperiment(props.experimentId);
  } catch {
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to load version history',
      life: 3000,
    });
  }
};

const openVersionDialog = () => {
  versionDraft.value = {
    name: `v${store.versions.length + 1}`,
    description: '',
    stages: ['raw'],
  };
  versionDialogVisible.value = true;
};

const createVersion = async () => {
  if (!props.experimentId || !versionDraft.value.name) {
    return;
  }

  try {
    await store.createVersion(
      props.experimentId,
      versionDraft.value.name,
      versionDraft.value.description,
      versionDraft.value.stages
    );

    toast.add({
      severity: 'success',
      summary: 'Snapshot Created',
      detail: `Version "${versionDraft.value.name}" created successfully`,
      life: 3000,
    });

    versionDialogVisible.value = false;
  } catch {
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to create version snapshot',
      life: 3000,
    });
  }
};

const restoreVersion = async (versionName: string) => {
  if (!props.experimentId) {
    return;
  }

  if (!confirm(`Restore version "${versionName}"? This will overwrite current files.`)) {
    return;
  }

  try {
    await store.restoreVersion(props.experimentId, versionName);
    toast.add({
      severity: 'success',
      summary: 'Restored',
      detail: `Version "${versionName}" restored successfully`,
      life: 3000,
    });
  } catch {
    toast.add({
      severity: 'error',
      summary: 'Error',
      detail: 'Failed to restore version',
      life: 3000,
    });
  }
};

const exportExperiment = (format: 'json' | 'csv' | 'zip') => {
  if (!store.currentExperiment) {
    return;
  }

  // Size validation
  const maxBytes = 1024 * 1024 * 1024; // 1 GB
  const warnBytes = 500 * 1024 * 1024; // 500 MB

  if (totalFileSize.value > maxBytes) {
    toast.add({
      severity: 'warn',
      summary: 'Export Too Large',
      detail: 'Export exceeds the 1 GB limit',
      life: 4000,
    });
    return;
  }

  if (totalFileSize.value > warnBytes) {
    const proceed = confirm(
      'This export is over 500 MB and may take a while. Continue?'
    );
    if (!proceed) {
      return;
    }
  }

  const payload = {
    experiment: store.currentExperiment,
    files: store.files,
    versions: store.versions,
  };

  if (format === 'json') {
    downloadJson(payload, `experiment_${store.currentExperiment.id}.json`);
    toast.add({
      severity: 'success',
      summary: 'Export Complete',
      detail: 'JSON file downloaded',
      life: 3000,
    });
    return;
  }

  const filesCsv = [
    ['file_path', 'stage', 'size_bytes'],
    ...store.files.map((file) => [
      file.file_path,
      file.stage,
      file.file_size_bytes.toString(),
    ]),
  ];

  const versionsCsv = [
    ['version_name', 'description', 'created_at', 'file_count'],
    ...store.versions.map((ver) => [
      ver.version_name,
      ver.description || '',
      ver.created_at,
      ver.file_count.toString(),
    ]),
  ];

  if (format === 'csv') {
    downloadCsv(filesCsv, `experiment_${store.currentExperiment.id}_files.csv`);
    downloadCsv(versionsCsv, `experiment_${store.currentExperiment.id}_versions.csv`);
    toast.add({
      severity: 'success',
      summary: 'Export Complete',
      detail: 'CSV files downloaded',
      life: 3000,
    });
    return;
  }

  // ZIP export
  const zipData = zipSync({
    'experiment.json': strToU8(JSON.stringify(payload, null, 2)),
    'files.csv': strToU8(filesCsv.map((row) => row.join(',')).join('\n')),
    'versions.csv': strToU8(versionsCsv.map((row) => row.join(',')).join('\n')),
  });

  const blob = new Blob([zipData], { type: 'application/zip' });
  downloadBlob(blob, `experiment_${store.currentExperiment.id}.zip`);

  toast.add({
    severity: 'success',
    summary: 'Export Complete',
    detail: 'ZIP archive downloaded',
    life: 3000,
  });
};
</script>

<style scoped>
.versions-tab {
  min-height: 400px;
}

.versions-container {
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

.section-description {
  margin: 0 0 20px 0;
  color: #64748b;
  font-size: 0.9375rem;
}

.version-tree-container {
  margin-top: 8px;
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

.export-options {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.export-card {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 20px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  transition: border-color 0.2s;
}

.export-card:hover {
  border-color: #3b82f6;
}

.export-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  background: #ffffff;
  border-radius: 8px;
  font-size: 1.5rem;
  color: #3b82f6;
  flex-shrink: 0;
}

.export-info {
  flex: 1;
}

.export-info h4 {
  margin: 0 0 4px 0;
  font-size: 1rem;
  font-weight: 600;
  color: #1e293b;
}

.export-info p {
  margin: 0;
  font-size: 0.875rem;
  color: #64748b;
}

.export-stats {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  gap: 24px;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.9375rem;
  color: #475569;
}

.stat-item i {
  color: #94a3b8;
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

.dialog-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 4px 0;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-weight: 500;
  font-size: 0.875rem;
  color: #334155;
}

.required {
  color: #ef4444;
}

@media (max-width: 768px) {
  .export-card {
    flex-direction: column;
    text-align: center;
  }

  .export-stats {
    flex-direction: column;
    gap: 12px;
  }
}
</style>
