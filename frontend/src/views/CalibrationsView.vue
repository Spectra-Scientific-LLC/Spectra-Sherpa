<template>
  <section class="card calibration-view">
    <div class="section-header">
      <div>
        <h1>Calibrations</h1>
        <p class="section-subtitle">Upload measurements, fit models, and activate versions.</p>
      </div>
      <Button label="New Calibration" icon="pi pi-plus" @click="openCreateDialog" />
    </div>

    <TabView v-model:activeIndex="activeTab" class="page-tabs">
      <TabPanel header="Calibrations">
        <DataTable
          :value="store.calibrations"
          stripedRows
          responsiveLayout="scroll"
          :loading="store.loading"
          class="mt-3"
        >
          <Column field="id" header="ID" sortable />
          <Column field="compound_name" header="Compound" sortable />
          <Column field="concentration_mode" header="Mode" />
          <Column field="x_unit" header="Units" />
          <Column header="Created">
            <template #body="slotProps">
              {{ formatDateTime(slotProps.data.created_at) }}
            </template>
          </Column>
          <Column header="Actions">
            <template #body="slotProps">
              <Button
                icon="pi pi-chart-line"
                class="p-button-rounded p-button-text"
                @click="openDetails(slotProps.data.id)"
              />
            </template>
          </Column>
        </DataTable>
      </TabPanel>

      <TabPanel header="Create">
        <div class="form-grid">
          <div class="field">
            <label>Compound Name</label>
            <InputText v-model="draftCalibration.compound_name" />
          </div>
          <div class="field">
            <label>Concentration Mode</label>
            <Dropdown v-model="draftCalibration.concentration_mode" :options="modeOptions" />
          </div>
          <div class="field">
            <label>X Unit</label>
            <InputText v-model="draftCalibration.x_unit" />
          </div>
          <div class="field">
            <label>Pathlength (m)</label>
            <InputNumber v-model="draftCalibration.pathlength_m" :min="0" :step="0.1" />
          </div>
        </div>
        <div class="tab-actions">
          <Button label="Reset" class="p-button-text" @click="resetDraft" />
          <Button label="Create" icon="pi pi-check" @click="createCalibration" />
        </div>
      </TabPanel>

      <TabPanel header="Details">
        <div v-if="store.currentCalibration" class="two-column">
          <div class="stack">
            <div class="panel">
              <div class="section-header">
                <h3>Measurements</h3>
                <Button label="Export" class="p-button-text" @click="exportCalibration" />
              </div>
              <div class="form-grid two mt-2">
                <div class="field">
                  <label>Concentration</label>
                  <InputNumber v-model="measurementConcentration" :min="0" :step="0.1" />
                </div>
                <div class="field">
                  <label>Upload File</label>
                  <FileUploader
                    title="Drop measurement CSV"
                    helper="Upload one measurement at a time."
                    :disabled="measurementUpload.uploading"
                    @files-selected="handleMeasurementUpload"
                  />
                  <p v-if="measurementUpload.uploading" class="muted-text">
                    Uploading {{ measurementUpload.done }}/{{ measurementUpload.total }}...
                  </p>
                </div>
              </div>
              <DataTable :value="store.measurements" stripedRows class="mt-3">
                <Column field="file_path" header="File">
                  <template #body="slotProps">
                    {{ slotProps.data.file_path.split("/").pop() }}
                  </template>
                </Column>
                <Column field="concentration" header="Concentration" />
                <Column header="Uploaded">
                  <template #body="slotProps">
                    {{ formatDateTime(slotProps.data.created_at) }}
                  </template>
                </Column>
              </DataTable>
            </div>

            <div class="panel">
              <div class="section-header">
                <h3>Fit Model</h3>
                <span
                  v-if="jobStore.connectionStatus !== 'connected'"
                  class="ws-status"
                  :class="jobStore.connectionStatus"
                >
                  {{
                    jobStore.connectionStatus === "connecting"
                      ? "Realtime reconnecting..."
                      : "Realtime disconnected"
                  }}
                  <span v-if="jobStore.lastError">({{ jobStore.lastError }})</span>
                </span>
              </div>
              <div class="form-grid two">
                <div class="field">
                  <label>Model Type</label>
                  <Dropdown v-model="modelType" :options="modelOptions" />
                </div>
                <div class="field">
                  <label>Version Name</label>
                  <InputText v-model="versionName" placeholder="Optional" />
                </div>
              </div>
              <Button
                label="Fit Model"
                icon="pi pi-play"
                class="mt-2"
                :loading="store.loading"
                @click="fitModel"
              />
              <div v-if="fitJob" class="mt-2">
                <JobProgressBar
                  :progress="fitJob.progress"
                  :status="fitJob.status"
                  :message="fitJob.progress_message"
                />
              </div>
            </div>

            <div class="panel">
              <h3>Model Versions</h3>
              <DataTable :value="store.models" stripedRows>
                <Column field="version_name" header="Version" />
                <Column field="model_type" header="Type" />
                <Column field="r_squared" header="R2" />
                <Column field="rmse" header="RMSE" />
                <Column header="Active">
                  <template #body="slotProps">
                    <InputSwitch
                      :modelValue="slotProps.data.is_active"
                      @update:modelValue="() => activateModel(slotProps.data.id)"
                    />
                  </template>
                </Column>
              </DataTable>
            </div>
          </div>

          <div class="panel plot-panel">
            <div class="section-header">
              <h3>Calibration Curve</h3>
            </div>
            <PlotlyChart :data="plotData" :layout="plotLayout" />
            <div class="muted-text mt-2">
              Preview plot uses uploaded CSV response maxima.
            </div>
          </div>
        </div>
        <div v-else class="panel muted-text">
          Select a calibration from the list to view details.
        </div>
      </TabPanel>
    </TabView>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import InputSwitch from "primevue/inputswitch";
