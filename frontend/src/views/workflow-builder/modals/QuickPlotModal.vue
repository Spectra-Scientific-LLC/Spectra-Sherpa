<template>
  <Dialog
    v-model:visible="visible"
    :header="title"
    :style="{ width: '85vw', maxWidth: '1200px' }"
    modal
    :draggable="false"
    class="quick-plot-modal"
  >
    <div class="plot-container">
      <!-- Plot controls bar -->
      <div class="plot-controls">
        <!-- Plot type selector -->
        <div class="control-group">
          <label>Plot Type</label>
          <Dropdown
            v-model="selectedPlotKey"
            :options="availablePlots"
            optionLabel="label"
            optionValue="key"
            class="plot-type-dropdown"
          />
        </div>

        <!-- Axis selectors (PCA/PLS/Classification scores and biplot) -->
        <template v-if="showAxisControls">
          <div class="control-group">
            <label>X Axis</label>
            <Dropdown
              v-model="xAxis"
              :options="axisOptions"
              optionLabel="label"
              optionValue="value"
              class="axis-dropdown"
            />
          </div>
          <div class="control-group">
            <label>Y Axis</label>
            <Dropdown
              v-model="yAxis"
              :options="axisOptions"
              optionLabel="label"
              optionValue="value"
              class="axis-dropdown"
            />
          </div>
        </template>

        <!-- Feature axis selectors (generic scatter) -->
        <template v-if="showFeatureControls">
          <div class="control-group">
            <label>X Feature</label>
            <Dropdown
              v-model="featureXAxis"
              :options="featureAxisOptions"
              optionLabel="label"
              optionValue="value"
              class="axis-dropdown"
            />
          </div>
          <div class="control-group">
            <label>Y Feature</label>
            <Dropdown
              v-model="featureYAxis"
              :options="featureAxisOptions"
              optionLabel="label"
              optionValue="value"
              class="axis-dropdown"
            />
          </div>
        </template>

        <!-- Regression target selector -->
        <div v-if="showRegressionTargetControl" class="control-group">
          <label>Target</label>
          <Dropdown
            v-model="regressionTargetIdx"
            :options="regressionTargetOptions"
            optionLabel="label"
            optionValue="value"
            class="axis-dropdown"
          />
        </div>

        <!-- Data shape summary -->
        <div class="control-group stats-summary">
          <span class="stat-item">
            <strong>{{ dataShape.rows }}</strong> {{ dataShape.rowLabel }}
          </span>
          <span class="stat-item">
            <strong>{{ dataShape.cols }}</strong> {{ dataShape.colLabel }}
          </span>
          <span v-if="dataShape.range" class="stat-item">
            Range: <strong>{{ dataShape.range[0].toFixed(2) }}</strong> - <strong>{{ dataShape.range[1].toFixed(2) }}</strong>
          </span>
        </div>

        <!-- View toggle: Plot vs Data Table -->
        <div class="control-group view-toggle">
          <Button
            :icon="viewMode === 'plot' ? 'pi pi-chart-line' : 'pi pi-table'"
            :label="viewMode === 'plot' ? 'Plot' : 'Data'"
            :class="['p-button-outlined', 'p-button-sm', viewMode === 'plot' ? 'p-button-primary' : 'p-button-secondary']"
            @click="toggleViewMode"
            :title="viewMode === 'plot' ? 'Switch to Data Table' : 'Switch to Plot'"
          />
        </div>

        <Button
          v-if="viewMode === 'plot'"
          icon="pi pi-download"
          label="Download"
          class="p-button-outlined p-button-sm"
          @click="downloadPlot"
        />
      </div>

      <!-- Plotly chart -->
      <div v-if="viewMode === 'plot'" ref="plotContainerEl" class="plotly-container">
        <PlotlyChart
          v-if="plotData.length > 0"
          :data="plotData"
          :layout="plotLayout"
          :config="PLOT_CONFIG"
        />
        <div v-else class="empty-plot">
          <i class="pi pi-chart-line" />
          <p>No data to display</p>
          <small>Execute the node first to see results</small>
        </div>
      </div>

      <!-- Data Table -->
      <div v-else class="data-table-container">
        <span v-if="dataPreviewSummary" class="data-summary">{{ dataPreviewSummary }}</span>
        <DataTable
          v-if="dataPreview.length > 0"
          :value="dataPreview"
          :scrollable="true"
          scrollHeight="calc(70vh - 120px)"
          class="preview-datatable"
          size="small"
          stripedRows
        >
          <Column
            v-for="col in dataPreviewColumns"
            :key="col.field"
            :field="col.field"
            :header="col.header"
            :style="{ minWidth: '80px', maxWidth: '150px' }"
          />
        </DataTable>
        <div v-else class="empty-plot">
          <i class="pi pi-table" />
          <p>No data to display</p>
          <small>Execute the node first to see results</small>
        </div>
      </div>
    </div>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import Dialog from "primevue/dialog";
