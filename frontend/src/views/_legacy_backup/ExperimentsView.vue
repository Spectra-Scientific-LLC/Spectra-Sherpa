<template>
  <section class="card experiments-view">
    <div class="section-header">
      <div>
        <h1>Experiments</h1>
        <p class="section-subtitle">Manage DOE metadata, uploads, and versioned spectra files.</p>
      </div>
      <Button label="New Experiment" icon="pi pi-plus" @click="openCreateDialog" />
    </div>

    <TabView v-model:activeIndex="activeTab" class="page-tabs">
      <TabPanel header="Experiments">
        <DataTable
          :value="store.experiments"
          stripedRows
          responsiveLayout="scroll"
          :loading="store.loading"
          class="mt-3"
        >
          <Column field="id" header="ID" sortable />
          <Column field="name" header="Name" sortable />
          <Column field="description" header="Description" />
          <Column header="Created">
            <template #body="slotProps">
              {{ formatDateTime(slotProps.data.created_at) }}
            </template>
          </Column>
          <Column header="Actions">
            <template #body="slotProps">
              <Button
                icon="pi pi-eye"
                class="p-button-rounded p-button-text"
                @click="openDetails(slotProps.data.id)"
              />
              <Button
                icon="pi pi-trash"
                class="p-button-rounded p-button-text p-button-danger"
                @click="deleteExperiment(slotProps.data.id)"
              />
            </template>
          </Column>
        </DataTable>
      </TabPanel>

      <TabPanel header="Create">
        <div class="form-grid">
          <div class="field">
            <label>Name</label>
            <InputText v-model="draftExperiment.name" />
          </div>
          <div class="field">
            <label>Description</label>
            <Textarea v-model="draftExperiment.description" rows="3" />
          </div>
          <div class="panel">
            <h3>Hardware</h3>
            <div class="form-grid two">
              <div class="field">
                <label>Instrument</label>
                <InputText v-model="draftExperiment.hardware.instrument" />
              </div>
              <div class="field">
                <label>Detector</label>
                <InputText v-model="draftExperiment.hardware.detector" />
              </div>
              <div class="field">
                <label>Location</label>
                <InputText v-model="draftExperiment.hardware.location" />
              </div>
              <div class="field">
                <label>Operator</label>
                <InputText v-model="draftExperiment.hardware.operator" />
              </div>
            </div>
          </div>
          <div class="panel">
            <h3>DOE</h3>
            <div class="form-grid two">
              <div class="field">
                <label>Design Type</label>
                <InputText v-model="draftExperiment.doe.design" />
              </div>
              <div class="field">
                <label>Objective</label>
                <InputText v-model="draftExperiment.doe.objective" />
              </div>
            </div>
            <div class="stack mt-2">
              <div
                v-for="(factor, idx) in draftExperiment.doe.factors"
                :key="idx"
                class="form-grid two"
              >
                <InputText v-model="factor.name" placeholder="Factor" />
                <InputText v-model="factor.levels" placeholder="Levels (comma-separated)" />
                <Button
                  icon="pi pi-times"
                  class="p-button-text p-button-danger"
                  @click="removeFactor(idx)"
                />
              </div>
              <Button label="Add Factor" icon="pi pi-plus" class="p-button-text" @click="addFactor" />
            </div>
          </div>
          <div class="panel">
            <h3>Mixtures</h3>
            <div class="stack">
              <div v-for="(mix, idx) in draftExperiment.mixtures" :key="idx" class="form-grid two">
                <InputText v-model="mix.component" placeholder="Component" />
                <InputNumber v-model="mix.fraction" placeholder="Fraction (%)" :min="0" :max="100" />
                <Button
                  icon="pi pi-times"
                  class="p-button-text p-button-danger"
                  @click="removeMixture(idx)"
                />
              </div>
              <Button
                label="Add Component"
                icon="pi pi-plus"
                class="p-button-text"
                @click="addMixture"
              />
            </div>
          </div>
        </div>
        <div class="tab-actions">
          <Button label="Reset" class="p-button-text" @click="resetDraft" />
          <Button label="Create" icon="pi pi-check" @click="createExperiment" />
        </div>
      </TabPanel>

      <TabPanel header="Details">
        <div v-if="store.currentExperiment" class="two-column">
          <div class="stack">
            <div class="panel">
              <h3>Metadata</h3>
              <div class="metadata-grid">
                <div>
                  <h4>Hardware</h4>
                  <p class="muted-text">Instrument: {{ hardware.instrument || "-" }}</p>
                  <p class="muted-text">Detector: {{ hardware.detector || "-" }}</p>
                  <p class="muted-text">Location: {{ hardware.location || "-" }}</p>
                  <p class="muted-text">Operator: {{ hardware.operator || "-" }}</p>
                </div>
                <div>
                  <h4>DOE</h4>
                  <p class="muted-text">Design: {{ doe.design || "-" }}</p>
                  <p class="muted-text">Objective: {{ doe.objective || "-" }}</p>
                  <div v-if="doe.factors.length" class="stack">
                    <div v-for="(factor, idx) in doe.factors" :key="idx" class="pill">
                      {{ factor.name }}: {{ factor.levels }}
                    </div>
                  </div>
                </div>
              </div>
              <div class="mt-3">
                <h4>Mixtures</h4>
                <div v-if="mixtures.length" class="stack">
                  <div v-for="(mix, idx) in mixtures" :key="idx" class="pill">
                    {{ mix.component }} - {{ mix.fraction }}%
                  </div>
                </div>
                <div v-else class="muted-text">No mixture components recorded.</div>
              </div>
            </div>

            <div class="panel">
              <div class="section-header">
                <h3>Files</h3>
                <Dropdown v-model="uploadStage" :options="stages" />
              </div>
              <FileUploader
                title="Upload spectra files"
                helper="CSV/JSON/JDX supported."
                multiple
                :disabled="uploadState.uploading"
                @files-selected="handleFileUpload"
              />
              <p v-if="uploadState.uploading" class="muted-text">
                Uploading {{ uploadState.done }}/{{ uploadState.total }}...
              </p>
              <DataTable :value="store.files" stripedRows class="mt-3">
                <Column field="file_path" header="File">
                  <template #body="slotProps">
                    {{ slotProps.data.file_path.split("/").pop() }}
                  </template>
                </Column>
                <Column field="stage" header="Stage">
                  <template #body="slotProps">
                    <Tag :value="slotProps.data.stage" />
                  </template>
                </Column>
                <Column header="Size">
                  <template #body="slotProps">
                    {{ formatBytes(slotProps.data.file_size_bytes) }}
                  </template>
                </Column>
              </DataTable>
            </div>
          </div>

          <div class="panel">
            <div class="section-header">
              <h3>Version History</h3>
              <Button
                label="Snapshot"
                icon="pi pi-camera"
                class="p-button-sm"
                @click="openVersionDialog"
              />
            </div>
            <VersionTree :versions="formattedVersions" @restore="restoreVersion" />
            <div class="export-actions">
              <h4>Export</h4>
              <div class="export-buttons">
                <Button label="JSON" class="p-button-text" @click="exportExperiment('json')" />
                <Button label="CSV" class="p-button-text" @click="exportExperiment('csv')" />
                <Button label="ZIP" class="p-button-text" @click="exportExperiment('zip')" />
              </div>
              <div class="muted-text">
                Export size: {{ formatBytes(totalFileSize) }}
              </div>
            </div>
          </div>
        </div>
        <div v-else class="panel muted-text">
          Select an experiment from the list to view details.
        </div>
      </TabPanel>
    </TabView>
  </section>

  <Dialog
    v-model:visible="versionDialogVisible"
    header="Create Version Snapshot"
    :modal="true"
    style="width: min(420px, 90vw)"
  >
    <div class="form-grid">
      <div class="field">
        <label>Version Name</label>
        <InputText v-model="versionDraft.name" />
      </div>
      <div class="field">
        <label>Description</label>
        <Textarea v-model="versionDraft.description" rows="2" />
      </div>
      <div class="field">
        <label>Include Stages</label>
        <MultiSelect v-model="versionDraft.stages" :options="stages" />
      </div>
    </div>
    <template #footer>
      <Button label="Cancel" class="p-button-text" @click="versionDialogVisible = false" />
      <Button label="Create" icon="pi pi-save" @click="createVersion" />
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useToast } from "primevue/usetoast";
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import Dialog from "primevue/dialog";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import MultiSelect from "primevue/multiselect";
import TabPanel from "primevue/tabpanel";
import TabView from "primevue/tabview";
import Tag from "primevue/tag";
import Textarea from "primevue/textarea";