import InputText from "primevue/inputtext";
import TabPanel from "primevue/tabpanel";
import TabView from "primevue/tabview";
import { useToast } from "primevue/usetoast";

import { useCalibrationStore } from "@/stores/calibration";
import { useJobStore } from "@/stores/job";
import FileUploader from "@/components/FileUploader.vue";
import JobProgressBar from "@/components/JobProgressBar.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import { downloadCsv, downloadJson } from "@/utils/download";
import { formatDateTime } from "@/utils/format";

const store = useCalibrationStore();
const jobStore = useJobStore();
const toast = useToast();

const activeTab = ref(0);
const measurementConcentration = ref<number | null>(null);
const previewPoints = ref<Array<{ concentration: number; response: number }>>([]);
const modelType = ref("linear");
const versionName = ref("");
const fitJobId = ref<number | null>(null);
const measurementUpload = reactive({ uploading: false, total: 0, done: 0 });
const hadRealtime = ref(false);

const modeOptions = ["product", "concentration"];
const modelOptions = ["linear", "saturation", "hybrid"];

const draftCalibration = ref({
  compound_name: "",
  concentration_mode: "product",
  x_unit: "ppm*m",
  pathlength_m: null as number | null,
});

const resetDraft = () => {
  draftCalibration.value = {
    compound_name: "",
    concentration_mode: "product",
    x_unit: "ppm*m",
    pathlength_m: null,
  };
};

const plotLayout = {
  title: { text: "Calibration Curve (Preview)" },
  xaxis: { title: { text: "Concentration" } },
  yaxis: { title: { text: "Response (max absorbance)" } },
  margin: { t: 40, r: 20, l: 60, b: 40 },
};

const fitJob = computed(() =>
  fitJobId.value ? jobStore.jobs.find((job) => job.id === fitJobId.value) : null
);

const plotData = computed(() => {
  if (previewPoints.value.length === 0) {
    return [];
  }
  const x = previewPoints.value.map((point) => point.concentration);
  const y = previewPoints.value.map((point) => point.response);
  const traces: any[] = [
    {
      x,
      y,
      type: "scatter",
      mode: "markers",
      name: "Measurements",
    },
  ];
  if (x.length >= 2) {
    const sorted = previewPoints.value.slice().sort((a, b) => a.concentration - b.concentration);
    const lineX = sorted.map((point) => point.concentration);
    const lineY = sorted.map((point) => point.response);
    traces.push({
      x: lineX,
      y: lineY,
      type: "scatter",
      mode: "lines",
      name: "Preview Fit",
    });
  }
  return traces;
});

onMounted(() => {
  store.fetchCalibrations().catch(() => {
    toast.add({
      severity: "error",
      summary: "Error",
      detail: "Failed to load calibrations.",
      life: 3000,
    });
  });
  jobStore.connect();
  jobStore.fetchJobs();
});

