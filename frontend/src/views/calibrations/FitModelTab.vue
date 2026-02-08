<template>
  <div class="fit-model-tab">
    <div v-if="!calibrationId" class="empty-state">
      <i class="pi pi-chart-line" style="font-size: 3rem; color: #94a3b8"></i>
      <h3>No Calibration Selected</h3>
      <p>Select a calibration from the Overview tab to start fitting models.</p>
    </div>

    <div v-else class="fit-content">
      <!-- Left Column: Measurements & Fit Controls -->
      <div class="left-column">
        <div class="tab-section">
          <div class="section-header">
            <h3>Measurements</h3>
            <Button
              label="Export"
              icon="pi pi-download"
              class="p-button-text p-button-sm"
              @click="exportMeasurements"
            />
          </div>

          <div class="upload-section">
            <div class="form-grid two">
              <div class="field">
                <label for="concentration">Concentration <span class="required">*</span></label>
                <InputNumber
                  id="concentration"
                  v-model="measurementConcentration"
                  :min="0"
                  :step="0.1"
                  placeholder="Enter value"
                />
              </div>
              <div class="field">
                <label>Upload File</label>
                <FileUploader
                  title="Drop measurement CSV"
                  helper="Upload one measurement at a time"
                  :disabled="measurementUpload.uploading"
                  @files-selected="handleMeasurementUpload"
                />
              </div>
            </div>

            <div v-if="measurementUpload.uploading" class="upload-status">
              <ProgressBar :value="uploadProgress" :showValue="true" />
              <p class="muted-text">
                Uploading {{ measurementUpload.done }}/{{ measurementUpload.total }}...
              </p>
            </div>
          </div>

          <DataTable
            :value="store.measurements"
            stripedRows
            :rows="10"
            :paginator="store.measurements.length > 10"
            class="measurements-table"
          >
            <Column field="file_path" header="File">
              <template #body="slotProps">
                {{ slotProps.data.file_path.split("/").pop() }}
              </template>
            </Column>
            <Column field="concentration" header="Concentration" sortable />
            <Column header="Uploaded">
              <template #body="slotProps">
                {{ formatDateTime(slotProps.data.created_at) }}
              </template>
            </Column>
          </DataTable>
        </div>

        <div class="tab-section">
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
              <label for="model-type">Model Type</label>
              <Dropdown
                id="model-type"
                v-model="modelType"
                :options="modelOptions"
                placeholder="Select model"
              />
            </div>
            <div class="field">
              <label for="version-name">Version Name</label>
              <InputText
                id="version-name"
                v-model="versionName"
                placeholder="Optional"
              />
            </div>
          </div>

          <Button
            label="Fit Model"
            icon="pi pi-play"
            class="fit-button"
            :loading="store.loading"
            :disabled="store.measurements.length < 2"
            @click="fitModel"
          />

          <div v-if="fitJob" class="job-progress">
            <JobProgressBar
              :progress="fitJob.progress"
              :status="fitJob.status"
              :message="fitJob.progress_message"
            />
          </div>
        </div>
      </div>

      <!-- Right Column: Calibration Plot -->
      <div class="right-column">
        <div class="tab-section plot-section">
          <div class="section-header">
            <h3>Calibration Curve</h3>
          </div>

          <div v-if="previewPoints.length === 0" class="empty-plot">
            <i class="pi pi-chart-scatter" style="font-size: 2rem; color: #cbd5e1"></i>
            <p>Upload measurements to see calibration curve preview</p>
          </div>

          <PlotlyChart v-else :data="plotData" :layout="plotLayout" />

          <div class="plot-info">
            <small class="muted-text">
              Preview plot uses uploaded CSV response maxima.
              Fit models in the Models tab for detailed results.
            </small>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, reactive } from "vue";
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import ProgressBar from "primevue/progressbar";
import { useToast } from "primevue/usetoast";
import { useCalibrationStore } from "@/stores/calibration";
import { useJobStore } from "@/stores/job";
import FileUploader from "@/components/FileUploader.vue";
import JobProgressBar from "@/components/JobProgressBar.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import { downloadCsv } from "@/utils/download";
import { formatDateTime } from "@/utils/format";

interface Props {
  calibrationId: number | null;
}

const props = defineProps<Props>();

const store = useCalibrationStore();
const jobStore = useJobStore();
const toast = useToast();

