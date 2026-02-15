<template>
  <div class="spectra-file-upload">
    <div class="upload-header" v-if="showHeader">
      <h3>{{ title }}</h3>
      <p>{{ subtitle }}</p>
    </div>

    <!-- Drag & Drop Zone -->
    <div
      class="upload-zone"
      :class="{ 'drag-over': isDragOver, 'has-files': files.length > 0 }"
      @dragover.prevent="isDragOver = true"
      @dragleave.prevent="isDragOver = false"
      @drop.prevent="handleDrop"
      @click="triggerFileInput"
    >
      <input
        ref="fileInput"
        type="file"
        :multiple="multiple"
        :accept="acceptedFormats"
        @change="handleFileSelect"
        hidden
      />

      <div v-if="files.length === 0" class="upload-placeholder">
        <i class="pi pi-cloud-upload"></i>
        <p class="upload-text">Drag & drop files here or click to browse</p>
        <p class="upload-hint">{{ formatHint }}</p>
      </div>

      <div v-else class="files-preview">
        <div class="files-summary">
          <i class="pi pi-check-circle"></i>
          <span>{{ files.length }} file(s) selected</span>
          <Button
            icon="pi pi-times"
            class="p-button-text p-button-sm p-button-danger"
            @click.stop="clearFiles"
          />
        </div>
        <div class="files-list">
          <div v-for="(file, index) in files.slice(0, 5)" :key="index" class="file-item">
            <i :class="getFileIcon(file.name)"></i>
            <span class="file-name">{{ file.name }}</span>
            <span class="file-size">{{ formatFileSize(file.size) }}</span>
          </div>
          <div v-if="files.length > 5" class="files-more">
            +{{ files.length - 5 }} more files
          </div>
        </div>
      </div>
    </div>

    <!-- Supported Formats -->
    <div v-if="showFormats" class="supported-formats">
      <h4>Supported Formats (via SpectrochemPy)</h4>
      <div class="formats-grid">
        <div v-for="format in formats" :key="format.name" class="format-item">
          <div class="format-header">
            <span class="format-name">{{ format.name }}</span>
            <span class="format-ext">{{ format.extensions }}</span>
          </div>
          <p class="format-desc">{{ format.description }}</p>
        </div>
      </div>
    </div>

    <!-- Upload Button -->
    <div v-if="files.length > 0 && showUploadButton" class="upload-actions">
      <Button
        :label="uploadButtonLabel"
        icon="pi pi-upload"
        :loading="uploading"
        :disabled="uploading"
        @click="uploadFiles"
      />
      <Button
        label="Clear"
        icon="pi pi-times"
        class="p-button-outlined p-button-secondary"
        @click="clearFiles"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import Button from "primevue/button";

interface Props {
  title?: string;
  subtitle?: string;
  showHeader?: boolean;
  showFormats?: boolean;
  showUploadButton?: boolean;
  uploadButtonLabel?: string;
  multiple?: boolean;
  formatFilter?: string[]; // Filter to specific formats like ['csv', 'jcamp']
}

const props = withDefaults(defineProps<Props>(), {
  title: "Import Spectra",
  subtitle: "Upload spectral data files for analysis",
  showHeader: true,
  showFormats: true,
  showUploadButton: true,
  uploadButtonLabel: "Upload Files",
  multiple: true,
  formatFilter: () => [],
});

const emit = defineEmits<{
  (event: "files-selected", files: File[]): void;
  (event: "upload", files: File[]): void;
}>();

const fileInput = ref<HTMLInputElement | null>(null);
const files = ref<File[]>([]);
const isDragOver = ref(false);
const uploading = ref(false);

// SpectrochemPy supported formats
const allFormats = [
  { name: "CSV", extensions: ".csv", description: "Comma-separated values", key: "csv" },
  { name: "JCAMP-DX", extensions: ".jdx, .dx", description: "IUPAC standard format", key: "jcamp" },
  { name: "Bruker OPUS", extensions: ".0, .1, .2", description: "Bruker FTIR format", key: "opus" },
  { name: "Thermo OMNIC", extensions: ".spa, .spg", description: "Thermo Scientific format", key: "omnic" },
  { name: "MATLAB", extensions: ".mat", description: "MATLAB data files", key: "matlab" },
  { name: "NumPy", extensions: ".npy, .npz", description: "NumPy array files", key: "numpy" },
  { name: "SPC", extensions: ".spc", description: "Galactic SPC format", key: "spc" },
  { name: "Wire", extensions: ".wdf", description: "Renishaw Wire format", key: "wire" },
];

