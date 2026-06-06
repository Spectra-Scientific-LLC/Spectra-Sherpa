<template>
  <Dialog
    v-model:visible="dialogVisible"
    :header="isEditMode ? 'Edit Project' : 'New Project'"
    :modal="true"
    :closable="true"
    :style="{ width: '520px' }"
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

      <div class="field-row">
        <div class="field">
          <label for="project-technique">Technique</label>
          <Dropdown
            inputId="project-technique"
            v-model="form.technique"
            :options="techniqueOptions"
            placeholder="Select technique"
            :showClear="true"
          />
        </div>
        <div class="field">
          <label for="project-sample-type">Sample Type</label>
          <InputText
            id="project-sample-type"
            v-model="form.sample_type"
            placeholder="e.g. polymer blend, wine"
          />
        </div>
      </div>

      <div v-if="isEditMode && editProject" class="project-metadata">
        <div class="metadata-row">
          <span class="metadata-label">Created:</span>
          <span class="metadata-value">{{ formatDate(editProject.created_at) }}</span>
        </div>
        <div class="metadata-row">
          <span class="metadata-label">Last Modified:</span>
          <span class="metadata-value">{{ formatDate(editProject.updated_at) }}</span>
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
import Dropdown from "primevue/dropdown";
import type { ProjectSummary } from "@/types";

const techniqueOptions = ["FTIR", "Raman", "NMR", "UV-Vis", "NIR", "XRF", "MS"];

interface Props {
  visible?: boolean;
  editProject?: ProjectSummary | null;
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  editProject: null,
});

export interface ProjectFormData {
  name: string;
  description: string;
  technique: string | null;
  sample_type: string | null;
}

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
  (e: "create", data: ProjectFormData): void;
  (e: "update", data: ProjectFormData): void;
}>();

const dialogVisible = computed({
  get: () => props.visible,
  set: (val) => emit("update:visible", val),
});

const isEditMode = computed(() => !!props.editProject);

const form = ref({
  name: "",
  description: "",
  technique: null as string | null,
  sample_type: null as string | null,
});

const submitted = ref(false);

const resetForm = () => {
  form.value = {
    name: "",
    description: "",
    technique: null,
    sample_type: null,
  };
  submitted.value = false;
};

watch(
  () => props.editProject,
  (project) => {
    if (project) {
      form.value = {
        name: project.name,
        description: project.description || "",
        technique: project.technique,
        sample_type: project.sample_type,
      };
    } else {
      resetForm();
    }
  },
  { immediate: true }
);

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
  if (!dateStr) return "\u2014";
  return new Date(dateStr).toLocaleString();
};

const onSubmit = () => {
  submitted.value = true;

  if (!form.value.name.trim()) {
    return;
  }

  const data: ProjectFormData = {
    name: form.value.name.trim(),
    description: form.value.description.trim(),
    technique: form.value.technique,
    sample_type: form.value.sample_type?.trim() || null,
  };

  if (isEditMode.value) {
    emit("update", data);
  } else {
    emit("create", data);
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
  flex: 1;
}

.field-row {
  display: flex;
  gap: 16px;
}

.field label {
  font-weight: 500;
  font-size: 0.9rem;
  color: #334155;
}

.required {
  color: #ef4444;
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
</style>