import { useExperimentStore } from "@/stores/experiment";
import FileUploader from "@/components/FileUploader.vue";
import VersionTree from "@/components/VersionTree.vue";
import { downloadBlob, downloadCsv, downloadJson } from "@/utils/download";
import { formatBytes, formatDateTime } from "@/utils/format";

import { zipSync, strToU8 } from "fflate";

const store = useExperimentStore();
const toast = useToast();

const activeTab = ref(0);
const versionDialogVisible = ref(false);

const stages = ["raw", "preprocessed", "synthetic"];
const uploadStage = ref("raw");
const uploadState = reactive({ uploading: false, total: 0, done: 0 });

const draftExperiment = ref({
  name: "",
  description: "",
  hardware: {
    instrument: "",
    detector: "",
    location: "",
    operator: "",
  },
  doe: {
    design: "",
    objective: "",
    factors: [{ name: "", levels: "" }],
  },
  mixtures: [{ component: "", fraction: 0 }],
});

const versionDraft = ref({
  name: "",
  description: "",
  stages: ["raw"],
});

const hardware = computed(() => {
  const meta = store.currentExperiment?.metadata as any;
  return meta?.hardware || {};
});

const doe = computed(() => {
  const meta = store.currentExperiment?.metadata as any;
  return {
    design: meta?.doe?.design || "",
    objective: meta?.doe?.objective || "",
    factors: meta?.doe?.factors || [],
  };
});

