<template>
  <div
    class="file-uploader"
    :class="{ 'is-dragging': isDragging, disabled: disabled }"
    @dragover.prevent="onDragOver"
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
    @click="openPicker"
  >
    <input
      ref="fileInput"
      class="file-input"
      type="file"
      :accept="accept"
      :multiple="multiple"
      :disabled="disabled"
      @change="onFilesSelected"
    />
    <div class="file-uploader__content">
      <strong>{{ title }}</strong>
      <p>{{ helper }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";

const props = defineProps<{
  title?: string;
  helper?: string;
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  (event: "files-selected", files: File[]): void;
}>();

const fileInput = ref<HTMLInputElement | null>(null);
const isDragging = ref(false);

const title = props.title || "Drop files here";
const helper = props.helper || "Drag and drop or click to browse.";

const openPicker = () => {
  if (props.disabled) {
    return;
  }
  fileInput.value?.click();
};

const onDragOver = () => {
  if (props.disabled) {
    return;
  }
  isDragging.value = true;
};

const onDragLeave = () => {
  isDragging.value = false;
};

const emitFiles = (files: FileList | File[]) => {
  const payload = Array.from(files);
  if (payload.length > 0) {
    emit("files-selected", payload);
  }
};

const onDrop = (event: DragEvent) => {
  if (props.disabled) {
    return;
  }
  isDragging.value = false;
  if (event.dataTransfer?.files) {
    emitFiles(event.dataTransfer.files);
  }
};

const onFilesSelected = (event: Event) => {
  const target = event.target as HTMLInputElement;
  if (target.files) {
    emitFiles(target.files);
    target.value = "";
  }
};
</script>

<style scoped>
.file-uploader {
  border: 1px dashed #94a3b8;
  border-radius: 12px;
  padding: 16px;
  text-align: center;
  background: #f8fafc;
  cursor: pointer;
  transition: border 0.2s ease, background 0.2s ease;
}

.file-uploader.is-dragging {
  border-color: #2563eb;
  background: #e0f2fe;
}

.file-uploader.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.file-uploader__content p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 0.9rem;
}

.file-input {
  display: none;
}
</style>
