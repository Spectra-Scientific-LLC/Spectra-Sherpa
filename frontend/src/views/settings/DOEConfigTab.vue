<template>
  <div class="tab-section">
    <div class="section-header">
      <div>
        <h3>DOE Configuration Profiles</h3>
        <p class="muted-text">
          Reusable settings for instrument/run styles. Configure folder→batch mapping,
          filename parsing, scan defaults, and run sequence templates.
        </p>
      </div>
      <Button
        label="New Profile"
        icon="pi pi-plus"
        @click="openCreateDialog"
      />
    </div>

    <DataTable
      :value="configs"
      :loading="loading"
      stripedRows
      class="config-table"
    >
      <Column field="name" header="Profile Name" sortable>
        <template #body="{ data }">
          <div class="profile-name">
            {{ data.name }}
            <Tag v-if="data.is_default" severity="success" value="Default" />
          </div>
        </template>
      </Column>
      <Column field="description" header="Description" />
      <Column header="Actions">
        <template #body="{ data }">
          <div class="action-buttons">
            <Button
              icon="pi pi-pencil"
              class="p-button-text p-button-sm"
              @click="openEditDialog(data)"
            />
            <Button
              v-if="!data.is_default"
              icon="pi pi-star"
              class="p-button-text p-button-sm"
              v-tooltip.top="'Set as default'"
              @click="setAsDefault(data.id)"
            />
            <Button
              icon="pi pi-trash"
              class="p-button-text p-button-sm p-button-danger"
              @click="confirmDelete(data)"
            />
          </div>
        </template>
      </Column>
    </DataTable>

    <!-- Create/Edit Dialog -->
    <Dialog
      v-model:visible="showDialog"
      :header="editingConfig ? 'Edit DOE Config Profile' : 'New DOE Config Profile'"
      :style="{ width: '700px' }"
      :modal="true"
    >
      <div class="dialog-content">
        <div class="field">
          <label for="config-name">Profile Name *</label>
          <InputText
            id="config-name"
            v-model="formData.name"
            placeholder="e.g., FTIR Plate Reader"
          />
        </div>

        <div class="field">
          <label for="config-description">Description</label>
          <Textarea
            id="config-description"
            v-model="formData.description"
            rows="2"
            placeholder="Brief description of this configuration"
          />
        </div>

        <div class="field">
          <div class="checkbox-field">
            <Checkbox v-model="formData.is_default" :binary="true" inputId="is-default" />
            <label for="is-default">Set as default profile</label>
          </div>
        </div>

        <Accordion :multiple="true">
          <AccordionTab header="Scan Path Defaults">
            <div class="stack">
              <div class="field">
                <label>First Cell</label>
                <InputText
                  v-model="formData.scan_defaults.first_cell"
                  placeholder="e.g., A1"
                />
              </div>
              <div class="field">
                <label>Scan Orientation</label>
                <Dropdown
                  v-model="formData.scan_defaults.orientation"
                  :options="[
                    { label: 'Row-wise', value: 'row' },
                    { label: 'Column-wise', value: 'column' },
                    { label: 'Serpentine', value: 'serpentine' }
                  ]"
                  optionLabel="label"
                  optionValue="value"
                  placeholder="Select orientation"
                />
              </div>
              <div class="field">
                <label>Sequence Offset</label>
                <InputNumber v-model="formData.scan_defaults.seq_offset" />
              </div>
            </div>
          </AccordionTab>

          <AccordionTab header="Filename Patterns">
            <div class="stack">
              <div class="field">
                <label>Sequence Pattern (regex)</label>
                <InputText
                  v-model="formData.filename_patterns.seq_pattern"
                  placeholder="e.g., _(\\d+)\\."
                />
              </div>
              <div class="field">
                <label>Cell Pattern (regex)</label>
                <InputText
                  v-model="formData.filename_patterns.cell_pattern"
                  placeholder="e.g., ([A-H][0-9]{1,2})"
                />
              </div>
              <div class="checkbox-field">
                <Checkbox
                  v-model="formData.filename_patterns.fallback_to_any_digits"
                  :binary="true"
                  inputId="fallback-digits"
                />
                <label for="fallback-digits">Fallback to any digits if no match</label>
              </div>
            </div>
          </AccordionTab>

          <AccordionTab header="Folder/Batch Rules">
            <div class="stack">
              <div class="field">
                <label>Folder Pattern</label>
                <Dropdown
                  v-model="formData.folder_batch_rules.pattern"
                  :options="['timestamp', 'sequential', 'custom']"
                  placeholder="Select pattern"
                />
              </div>
              <div class="checkbox-field">
                <Checkbox
                  v-model="formData.folder_batch_rules.extract_batch_from_folder"
                  :binary="true"
                  inputId="extract-batch"
                />
                <label for="extract-batch">Extract batch number from folder name</label>
              </div>
              <div class="checkbox-field">
                <Checkbox
                  v-model="formData.folder_batch_rules.auto_increment"
                  :binary="true"
                  inputId="auto-increment"
                />
                <label for="auto-increment">Auto-increment batch numbers</label>
              </div>
            </div>
          </AccordionTab>

          <AccordionTab header="Matching Behavior">
            <div class="stack">
              <div class="checkbox-field">
                <Checkbox
                  v-model="formData.match_settings.use_plate_map"
                  :binary="true"
                  inputId="use-plate-map"
                />
                <label for="use-plate-map">Use plate map for cell/sample derivation</label>
              </div>
              <div class="checkbox-field">
                <Checkbox
                  v-model="formData.match_settings.use_run_sequence"
                  :binary="true"
                  inputId="use-run-seq"
                />
                <label for="use-run-seq">Map folders to run sequence for factor values</label>
              </div>
              <div class="checkbox-field">
                <Checkbox
                  v-model="formData.match_settings.auto_detect_folders"
                  :binary="true"
                  inputId="auto-detect"
                />
                <label for="auto-detect">Auto-detect folder structure</label>
              </div>
            </div>
          </AccordionTab>
        </Accordion>
      </div>

      <template #footer>
        <Button label="Cancel" @click="showDialog = false" class="p-button-text" />
        <Button
          :label="editingConfig ? 'Update' : 'Create'"
          :loading="saving"
          @click="saveConfig"
        />
      </template>
    </Dialog>

    <!-- Delete Confirmation Dialog -->
    <Dialog
      v-model:visible="showDeleteDialog"
      header="Confirm Delete"
      :style="{ width: '400px' }"
      :modal="true"
    >
      <p>Are you sure you want to delete the profile "{{ configToDelete?.name }}"?</p>
      <template #footer>
        <Button label="Cancel" @click="showDeleteDialog = false" class="p-button-text" />
        <Button
          label="Delete"
          severity="danger"
          :loading="deleting"
          @click="deleteConfig"
        />
      </template>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