const measurementConcentration = ref<number | null>(null);
const previewPoints = ref<Array<{ concentration: number; response: number }>>([]);
const modelType = ref("linear");
const versionName = ref("");
const fitJobId = ref<number | null>(null);
const measurementUpload = reactive({ uploading: false, total: 0, done: 0 });

const modelOptions = ["linear", "saturation", "hybrid"];

const uploadProgress = computed(() => {
  if (measurementUpload.total === 0) return 0;
  return (measurementUpload.done / measurementUpload.total) * 100;
});

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
      marker: { size: 10, color: "#3b82f6" },
    },
  ];

  // Add linear fit preview if we have enough points
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
      line: { color: "#10b981", dash: "dash" },
    });
  }
  return traces;
});

const plotLayout = {
  title: { text: "Calibration Curve (Preview)", font: { size: 14 } },
  xaxis: {
    title: { text: "Concentration" },
    showgrid: true,
    gridcolor: "#e2e8f0",
  },
  yaxis: {
    title: { text: "Response (max absorbance)" },
    showgrid: true,
    gridcolor: "#e2e8f0",
  },
  hovermode: "closest",
  template: "plotly_white",
  height: 500,
  margin: { t: 40, r: 20, l: 60, b: 50 },
};

// Watch for calibration changes and reset state
watch(
  () => props.calibrationId,
  async (newId) => {
    if (newId) {
      previewPoints.value = [];
      measurementConcentration.value = null;
      fitJobId.value = null;
      await store.fetchMeasurements(newId);
    }
  },
  { immediate: true }
);

const parseMaxAbsorbance = async (file: File): Promise<number> => {
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
  if (!props.calibrationId) return;

  if (measurementConcentration.value === null) {
    toast.add({
      severity: "warn",
      summary: "Missing concentration",
      detail: "Enter a concentration before uploading",
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
        props.calibrationId,
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
      detail: `${successCount} measurement(s) uploaded`,
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
  if (!props.calibrationId) return;

  try {
    const result = await store.fitModel(
      props.calibrationId,
      modelType.value,
      {},
      versionName.value || undefined
    );
    fitJobId.value = result.job_id;
    await store.fetchModels(props.calibrationId);
    toast.add({
      severity: "info",
      summary: "Fitting Started",
      detail: "Model fitting job has been queued",
      life: 3000,
    });
  } catch {
    toast.add({
      severity: "error",
      summary: "Fit failed",
      detail: "Unable to start fit job",
      life: 3000,
    });
  }
};

const exportMeasurements = () => {
  if (!store.measurements.length) return;

  downloadCsv(
    [
      ["file_path", "concentration", "created_at"],
      ...store.measurements.map((item) => [
        item.file_path,
        item.concentration,
        item.created_at,
      ]),
    ],
    `calibration_${props.calibrationId}_measurements.csv`
  );

  toast.add({
    severity: "success",
    summary: "Exported",
    detail: "Measurements exported to CSV",
    life: 3000,
  });
};
</script>

<style scoped>
.fit-model-tab {
  display: flex;
  flex-direction: column;
  min-height: 600px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
  color: #64748b;
}

.empty-state h3 {
  margin: 16px 0 8px;
  font-size: 1.2rem;
  color: #475569;
}

.fit-content {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.left-column,
.right-column {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.tab-section {
  background: #ffffff;
  border-radius: 8px;
  padding: 20px;
}

.plot-section {
  min-height: 600px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
}

.section-header h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
}

.upload-section {
  margin-bottom: 16px;
}

.form-grid {
  display: grid;
  gap: 16px;
}

.form-grid.two {
  grid-template-columns: 1fr 1fr;
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
  color: #dc2626;
}

.upload-status {
  margin-top: 12px;
}

.measurements-table {
  margin-top: 12px;
}

.fit-button {
  width: 100%;
  margin-top: 16px;
}

.job-progress {
  margin-top: 16px;
}

.empty-plot {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  text-align: center;
  color: #94a3b8;
  background: #f8fafc;
  border-radius: 8px;
  border: 2px dashed #e2e8f0;
}

.empty-plot p {
  margin-top: 12px;
  color: #64748b;
}

.plot-info {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e2e8f0;
}

.muted-text {
  color: #64748b;
  font-size: 0.9rem;
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

@media (max-width: 1200px) {
  .fit-content {
    grid-template-columns: 1fr;
  }
}
</style>
