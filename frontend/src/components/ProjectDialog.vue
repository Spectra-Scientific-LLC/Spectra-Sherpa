<template>
  <Dialog
    v-model:visible="dialogVisible"
    :header="isEditMode ? 'Edit Project' : 'New Project'"
    :modal="true"
    :closable="true"
    :style="{ width: '500px' }"
    @hide="onHide"
  >
    <div class="project-form">
      <div class="field">
        <label for="project-name">Project Name <span class="required">*</span></label>
        <InputText
          id="project-name"
          v-model="form.name"
          placeholder="Enter project name"
          :class="{ 'p-invalid': submitted && !form.name }"
        />
        <small v-if="submitted && !form.name" class="p-error">
          Project name is required
        </small>
      </div>

      <div class="field">
        <label for="project-description">Description</label>
        <Textarea
          id="project-description"
          v-model="form.description"
          rows="3"
          placeholder="Describe the project purpose and goals"
        />
      </div>

      <div class="field">
        <label for="project-tags">Tags</label>
        <Chips
          id="project-tags"
          v-model="form.tags"
          separator=","
          placeholder="Add tags (press Enter)"
        />
        <small class="field-hint">Press Enter or comma to add tags</small>
      </div>

      <div v-if="isEditMode" class="project-metadata">
        <div class="metadata-row">
          <span class="metadata-label">Created:</span>
          <span class="metadata-value">{{ formatDate(editProject?.metadata.created) }}</span>
        </div>
        <div class="metadata-row">
          <span class="metadata-label">Last Modified:</span>
          <span class="metadata-value">{{ formatDate(editProject?.metadata.modified) }}</span>
        </div>
        <div class="metadata-row">
          <span class="metadata-label">Version:</span>
          <span class="metadata-value">{{ editProject?.metadata.version }}</span>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <Button
          label="Cancel"
          icon="pi pi-times"
          class="p-button-text"
          @click="onCancel"
        />
        <Button
          :label="isEditMode ? 'Save Changes' : 'Create Project'"
          :icon="isEditMode ? 'pi pi-check' : 'pi pi-plus'"
          @click="onSubmit"
        />
      </div>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, watch, computed } from "vue";
import Dialog from "primevue/dialog";
import Button from "primevue/button";
import InputText from "primevue/inputtext";
import Textarea from "primevue/textarea";
import Chips from "primevue/chips";
import type { Project } from "@/stores/project";

interface Props {
  visible: boolean;
  editProject?: Project | null;
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  editProject: null,
});

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
  (e: "create", data: { name: string; description: string; tags: string[] }): void;
  (e: "update", data: { name: string; description: string; tags: string[] }): void;
}>();

const dialogVisible = computed({
  get: () => props.visible,
  set: (val) => emit("update:visible", val),
});

const isEditMode = computed(() => !!props.editProject);

const form = ref({
  name: "",
  description: "",
  tags: [] as string[],
});

const submitted = ref(false);

// Define resetForm before watchers that use it
const resetForm = () => {
  form.value = {
    name: "",
    description: "",
    tags: [],
  };
  submitted.value = false;
};

// Watch for edit project changes
watch(
  () => props.editProject,
  (project) => {
    if (project) {
      form.value = {
        name: project.metadata.name,
        description: project.metadata.description,
        tags: [...project.metadata.tags],
      };
    } else {
      resetForm();
    }
  },
  { immediate: true }
);

// Watch for visibility changes
watch(
  () => props.visible,
  (visible) => {
    if (visible && !props.editProject) {
      resetForm();
    }
    submitted.value = false;
  }
);

const formatDate = (dateStr?: string): string => {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleString();
};

const onSubmit = () => {
  submitted.value = true;

  if (!form.value.name.trim()) {
    return;
  }

  if (isEditMode.value) {
    emit("update", {
      name: form.value.name.trim(),
      description: form.value.description.trim(),
      tags: form.value.tags,
    });
  } else {
    emit("create", {
      name: form.value.name.trim(),
      description: form.value.description.trim(),
      tags: form.value.tags,
    });
  }

  dialogVisible.value = false;
};

const onCancel = () => {
  dialogVisible.value = false;
};

const onHide = () => {
  submitted.value = false;
};
</script>

<style scoped>
.project-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  font-weight: 500;
  font-size: 0.9rem;
  color: #334155;
}

.required {
  color: #ef4444;
}

.field-hint {
  color: #94a3b8;
  font-size: 0.8rem;
}

.project-metadata {
  margin-top: 8px;
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.metadata-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.85rem;
}

.metadata-label {
  color: #64748b;
}

.metadata-value {
  color: #334155;
  font-weight: 500;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

:deep(.p-chips-token) {
  background: #dbeafe;
  color: #1e40af;
}
</style>