const formats = computed(() => {
  if (props.formatFilter.length === 0) return allFormats;
  return allFormats.filter((f) => props.formatFilter.includes(f.key));
});

const acceptedFormats = computed(() => {
  return formats.value.map((f) => f.extensions).join(",");
});

const formatHint = computed(() => {
  const exts = formats.value.map((f) => f.extensions.split(",")[0].trim()).slice(0, 5);
  return `Supports: ${exts.join(", ")}${formats.value.length > 5 ? ", ..." : ""}`;
});

const triggerFileInput = () => {
  fileInput.value?.click();
};

const handleFileSelect = (event: Event) => {
  const target = event.target as HTMLInputElement;
  if (target.files) {
    files.value = Array.from(target.files);
    emit("files-selected", files.value);
  }
};

const handleDrop = (event: DragEvent) => {
  isDragOver.value = false;
  if (event.dataTransfer?.files) {
    files.value = Array.from(event.dataTransfer.files);
    emit("files-selected", files.value);
  }
};

const clearFiles = () => {
  files.value = [];
  if (fileInput.value) {
    fileInput.value.value = "";
  }
};

const uploadFiles = async () => {
  uploading.value = true;
  emit("upload", files.value);
  // Parent component handles actual upload
  uploading.value = false;
};

const getFileIcon = (filename: string): string => {
  const ext = filename.split(".").pop()?.toLowerCase();
  const iconMap: Record<string, string> = {
    csv: "pi pi-file",
    jdx: "pi pi-file",
    dx: "pi pi-file",
    spa: "pi pi-file",
    spg: "pi pi-file",
    mat: "pi pi-file",
    npy: "pi pi-file",
    npz: "pi pi-file",
    spc: "pi pi-file",
    wdf: "pi pi-file",
  };
  return iconMap[ext || ""] || "pi pi-file";
};

const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};
</script>

<style scoped>
.spectra-file-upload {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.upload-header h3 {
  margin: 0 0 4px;
  font-size: 1.1rem;
  font-weight: 600;
}

.upload-header p {
  margin: 0;
  color: #64748b;
  font-size: 0.9rem;
}

.upload-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  padding: 40px 20px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s ease;
  background: #f8fafc;
}

.upload-zone:hover {
  border-color: #3b82f6;
  background: #eff6ff;
}

.upload-zone.drag-over {
  border-color: #3b82f6;
  background: #dbeafe;
  transform: scale(1.01);
}

.upload-zone.has-files {
  border-style: solid;
  border-color: #22c55e;
  background: #f0fdf4;
  padding: 20px;
}

.upload-placeholder i {
  font-size: 3rem;
  color: #94a3b8;
  margin-bottom: 16px;
}

.upload-text {
  margin: 0 0 8px;
  font-size: 1rem;
  color: #334155;
  font-weight: 500;
}

.upload-hint {
  margin: 0;
  font-size: 0.85rem;
  color: #94a3b8;
}

.files-preview {
  text-align: left;
}

.files-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  color: #166534;
  font-weight: 500;
}

.files-summary i {
  font-size: 1.25rem;
}

.files-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: white;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.file-item i {
  color: #64748b;
}

.file-name {
  flex: 1;
  font-size: 0.9rem;
  color: #334155;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size {
  font-size: 0.8rem;
  color: #94a3b8;
}

.files-more {
  font-size: 0.85rem;
  color: #64748b;
  padding: 8px 12px;
}

.supported-formats h4 {
  margin: 0 0 12px;
  font-size: 0.9rem;
  font-weight: 600;
  color: #64748b;
}

.formats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}

.format-item {
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.format-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 4px;
}

.format-name {
  font-weight: 600;
  font-size: 0.9rem;
}

.format-ext {
  font-size: 0.75rem;
  color: #64748b;
  font-family: monospace;
}

.format-desc {
  margin: 0;
  font-size: 0.8rem;
  color: #64748b;
}

.upload-actions {
  display: flex;
  gap: 12px;
}
</style>