/* eslint-disable @typescript-eslint/no-explicit-any -- DOE payloads are form-driven and backend-shaped in this admin editor. */
import { ref, onMounted } from "vue";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import Dialog from "primevue/dialog";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Tag from "primevue/tag";
import Textarea from "primevue/textarea";
import Accordion from "primevue/accordion";
import AccordionTab from "primevue/accordiontab";
import { useToast } from "primevue/usetoast";
import api from "@/api/client";

const toast = useToast();

const configs = ref<any[]>([]);
const loading = ref(false);
const saving = ref(false);
const deleting = ref(false);
const showDialog = ref(false);
const showDeleteDialog = ref(false);
const editingConfig = ref<any>(null);
const configToDelete = ref<any>(null);

const emptyFormData = () => ({
  name: "",
  description: "",
  is_default: false,
  scan_defaults: {
    first_cell: "A1",
    orientation: "row",
    seq_offset: 0,
  },
  filename_patterns: {
    seq_pattern: "_(\\d+)\\.",
    cell_pattern: "([A-H][0-9]{1,2})",
    fallback_to_any_digits: true,
  },
  folder_batch_rules: {
    pattern: "timestamp",
    extract_batch_from_folder: true,
    auto_increment: true,
  },
  match_settings: {
    use_plate_map: true,
    use_run_sequence: true,
    auto_detect_folders: true,
  },
  run_sequence_template: null,
});