import Dropdown from "primevue/dropdown";
import Button from "primevue/button";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import PlotlyChart from "@/components/PlotlyChart.vue";
import { usePlotData, PLOT_CONFIG } from "@/composables/usePlotData";
import {
  normalizeSampleLabel,
  compactSampleLabel,
  detectLabelDelimiter,
  splitLabelByDelimiter,
} from "@/utils/sampleLabels";

interface Props {
  modelValue: boolean;
  nodeOutput: any;
  nodeType: string;
  nodeLabel: string;
  nodeInput?: any;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (e: "update:modelValue", value: boolean): void;
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

const title = computed(() => `${props.nodeLabel} - Output Visualization`);

// Use the shared plot composable (same functions as Detailed View)
const nodeOutputRef = computed(() => props.nodeOutput);
const nodeTypeRef = computed(() => props.nodeType);
const nodeInputRef = computed(() => props.nodeInput);

const {
  availablePlots,
  selectedPlotKey,
  xAxis,
  yAxis,
  featureXAxis,
  featureYAxis,
  regressionTargetIdx,
  axisOptions,
  featureAxisOptions,
  regressionTargetOptions,
  showAxisControls,
  showFeatureControls,
  showRegressionTargetControl,
  plotData,
  plotLayout,
  dataShape,
} = usePlotData(nodeOutputRef, nodeTypeRef, nodeInputRef);

// View mode toggle
const viewMode = ref<"plot" | "data">("plot");
const previewRowLimit = 100;

function toggleViewMode() {
  viewMode.value = viewMode.value === "plot" ? "data" : "plot";
}

// Data preview for table view
const dataPreview = computed(() => {
  const data = props.nodeOutput?.data;
  const metadata = props.nodeOutput?.metadata || {};
  if (!data || !Array.isArray(data)) return [];

  const labelsRaw = metadata.sample_labels || metadata.labels || [];
  const labels = Array.isArray(labelsRaw)
    ? labelsRaw.map((label: any) => normalizeSampleLabel(label))
    : [];
  const delimiter = detectLabelDelimiter(labels);
  const splitLabels = delimiter
    ? labels.map((label: string) => splitLabelByDelimiter(label, delimiter))
    : [];
  const maxParts = splitLabels.length > 0
    ? Math.max(...splitLabels.map((parts: string[]) => parts.length))
    : 0;
  const useSplitColumns = !!delimiter && maxParts > 1;

  return data.slice(0, previewRowLimit).map((row: any, i: number) => {
    const obj: any = { _index: i + 1, _label_full: labels[i] || "" };
    if (labels.length > 0) {
      if (useSplitColumns) {
        const parts = splitLabels[i] || [];
        for (let labelIdx = 0; labelIdx < maxParts; labelIdx += 1) {
          obj[`_label_${labelIdx}`] = compactSampleLabel(parts[labelIdx] || "", {
            maxLength: 42, headLength: 28, tailLength: 12,
          });
        }
      } else {
        obj._label = compactSampleLabel(labels[i] || "", {
          maxLength: 52, headLength: 34, tailLength: 14,
        });
      }
    }
    if (Array.isArray(row)) {
      row.slice(0, 10).forEach((val: any, j: number) => {
        obj[`col_${j}`] = typeof val === "number" ? val.toFixed(4) : val;
      });
    } else {
      obj.value = typeof row === "number" ? row.toFixed(4) : row;
    }
    return obj;
  });
});

const dataPreviewSummary = computed(() => {
  const data = props.nodeOutput?.data;
  if (!data || !Array.isArray(data)) return "";
  const totalRows = data.length;
  const totalCols = Array.isArray(data[0]) ? data[0].length : 1;
  const shownRows = Math.min(totalRows, previewRowLimit);
  const shownCols = Math.min(totalCols, 10);
  let summary = `${shownRows} of ${totalRows} rows`;
  if (totalCols > 10) summary += `, ${shownCols} of ${totalCols} columns`;
  return summary;
});

const dataPreviewColumns = computed(() => {
  if (!dataPreview.value.length) return [];
  const first = dataPreview.value[0] as Record<string, any>;
  const metadata = props.nodeOutput?.metadata || {};
  const pcLabels = metadata.pc_labels || [];
  const _featureNames = metadata.feature_names || [];
  const xTitle = metadata.x_title || "";
  const isPCA = metadata.type === "PCA" || metadata.isPCA;
  const isMCR = metadata.type === "MCR_ALS";
  const mcrLabels = Array.isArray(metadata.labels)
    ? metadata.labels.map((item: any) => normalizeSampleLabel(item)).filter((s: string) => s.length > 0)
    : [];

  return Object.keys(first)
    .filter((key) => key !== "_label_full")
    .map((key) => {
      let header = key;
      if (key === "_index") {
        header = "#";
      } else if (key === "_label") {
        header = "Label";
      } else if (key.startsWith("_label_")) {
        const labelIdx = Number.parseInt(key.replace("_label_", ""), 10);
        header = Number.isNaN(labelIdx) ? "Label" : `Field ${labelIdx + 1}`;
      } else if (key.startsWith("col_")) {
        const colIdx = parseInt(key.replace("col_", ""));
        if (isPCA && pcLabels[colIdx]) {
          header = pcLabels[colIdx];
        } else if (isMCR && mcrLabels[colIdx]) {
          header = mcrLabels[colIdx];
        } else if (_featureNames.length > colIdx) {
          header = _featureNames[colIdx];
        } else if (xTitle && xTitle !== "Feature") {
          header = `${xTitle} ${colIdx + 1}`;
        } else {
          header = `Col ${colIdx + 1}`;
        }
      }
      return { field: key, header };
    });
});

// Download functionality
const plotContainerEl = ref<HTMLElement | null>(null);

function downloadPlot() {
  const plotDiv = plotContainerEl.value?.querySelector(".js-plotly-plot") as HTMLElement;
  const PlotlyGlobal = (window as unknown as { Plotly?: { downloadImage: (el: HTMLElement, opts: Record<string, unknown>) => void } }).Plotly;
  if (plotDiv && PlotlyGlobal) {
    PlotlyGlobal.downloadImage(plotDiv, {
      format: "png",
      width: 1200,
      height: 800,
      filename: `${props.nodeLabel.replace(/\s+/g, "_")}_output`,
    });
  }
}
</script>

<style scoped>
.quick-plot-modal :deep(.p-dialog-content) {
  padding: 0;
  background: #0f172a;
}

.plot-container {
  display: flex;
  flex-direction: column;
  height: 70vh;
  min-height: 500px;
}

.plot-controls {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 12px 20px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
  flex-wrap: wrap;
}

.control-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.control-group label {
  font-size: 0.85rem;
  color: #94a3b8;
  white-space: nowrap;
}

.plot-type-dropdown {
  min-width: 200px;
}

.axis-dropdown {
  min-width: 160px;
}

.stats-summary {
  margin-left: auto;
  gap: 16px;
}

.stat-item {
  font-size: 0.85rem;
  color: #94a3b8;
}

.stat-item strong {
  color: #f8fafc;
}

.plotly-container {
  flex: 1;
  padding: 16px;
  overflow: auto;
}

.plotly-container :deep(.js-plotly-plot) {
  width: 100%;
  height: 100%;
}

.empty-plot {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #64748b;
}

.empty-plot i {
  font-size: 3rem;
  margin-bottom: 16px;
  color: #475569;
}

.empty-plot p {
  font-size: 1.1rem;
  margin: 0 0 8px;
}

.empty-plot small {
  font-size: 0.85rem;
  color: #475569;
}

/* View toggle button */
.view-toggle {
  margin-left: 8px;
}

/* Data table container */
.data-table-container {
  flex: 1;
  padding: 16px;
  overflow: auto;
  background: #0f172a;
}

.data-summary {
  display: block;
  font-size: 0.8rem;
  color: #94a3b8;
  margin-bottom: 8px;
}

.preview-datatable {
  font-size: 0.85rem;
}

:deep(.preview-datatable .p-datatable-thead > tr > th) {
  background: #1e293b;
  color: #f8fafc;
  border-color: #334155;
  font-weight: 600;
  padding: 8px 12px;
}

:deep(.preview-datatable .p-datatable-tbody > tr) {
  background: #0f172a;
  color: #e2e8f0;
}

:deep(.preview-datatable .p-datatable-tbody > tr > td) {
  border-color: #334155;
  padding: 6px 12px;
}

:deep(.preview-datatable .p-datatable-tbody > tr:nth-child(even)) {
  background: #1e293b;
}

:deep(.preview-datatable .p-datatable-tbody > tr:hover) {
  background: #334155;
}

/* PrimeVue overrides for dark theme */
:deep(.p-dropdown) {
  background: #0f172a;
  border-color: #334155;
}

:deep(.p-dropdown:hover) {
  border-color: #475569;
}

:deep(.p-dialog) {
  background: #1e293b;
  border: 1px solid #334155;
}

:deep(.p-dialog-header) {
  background: #1e293b;
  color: #f8fafc;
  border-bottom: 1px solid #334155;
  padding: 16px 20px;
}

:deep(.p-dialog-header-icon) {
  color: #94a3b8;
}

:deep(.p-dialog-header-icon:hover) {
  background: #334155;
  color: #f8fafc;
}
</style>