watch(
  () => jobStore.connectionStatus,
  (status, prev) => {
    if (prev === "connected" && status === "disconnected") {
      toast.add({
        severity: "warn",
        summary: "Realtime disconnected",
        detail: jobStore.lastError || "Trying to reconnect...",
        life: 4000,
      });
    }
    if (status === "connected") {
      if (hadRealtime.value && prev === "disconnected") {
        toast.add({
          severity: "success",
          summary: "Realtime restored",
          detail: "Job progress updates are back online.",
          life: 2500,
        });
      }
      hadRealtime.value = true;
    }
  }
);

const openCreateDialog = () => {
  resetDraft();
  activeTab.value = 1;
};

const createCalibration = async () => {
  try {
    await store.createCalibration(draftCalibration.value);
    activeTab.value = 0;
    toast.add({
      severity: "success",
      summary: "Created",
      detail: "Calibration created.",
      life: 3000,
    });
  } catch {
    toast.add({
      severity: "error",
      summary: "Error",
      detail: "Failed to create calibration.",
      life: 3000,
    });
  }
};

const openDetails = async (calibrationId: number) => {
  await store.selectCalibration(calibrationId);
  previewPoints.value = [];
  measurementConcentration.value = null;
  activeTab.value = 2;
};

const parseMaxAbsorbance = async (file: File) => {
  const text = await file.text();
  const lines = text.split(/\r?\n/).filter(Boolean);
  let max = 0;
  lines.forEach((line) => {
    const parts = line.split(",");
    const value = Number(parts[1]);
    if (!Number.isNaN(value)) {
      max = Math.max(max, value);
    }
  });
  return max;
};

const handleMeasurementUpload = async (files: File[]) => {
  if (!store.currentCalibration) {
    return;
  }
  if (measurementConcentration.value === null) {
    toast.add({
      severity: "warn",
      summary: "Missing concentration",
      detail: "Enter a concentration before uploading.",
      life: 3000,
    });
    return;
  }
  measurementUpload.uploading = true;
  measurementUpload.total = files.length;
  measurementUpload.done = 0;
  let successCount = 0;
  const failedFiles: string[] = [];

  for (const file of files) {
    try {
      const response = await parseMaxAbsorbance(file);
      await store.uploadMeasurement(
        store.currentCalibration.id,
        file,
        measurementConcentration.value
      );
      previewPoints.value.push({
        concentration: measurementConcentration.value,
        response,
      });
      successCount += 1;
    } catch {
      failedFiles.push(file.name);
    } finally {
      measurementUpload.done += 1;
    }
  }

  measurementUpload.uploading = false;

  if (successCount > 0) {
    toast.add({
      severity: "success",
      summary: "Uploaded",
      detail: `${successCount} measurement(s) uploaded.`,
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

const fitModel = async () => {
  if (!store.currentCalibration) {
    return;
  }
  try {
    const result = await store.fitModel(
      store.currentCalibration.id,
      modelType.value,
      {},
      versionName.value || undefined
    );
    fitJobId.value = result.job_id;
    await store.fetchModels(store.currentCalibration.id);
  } catch {
    toast.add({
      severity: "error",
      summary: "Fit failed",
      detail: "Unable to start fit job.",
      life: 3000,
    });
  }
};

const activateModel = async (modelId: number) => {
  if (!store.currentCalibration) {
    return;
  }
  await store.activateModel(store.currentCalibration.id, modelId);
};

const exportCalibration = () => {
  if (!store.currentCalibration) {
    return;
  }
  const payload = {
    calibration: store.currentCalibration,
    measurements: store.measurements,
    models: store.models,
  };
  downloadJson(payload, `calibration_${store.currentCalibration.id}.json`);
  downloadCsv(
    [
      ["file_path", "concentration", "created_at"],
      ...store.measurements.map((item) => [
        item.file_path,
        item.concentration,
        item.created_at,
      ]),
    ],
    `calibration_${store.currentCalibration.id}_measurements.csv`
  );
};
</script>

<style scoped>
.calibration-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.ws-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid #fde047;
  background: #fefce8;
  color: #a16207;
  font-size: 0.85rem;
}

.ws-status.disconnected {
  border-color: #fecaca;
  background: #fef2f2;
  color: #b91c1c;
}

.ws-status.connecting {
  border-color: #fde047;
  background: #fefce8;
  color: #a16207;
}

.plot-panel {
  min-height: 520px;
}

.tab-actions {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.mt-2 {
  margin-top: 12px;
}

.mt-3 {
  margin-top: 16px;
}
</style>