const formData = ref(emptyFormData());

const fetchConfigs = async () => {
  loading.value = true;
  try {
    const response = await api.get("/doe-configs");
    configs.value = response.data.configs;
  } catch {
    toast.add({
      severity: "error",
      summary: "Error",
      detail: "Failed to load DOE configurations",
      life: 3000,
    });
  } finally {
    loading.value = false;
  }
};

const openCreateDialog = () => {
  editingConfig.value = null;
  formData.value = emptyFormData();
  showDialog.value = true;
};

const openEditDialog = (config: any) => {
  editingConfig.value = config;
  formData.value = {
    name: config.name,
    description: config.description || "",
    is_default: config.is_default,
    scan_defaults: config.scan_defaults || emptyFormData().scan_defaults,
    filename_patterns: config.filename_patterns || emptyFormData().filename_patterns,
    folder_batch_rules: config.folder_batch_rules || emptyFormData().folder_batch_rules,
    match_settings: config.match_settings || emptyFormData().match_settings,
    run_sequence_template: config.run_sequence_template,
  };
  showDialog.value = true;
};

const saveConfig = async () => {
  if (!formData.value.name.trim()) {
    toast.add({
      severity: "warn",
      summary: "Validation Error",
      detail: "Profile name is required",
      life: 3000,
    });
    return;
  }

  saving.value = true;
  try {
    if (editingConfig.value) {
      await api.put(`/doe-configs/${editingConfig.value.id}`, formData.value);
      toast.add({
        severity: "success",
        summary: "Success",
        detail: "Configuration updated",
        life: 3000,
      });
    } else {
      await api.post("/doe-configs", formData.value);
      toast.add({
        severity: "success",
        summary: "Success",
        detail: "Configuration created",
        life: 3000,
      });
    }
    showDialog.value = false;
    await fetchConfigs();
  } catch {
    toast.add({
      severity: "error",
      summary: "Error",
      detail: "Failed to save configuration",
      life: 3000,
    });
  } finally {
    saving.value = false;
  }
};

const setAsDefault = async (configId: number) => {
  try {
    await api.put(`/doe-configs/${configId}`, { is_default: true });
    toast.add({
      severity: "success",
      summary: "Success",
      detail: "Default profile updated",
      life: 3000,
    });
    await fetchConfigs();
  } catch {
    toast.add({
      severity: "error",
      summary: "Error",
      detail: "Failed to set default profile",
      life: 3000,
    });
  }
};

const confirmDelete = (config: any) => {
  configToDelete.value = config;
  showDeleteDialog.value = true;
};

const deleteConfig = async () => {
  if (!configToDelete.value) return;

  deleting.value = true;
  try {
    await api.delete(`/doe-configs/${configToDelete.value.id}`);
    toast.add({
      severity: "success",
      summary: "Success",
      detail: "Configuration deleted",
      life: 3000,
    });
    showDeleteDialog.value = false;
    await fetchConfigs();
  } catch {
    toast.add({
      severity: "error",
      summary: "Error",
      detail: "Failed to delete configuration",
      life: 3000,
    });
  } finally {
    deleting.value = false;
  }
};

onMounted(() => {
  fetchConfigs();
});
</script>

<style scoped>
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.config-table {
  margin-top: 16px;
}

.profile-name {
  display: flex;
  align-items: center;
  gap: 8px;
}

.action-buttons {
  display: flex;
  gap: 4px;
}

.dialog-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.checkbox-field {
  display: flex;
  align-items: center;
  gap: 8px;
}

.checkbox-field label {
  margin: 0;
}

.stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
</style>