const mixtures = computed(() => {
  const meta = store.currentExperiment?.metadata as any;
  return meta?.mixtures || [];
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

onMounted(() => {
  store.fetchExperiments().catch(() => {
    toast.add({
      severity: "error",
      summary: "Error",
      detail: "Failed to load experiments",
      life: 3000,
    });
  });
});

const resetDraft = () => {
  draftExperiment.value = {
    name: "",
    description: "",
    hardware: {
      instrument: "",
      detector: "",
      location: "",
      operator: "",
    },
    doe: {
      design: "",
      objective: "",
      factors: [{ name: "", levels: "" }],
    },
    mixtures: [{ component: "", fraction: 0 }],
  };
};

const openCreateDialog = () => {
  resetDraft();
  activeTab.value = 1;
};

const addMixture = () => {
  draftExperiment.value.mixtures.push({ component: "", fraction: 0 });
};

const removeMixture = (index: number) => {
  draftExperiment.value.mixtures.splice(index, 1);
};

const addFactor = () => {
  draftExperiment.value.doe.factors.push({ name: "", levels: "" });
};

const removeFactor = (index: number) => {
  draftExperiment.value.doe.factors.splice(index, 1);
};

const createExperiment = async () => {
  try {
    await store.createExperiment({
      name: draftExperiment.value.name,
      description: draftExperiment.value.description,
      metadata: {
        hardware: draftExperiment.value.hardware,
        doe: draftExperiment.value.doe,
        mixtures: draftExperiment.value.mixtures,
      },
    });
    activeTab.value = 0;
    toast.add({
      severity: "success",
      summary: "Created",
      detail: "Experiment created",
      life: 3000,
    });
  } catch {
    toast.add({
      severity: "error",
      summary: "Error",
      detail: "Failed to create experiment",
      life: 3000,
    });
  }
};

const openDetails = async (experimentId: number) => {
  try {
    await store.selectExperiment(experimentId);
    activeTab.value = 2;
  } catch {
    toast.add({
      severity: "error",
      summary: "Error",
      detail: "Failed to load experiment",
      life: 3000,
    });
  }
};

const deleteExperiment = async (experimentId: number) => {
  if (!confirm("Delete this experiment?")) {
    return;
  }
  await store.deleteExperiment(experimentId);
};

const handleFileUpload = async (files: File[]) => {
  if (!store.currentExperiment) {
    return;
  }
  uploadState.uploading = true;
  uploadState.total = files.length;
  uploadState.done = 0;
  let successCount = 0;
  const failedFiles: string[] = [];

  for (const file of files) {
    try {
      await store.uploadFile(store.currentExperiment.id, file, uploadStage.value);
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
      severity: "success",
      summary: "Uploaded",
      detail: `${successCount} file(s) uploaded successfully.`,
      life: 3000,
    });
  }
  if (failedFiles.length > 0) {
    toast.add({
      severity: "error",
      summary: "Upload failed",
      detail: `Failed: ${failedFiles.join(", ")}`,
      life: 4000,
    });
  }
};

const openVersionDialog = () => {
  versionDraft.value = {
    name: `v${store.versions.length + 1}`,
    description: "",
    stages: ["raw"],
  };
  versionDialogVisible.value = true;
};

const createVersion = async () => {
  if (!store.currentExperiment) {
    return;
  }
  await store.createVersion(
    store.currentExperiment.id,
    versionDraft.value.name,
    versionDraft.value.description,
    versionDraft.value.stages
  );
  versionDialogVisible.value = false;
};

const restoreVersion = async (versionName: string) => {
  if (!store.currentExperiment) {
    return;
  }
  if (!confirm(`Restore ${versionName}? Existing files will be overwritten.`)) {
    return;
  }
  await store.restoreVersion(store.currentExperiment.id, versionName);
};

const exportExperiment = (format: "json" | "csv" | "zip") => {
  if (!store.currentExperiment) {
    return;
  }
  const maxBytes = 1024 * 1024 * 1024;
  const warnBytes = 500 * 1024 * 1024;
  if (totalFileSize.value > maxBytes) {
    toast.add({
      severity: "warn",
      summary: "Export too large",
      detail: "Export exceeds the 1 GB limit.",
      life: 4000,
    });
    return;
  }
  if (totalFileSize.value > warnBytes) {
    const proceed = confirm(
      "This export is over 500 MB and may take a while. Continue?"
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

  if (format === "json") {
    downloadJson(payload, `experiment_${store.currentExperiment.id}.json`);
    return;
  }

  const filesCsv = [
    ["file_path", "stage", "size_bytes"],
    ...store.files.map((file) => [file.file_path, file.stage, file.file_size_bytes]),
  ];
  const versionsCsv = [
    ["version_name", "description", "created_at", "file_count"],
    ...store.versions.map((ver) => [
      ver.version_name,
      ver.description,
      ver.created_at,
      ver.file_count,
    ]),
  ];

  if (format === "csv") {
    downloadCsv(filesCsv, `experiment_${store.currentExperiment.id}_files.csv`);
    downloadCsv(versionsCsv, `experiment_${store.currentExperiment.id}_versions.csv`);
    return;
  }

  const zipData = zipSync({
    "experiment.json": strToU8(JSON.stringify(payload, null, 2)),
    "files.csv": strToU8(filesCsv.map((row) => row.join(",")).join("\n")),
    "versions.csv": strToU8(versionsCsv.map((row) => row.join(",")).join("\n")),
  });
  const blob = new Blob([zipData], { type: "application/zip" });
  downloadBlob(blob, `experiment_${store.currentExperiment.id}.zip`);
};
</script>

<style scoped>
.experiments-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.metadata-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.export-actions {
  margin-top: 24px;
}

.export-buttons {
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
}

.tab-actions {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.mt-3 {
  margin-top: 16px;
}
</style>
