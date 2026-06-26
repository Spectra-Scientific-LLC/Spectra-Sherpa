<template>
  <section class="contents-panel" aria-label="Dataset contents">
    <div class="contents-panel-header">
      <div>
        <h3>Contents</h3>
        <p>
          {{ contentsSubtitle }}
        </p>
      </div>
    </div>

    <div v-if="dataStore.fileInfoLoading" class="explore-loading">
      <ProgressSpinner style="width: 36px; height: 36px" />
      <span>Loading contents...</span>
    </div>

    <div v-else-if="dataStore.fileInfoError" class="explore-error">
      <i class="pi pi-exclamation-triangle"></i>
      <span>{{ dataStore.fileInfoError }}</span>
    </div>

    <div v-else-if="dataStore.catalogDatasetLoading" class="explore-loading">
      <ProgressSpinner style="width: 36px; height: 36px" />
      <span>Loading dataset info...</span>
    </div>

    <div v-else-if="dataStore.catalogDatasetError" class="explore-error">
      <i class="pi pi-exclamation-triangle"></i>
      <span>{{ dataStore.catalogDatasetError }}</span>
    </div>

    <div v-else-if="dataStore.catalogDatasetInfo" class="explore-content">
      <div class="explore-header">
        <div class="explore-title">
          <i class="pi pi-database"></i>
          <span>{{ dataStore.catalogDatasetInfo.label }}</span>
          <Tag
            v-if="dataStore.catalogDatasetInfo.technique"
            :value="dataStore.catalogDatasetInfo.technique"
            severity="info"
          />
        </div>
      </div>

      <div v-if="catalogBoxPlotData.length" class="explore-table">
        <div class="table-summary">
          <Tag value="Properties" severity="info" />
          <span class="meta-val">
            {{ dataStore.catalogDatasetInfo.n_samples?.toLocaleString() }} samples
            &times;
            {{ dataStore.catalogDatasetInfo.n_features }} features
          </span>
        </div>
        <PlotlyChart
          :data="catalogBoxPlotData"
          :layout="catalogBoxPlotLayout"
          :config="{ displayModeBar: true, displaylogo: false }"
        />
      </div>
      <div v-else-if="catalogPreviewPlotData.length" class="explore-plot">
        <PlotlyChart
          :data="catalogPreviewPlotData"
          :layout="catalogPreviewPlotLayout"
          :config="{ displayModeBar: true, displaylogo: false }"
        />
      </div>

      <div class="explore-panels">
        <div class="metadata-panel">
          <h4 class="panel-title">Dataset Metadata</h4>
          <div class="metadata-table">
            <div v-if="dataStore.catalogDatasetInfo.source" class="meta-row">
              <span class="meta-key">Source</span>
              <span class="meta-val">{{ dataStore.catalogDatasetInfo.source }}</span>
            </div>
            <div v-if="dataStore.catalogDatasetInfo.file_metadata?.name" class="meta-row">
              <span class="meta-key">Title</span>
              <span class="meta-val">{{ dataStore.catalogDatasetInfo.file_metadata.name }}</span>
            </div>
            <div v-if="dataStore.catalogDatasetInfo.n_samples" class="meta-row">
              <span class="meta-key">Samples</span>
              <span class="meta-val">{{ dataStore.catalogDatasetInfo.n_samples.toLocaleString() }}</span>
            </div>
            <div v-if="dataStore.catalogDatasetInfo.n_features" class="meta-row">
              <span class="meta-key">Features</span>
              <span class="meta-val">{{ dataStore.catalogDatasetInfo.n_features.toLocaleString() }}</span>
            </div>
            <div v-if="dataStore.catalogDatasetInfo.wavelength_min != null" class="meta-row">
              <span class="meta-key">Spectral Range</span>
              <span class="meta-val">
                {{ dataStore.catalogDatasetInfo.wavelength_min.toFixed(1) }} &ndash;
                {{ dataStore.catalogDatasetInfo.wavelength_max?.toFixed(1) }}
                {{ dataStore.catalogDatasetInfo.x_units || '' }}
              </span>
            </div>
            <div v-if="dataStore.catalogDatasetInfo.task_type" class="meta-row">
              <span class="meta-key">Task Type</span>
              <span class="meta-val">{{ dataStore.catalogDatasetInfo.task_type }}</span>
            </div>
            <div v-if="dataStore.catalogDatasetInfo.target_names?.length" class="meta-row">
              <span class="meta-key">Classes</span>
              <span class="meta-val">{{ dataStore.catalogDatasetInfo.target_names.join(', ') }}</span>
            </div>
            <MetadataEditor
              v-model:x-title="editXTitle"
              v-model:x-units="editXUnits"
              v-model:y-title="editYTitle"
              v-model:is-time-series="isTimeSeriesToggle"
              v-model:target-mode="targetMode"
              v-model:selected-target="selectedTarget"
              :x-title-options="xTitleOptions"
              :x-units-options="xUnitsOptions"
              :y-title-options="yTitleOptions"
              :target-options="targetOptions"
              :show-target-controls="showTargetControls"
            />
          </div>
        </div>

        <div class="metadata-panel">
          <div v-if="dataStore.catalogDatasetInfo.property_stats?.length">
            <h4 class="panel-title">Reference Properties</h4>
            <PropertyStatsTable :stats="dataStore.catalogDatasetInfo.property_stats" />
          </div>
          <div v-else>
            <h4 class="panel-title">Description</h4>
            <p class="dataset-description">
              {{ dataStore.catalogDatasetInfo.description }}
            </p>
          </div>
        </div>
      </div>

      <DataStorySection />
    </div>

    <div v-else-if="!dataStore.fileInfo" class="explore-empty">
      <i class="pi pi-table"></i>
      <h3>No contents selected</h3>
      <p>Select a dataset name to view all raw contents, or select a file to view that file alone.</p>
    </div>

    <div v-else class="explore-content">
      <div class="explore-header">
        <div class="explore-title">
          <i class="pi pi-file"></i>
          <span>{{ contentsTitle }}</span>
          <Tag v-if="contentsFileCount" :value="`${contentsFileCount} file${contentsFileCount === 1 ? '' : 's'}`" severity="info" />
        </div>
      </div>

      <div v-if="isTabular" class="explore-table">
        <div class="table-summary">
          <Tag value="Properties" severity="info" />
          <span class="meta-val">
            {{ dataStore.fileInfo.n_samples?.toLocaleString() }} samples
            &times;
            {{ dataStore.fileInfo.n_features }} properties
          </span>
        </div>
        <PlotlyChart
          :data="boxPlotData"
          :layout="boxPlotLayout"
          :config="{ displayModeBar: true, displaylogo: false }"
        />
      </div>

      <div v-else-if="hasSpectra" class="explore-plot">
        <PlotlyChart
          :data="previewPlotData"
          :layout="previewPlotLayout"
          :config="{ displayModeBar: true, displaylogo: false }"
        />
      </div>

      <div v-if="propertyStats.length > 0" class="explore-panels">
        <div class="metadata-panel" style="flex: 1">
          <h4 class="panel-title">Reference Properties</h4>
          <PropertyStatsTable :stats="propertyStats" />
        </div>
      </div>

      <div class="explore-panels">
        <div class="metadata-panel">
          <h4 class="panel-title">{{ metadataPanelTitle }}</h4>
          <div class="metadata-table">
            <div class="meta-row">
              <span class="meta-key">Files</span>
              <span class="meta-val">{{ contentsFileCount || 1 }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-key">Samples</span>
              <span class="meta-val">{{ dataStore.fileInfo.n_samples?.toLocaleString() }}</span>
            </div>
            <div class="meta-row">
              <span class="meta-key">Features</span>
              <span class="meta-val">{{ dataStore.fileInfo.n_features?.toLocaleString() }}</span>
            </div>
            <div v-if="sdMeta.spectral_technique" class="meta-row">
              <span class="meta-key">Technique</span>
              <Tag :value="String(sdMeta.spectral_technique)" severity="info" />
            </div>
            <MetadataEditor
              v-model:x-title="editXTitle"
              v-model:x-units="editXUnits"
              v-model:y-title="editYTitle"
              v-model:is-time-series="isTimeSeriesToggle"
              v-model:target-mode="targetMode"
              v-model:selected-target="selectedTarget"
              :x-title-options="xTitleOptions"
              :x-units-options="xUnitsOptions"
              :y-title-options="yTitleOptions"
              :target-options="targetOptions"
              :show-target-controls="showTargetControls"
            />
          </div>
        </div>

        <DataQualityPanel
          v-if="hasMatrixData"
          :datasetDict="dataStore.fileInfo"
          :loading="dataStore.fileInfoLoading"
        />
      </div>

      <DataStorySection />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, ref, watch, type VNodeChild } from "vue";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Dropdown from "primevue/dropdown";
import InputSwitch from "primevue/inputswitch";
import ProgressSpinner from "primevue/progressspinner";
import Tag from "primevue/tag";
import Textarea from "primevue/textarea";
import Button from "primevue/button";
import api from "@/api/client";
import MemoryAttribution from "@/components/MemoryAttribution.vue";
import PlotlyChart from "@/components/PlotlyChart.vue";
import { useAppConfig } from "@/composables/useAppConfig";
import { useDataStore, type CatalogDatasetInfo, type DataStoryPropertyStat } from "@/stores/data";
import { useSherpaStore } from "@/stores/sherpa";
import DataQualityPanel from "./DataQualityPanel.vue";

const dataStore = useDataStore();
const sherpaStore = useSherpaStore();
const { isFeatureEnabled } = useAppConfig();

const PLOT_COLORS = [
  "#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6",
  "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#6366f1",
  "#e11d48", "#84cc16", "#0ea5e9", "#d946ef", "#a3e635",
  "#2dd4bf", "#fb923c", "#818cf8", "#f472b6", "#34d399",
];

const xTitleOptions = [
  "Wavenumber", "Wavelength", "Raman Shift", "m/z", "Time",
  "Energy", "Channel", "Index",
];
const xUnitsMap: Record<string, string[]> = {
  "Wavenumber": ["cm\u207B\u00B9"],
  "Wavelength": ["nm", "\u00B5m"],
  "Raman Shift": ["cm\u207B\u00B9"],
  "m/z": ["Da", "Th"],
  "Time": ["s", "min", "h"],
  "Energy": ["eV", "keV"],
  "Channel": [""],
  "Index": [""],
};
const yTitleOptions = [
  "Intensity", "Absorbance", "Transmittance", "Reflectance", "Response",
];

const editXTitle = ref("");
const editXUnits = ref("");
const editYTitle = ref("");
const isTimeSeriesToggle = ref(false);
const targetMode = ref<"single" | "multi">("single");
const selectedTarget = ref("");

const xUnitsOptions = computed(() => {
  const units = xUnitsMap[editXTitle.value];
  if (units) return units.filter((u) => u !== "");
  return [];
});

const contentsFileCount = computed(() => {
  const metadata = dataStore.fileInfo?.metadata as Record<string, unknown> | undefined;
  const count = metadata?.contents_file_count;
  return typeof count === "number" && Number.isFinite(count) ? count : dataStore.activeFileId ? 1 : null;
});

const contentsTitle = computed(() => {
  const metadata = dataStore.fileInfo?.metadata as Record<string, unknown> | undefined;
  const title = metadata?.contents_title;
  if (typeof title === "string" && title.trim()) return title;
  if (dataStore.activeFilePath) return extractFileName(dataStore.activeFilePath);
  return dataStore.fileInfo?.title || "Dataset contents";
});

const metadataPanelTitle = computed(() =>
  dataStore.activeFileId ? "File Metadata" : "Dataset Metadata"
);

const contentsSubtitle = computed(() => {
  if (dataStore.activeFileId) return "Single-file view";
  if (dataStore.fileInfo) return "Dataset-level raw contents";
  return "Select a dataset or file from My Dataset.";
});

function targetNamesFromContext(context: unknown): string[] {
  if (!context || typeof context !== "object") return [];
  const record = context as Record<string, unknown>;
  const raw = record.target_names ?? record.class_names;
  return Array.isArray(raw) ? raw.map((item) => String(item)).filter(Boolean) : [];
}

const targetOptions = computed(() => {
  const fileTargets = targetNamesFromContext(dataStore.fileInfo?.target_context);
  if (fileTargets.length) return fileTargets;
  const catalogTargets = dataStore.catalogDatasetInfo?.target_names ?? [];
  return Array.isArray(catalogTargets) ? catalogTargets.map((item) => String(item)).filter(Boolean) : [];
});

const showTargetControls = computed(() => targetOptions.value.length > 1);

function syncTargetControls(metadata: Record<string, unknown> | undefined, targetNames: string[]) {
  const mode = metadata?.target_mode === "multi" ? "multi" : "single";
  targetMode.value = targetNames.length > 1 ? mode : "single";
  const savedTarget = typeof metadata?.selected_target === "string" ? metadata.selected_target : "";
  selectedTarget.value = savedTarget && targetNames.includes(savedTarget)
    ? savedTarget
    : (targetNames[0] ?? "");
}

function _syncFromFileInfo(fi: { metadata?: Record<string, unknown> } | null) {
  const m = fi?.metadata as Record<string, unknown> | undefined;
  editXTitle.value = (m?.x_title ?? "") as string;
  editXUnits.value = (m?.x_units ?? "") as string;
  editYTitle.value = (m?.data_quantity ?? "") as string;
  isTimeSeriesToggle.value = !!(m?.is_time_series);
  syncTargetControls(m, targetNamesFromContext((fi as Record<string, unknown> | null)?.target_context));
}

function _syncFromCatalog(info: CatalogDatasetInfo | null) {
  const m = info?.metadata as Record<string, unknown> | undefined;
  editXTitle.value = (info?.x_title ?? "") as string;
  editXUnits.value = (info?.x_units ?? "") as string;
  editYTitle.value = (info?.data_quantity ?? "") as string;
  isTimeSeriesToggle.value = !!m?.is_time_series
    || !!(info?.is_time_series);
  syncTargetControls(m, Array.isArray(info?.target_names) ? info.target_names.map((item) => String(item)) : []);
}

watch(() => dataStore.fileInfo, _syncFromFileInfo);
watch(() => dataStore.catalogDatasetInfo, _syncFromCatalog);

async function persistMetadataOverride() {
  const xTitle = editXTitle.value;
  const xUnits = editXUnits.value;
  const yTitle = editYTitle.value;
  const isTimeSeries = isTimeSeriesToggle.value;
  const targetNames = targetOptions.value;
  const targetModeValue = targetNames.length > 1 ? targetMode.value : null;
  const selectedTargetValue = targetModeValue === "single" ? (selectedTarget.value || targetNames[0] || null) : null;
  const body: Record<string, unknown> = {
    x_title: xTitle,
    x_units: xUnits,
    y_title: yTitle,
    is_time_series: isTimeSeries,
    target_mode: targetModeValue,
    selected_target: selectedTargetValue,
  };

  const catInfo = dataStore.catalogDatasetInfo;
  if (catInfo?.source && catInfo?.name) {
    body.source = catInfo.source;
    body.name = catInfo.name;
  } else if (dataStore.activeFilePath) {
    body.file_path = dataStore.activeFilePath;
    if (dataStore.activeExperimentId) body.experiment_id = dataStore.activeExperimentId;
  } else {
    return;
  }

  try {
    await api.patch("/builder/file-metadata", body);
    const fi = dataStore.fileInfo;
    if (fi && typeof fi === "object") {
      const fiAny = fi as Record<string, unknown> & { metadata?: Record<string, unknown> };
      if (fiAny.metadata && typeof fiAny.metadata === "object") {
        fiAny.metadata.x_title = xTitle;
        fiAny.metadata.x_units = xUnits;
        fiAny.metadata.data_quantity = yTitle;
        fiAny.metadata.is_time_series = isTimeSeries;
        fiAny.metadata.target_mode = targetModeValue;
        fiAny.metadata.selected_target = selectedTargetValue;
      }
      fiAny.x_title = xTitle;
      fiAny.x_units = xUnits;
      fiAny.data_quantity = yTitle;
      fiAny.is_time_series = isTimeSeries;
    }
    if (catInfo) {
      const ciAny = catInfo as Record<string, unknown>;
      ciAny.x_title = xTitle;
      ciAny.x_units = xUnits;
      ciAny.data_quantity = yTitle;
      ciAny.is_time_series = isTimeSeries;
      const ciMeta = (ciAny.metadata ?? {}) as Record<string, unknown>;
      ciMeta.target_mode = targetModeValue;
      ciMeta.selected_target = selectedTargetValue;
      ciAny.metadata = ciMeta;
    }
  } catch (err) {
    console.warn("Failed to persist metadata override", err);
  }
}

let _persistTimer: ReturnType<typeof setTimeout> | null = null;
function schedulePersist() {
  if (_persistTimer) clearTimeout(_persistTimer);
  _persistTimer = setTimeout(persistMetadataOverride, 500);
}

watch(editXTitle, schedulePersist);
watch(editXUnits, schedulePersist);
watch(editYTitle, schedulePersist);
watch(isTimeSeriesToggle, schedulePersist);
watch(targetMode, schedulePersist);
watch(selectedTarget, schedulePersist);

const sdMeta = computed(() => {
  const m = dataStore.fileInfo?.metadata as Record<string, unknown> | undefined;
  const xAxis = dataStore.fileInfo?.x_axis;
  const axisData = Array.isArray(xAxis?.data) ? xAxis.data : [];
  const metadataWavenumbers = Array.isArray(m?.wavenumbers) ? m.wavenumbers : [];
  return {
    wavenumbers: (metadataWavenumbers.length ? metadataWavenumbers : axisData) as number[],
    labels: (m?.labels ?? m?.sample_labels ?? []) as string[],
    x_title: editXTitle.value,
    x_units: editXUnits.value,
    spectral_technique: (m?.spectral_technique ?? null) as string | null,
    data_quantity: editYTitle.value,
    value_units: (m?.value_units ?? null) as string | null,
    prop_names: (m?.prop_names ?? []) as string[],
    properties: (m?.properties ?? null) as Record<string, number[]> | null,
  };
});

const propertyStats = computed(() => {
  const { properties, prop_names } = sdMeta.value;
  if (!properties || !prop_names.length) return [];
  return prop_names.map((name) => {
    const vals = (properties[name] ?? []).filter((v) => v != null && isFinite(v));
    if (!vals.length) return { name, min: null, max: null, mean: null };
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
    return { name, min, max, mean };
  });
});

const isTabular = computed(() => {
  const fi = dataStore.fileInfo;
  if (!fi) return false;
  const metadata = fi.metadata as Record<string, unknown> | undefined;
  const declaredSpectra = fi.data_role === "X_spectra" || metadata?.data_role === "X_spectra" || metadata?.is_spectra === true;
  if (declaredSpectra) return false;
  if (sdMeta.value.wavenumbers.length === fi.n_features) return false;
  return fi.x_axis?.labels != null && fi.x_axis.labels.length > 0;
});

const hasSpectra = computed(() => {
  const fi = dataStore.fileInfo;
  if (!fi?.data?.length) return false;
  const metadata = fi.metadata as Record<string, unknown> | undefined;
  return !isTabular.value || fi.data_role === "X_spectra" || metadata?.data_role === "X_spectra" || metadata?.is_spectra === true;
});

const hasMatrixData = computed(() => {
  const fi = dataStore.fileInfo;
  return !!fi?.data?.length;
});

const previewPlotData = computed(() => {
  const fi = dataStore.fileInfo;
  if (!fi?.data?.length) return [];
  const wavenumbers = sdMeta.value.wavenumbers.length
    ? sdMeta.value.wavenumbers
    : Array.from({ length: fi.n_features }, (_, i) => i);
  const labels = sdMeta.value.labels;
  const maxTraces = Math.min(fi.data.length, 50);
  return fi.data.slice(0, maxTraces).map((spectrum, i) => ({
    x: wavenumbers,
    y: spectrum,
    type: "scatter" as const,
    mode: "lines" as const,
    name: labels[i] || `Spectrum ${i + 1}`,
    line: { color: PLOT_COLORS[i % PLOT_COLORS.length], width: 1.2 },
  }));
});

const xAxisLabel = computed(() => {
  const { x_title, x_units } = sdMeta.value;
  if (x_title && x_units) return `${x_title} (${x_units})`;
  if (x_title) return x_title;
  return "";
});

const yAxisLabel = computed(() => sdMeta.value.data_quantity || sdMeta.value.value_units || "");

const previewPlotLayout = computed(() => ({
  title: { text: "Spectra Preview", font: { size: 14 } },
  xaxis: { title: xAxisLabel.value, autorange: true as const },
  yaxis: { title: yAxisLabel.value },
  autosize: true,
  height: 380,
  margin: { t: 40, r: 20, b: 50, l: 60 },
  showlegend: (dataStore.fileInfo?.data?.length ?? 0) <= 20,
  legend: { font: { size: 10 }, orientation: "h" as const, y: -0.25 },
  plot_bgcolor: "#fafafa",
  paper_bgcolor: "#ffffff",
}));

const boxPlotData = computed(() => {
  const fi = dataStore.fileInfo;
  const labels = fi?.x_axis?.labels;
  if (!labels?.length || !fi?.data?.length) return [];
  return labels.map((col, colIdx) => ({
    type: "box" as const,
    y: fi.data.map((row) => row[colIdx]).filter((v): v is number => v !== null && typeof v === "number"),
    name: col,
    marker: { color: PLOT_COLORS[colIdx % PLOT_COLORS.length] },
    boxpoints: false,
  }));
});

const boxPlotLayout = computed(() => ({
  title: { text: "Property Distributions", font: { size: 14 } },
  xaxis: { title: "Property" },
  yaxis: { title: sdMeta.value.value_units || sdMeta.value.x_title || "" },
  autosize: true,
  height: 400,
  margin: { t: 40, r: 20, b: 50, l: 60 },
  showlegend: false,
  plot_bgcolor: "#fafafa",
  paper_bgcolor: "#ffffff",
}));

const catalogPreviewPlotData = computed(() => {
  const info = dataStore.catalogDatasetInfo;
  const spectra = info?.preview_spectra;
  if (!spectra?.length || info?.feature_labels?.length) return [];
  const firstRow = spectra[0] ?? [];
  const wavelengths = info?.wavelengths?.length
    ? info.wavelengths
    : Array.from({ length: firstRow.length }, (_, i) => i);
  return spectra.map((spectrum, i) => ({
    x: wavelengths,
    y: spectrum,
    type: "scatter" as const,
    mode: "lines" as const,
    name: `Spectrum ${i + 1}`,
    line: { color: PLOT_COLORS[i % PLOT_COLORS.length], width: 1.2 },
  }));
});

const catalogPreviewPlotLayout = computed(() => {
  const info = dataStore.catalogDatasetInfo;
  const xTitle = editXTitle.value || info?.x_title || "";
  const xUnits = editXUnits.value || info?.x_units || "";
  return {
    title: { text: "Spectra Preview", font: { size: 14 } },
    xaxis: { title: xTitle && xUnits ? `${xTitle} (${xUnits})` : xTitle, autorange: true as const },
    yaxis: { title: editYTitle.value || info?.data_quantity || "" },
    autosize: true,
    height: 380,
    margin: { t: 40, r: 20, b: 50, l: 60 },
    showlegend: (catalogPreviewPlotData.value.length ?? 0) <= 20,
    legend: { font: { size: 10 }, orientation: "h" as const, y: -0.25 },
    plot_bgcolor: "#fafafa",
    paper_bgcolor: "#ffffff",
  };
});

const catalogBoxPlotData = computed(() => {
  const info = dataStore.catalogDatasetInfo;
  const labels = info?.feature_labels;
  const spectra = info?.preview_spectra;
  if (!labels?.length || !spectra?.length) return [];
  return labels.map((col, colIdx) => ({
    type: "box" as const,
    y: spectra.map((row) => row[colIdx]).filter((v): v is number => v !== null && typeof v === "number"),
    name: col,
    marker: { color: PLOT_COLORS[colIdx % PLOT_COLORS.length] },
    boxpoints: false,
  }));
});

const catalogBoxPlotLayout = computed(() => ({
  title: { text: "Feature Distributions", font: { size: 14 } },
  xaxis: { title: "Feature" },
  yaxis: { title: editYTitle.value || "" },
  autosize: true,
  height: 400,
  margin: { t: 40, r: 20, b: 80, l: 60 },
  showlegend: false,
  plot_bgcolor: "#fafafa",
  paper_bgcolor: "#ffffff",
}));

const isDataStoryButtonDisabled = computed(() => sherpaStore.isSyncing || sherpaStore.isChatting);
const dataStoryButtonLabel = computed(() =>
  dataStore.dataStoryText ? "Regenerate Data Story" : "Generate Data Story"
);
const dataStoryButtonHoverText = computed(() =>
  isDataStoryButtonDisabled.value ? "Available when Sherpa Advisor finishes" : ""
);

function extractFileName(filePath: string): string {
  return filePath.split("/").pop() || filePath;
}

const PropertyStatsTable = defineComponent({
  name: "PropertyStatsTable",
  props: {
    stats: { type: Array as () => DataStoryPropertyStat[], required: true },
  },
  setup(props) {
    return () => h(DataTable, { value: props.stats, size: "small", stripedRows: true, class: "prop-stats-table" }, {
      default: () => [
        h(Column, { field: "name", header: "Property" }),
        h(Column, { header: "Range" }, {
          body: ({ data }: { data: DataStoryPropertyStat }) =>
            data.min != null ? `${data.min.toFixed(2)} - ${data.max?.toFixed(2)}` : "N/A",
        }),
        h(Column, { header: "Mean" }, {
          body: ({ data }: { data: DataStoryPropertyStat }) =>
            data.mean != null ? data.mean.toFixed(2) : "N/A",
        }),
      ],
    });
  },
});

const MetadataEditor = defineComponent({
  name: "MetadataEditor",
  props: {
    xTitle: { type: String, default: "" },
    xUnits: { type: String, default: "" },
    yTitle: { type: String, default: "" },
    isTimeSeries: { type: Boolean, default: false },
    targetMode: { type: String as () => "single" | "multi", default: "single" },
    selectedTarget: { type: String, default: "" },
    xTitleOptions: { type: Array as () => string[], required: true },
    xUnitsOptions: { type: Array as () => string[], required: true },
    yTitleOptions: { type: Array as () => string[], required: true },
    targetOptions: { type: Array as () => string[], default: () => [] },
    showTargetControls: { type: Boolean, default: false },
  },
  emits: [
    "update:xTitle",
    "update:xUnits",
    "update:yTitle",
    "update:isTimeSeries",
    "update:targetMode",
    "update:selectedTarget",
  ],
  setup(props, { emit }) {
    const row = (label: string, control: VNodeChild) =>
      h("div", { class: "meta-row" }, [h("span", { class: "meta-key" }, label), control]);
    return () => [
      row("X-Axis", h(Dropdown, {
        modelValue: props.xTitle,
        options: props.xTitleOptions,
        editable: true,
        placeholder: "Select or type...",
        class: "meta-dropdown",
        "onUpdate:modelValue": (value: string) => emit("update:xTitle", value),
      })),
      row("X Units", h(Dropdown, {
        modelValue: props.xUnits,
        options: props.xUnitsOptions,
        editable: true,
        placeholder: "Units",
        class: "meta-dropdown",
        "onUpdate:modelValue": (value: string) => emit("update:xUnits", value),
      })),
      row("Y-Axis", h(Dropdown, {
        modelValue: props.yTitle,
        options: props.yTitleOptions,
        editable: true,
        placeholder: "Select or type...",
        class: "meta-dropdown",
        "onUpdate:modelValue": (value: string) => emit("update:yTitle", value),
      })),
      row("Time Series", h(InputSwitch, {
        modelValue: props.isTimeSeries,
        "onUpdate:modelValue": (value: boolean) => emit("update:isTimeSeries", value),
      })),
      props.showTargetControls
        ? row("Target Mode", h(Dropdown, {
            modelValue: props.targetMode,
            options: [
              { label: "Single property", value: "single" },
              { label: "Multi-target complete-case", value: "multi" },
            ],
            optionLabel: "label",
            optionValue: "value",
            class: "meta-dropdown",
            "onUpdate:modelValue": (value: "single" | "multi") => emit("update:targetMode", value),
          }))
        : null,
      props.showTargetControls && props.targetMode === "single"
        ? row("Target Property", h(Dropdown, {
            modelValue: props.selectedTarget,
            options: props.targetOptions,
            placeholder: "Select property",
            class: "meta-dropdown",
            "onUpdate:modelValue": (value: string) => emit("update:selectedTarget", value),
          }))
        : null,
    ];
  },
});

const DataStorySection = defineComponent({
  name: "DataStorySection",
  setup() {
    return () => {
      if (!isFeatureEnabled("sherpaDataStory")) return null;
      return h("div", { class: "data-story-panel" }, [
        h("div", { class: "data-story-header" }, [
          h("h4", { class: "panel-title" }, [h("i", { class: "pi pi-book" }), " Data Story"]),
          h("div", { class: "data-story-actions" }, [
            h("span", { class: "ai-feature-note" }, "AI Feature"),
            h("span", { class: "data-story-button-wrap", title: dataStoryButtonHoverText.value }, [
              h(Button, {
                label: dataStoryButtonLabel.value,
                icon: "pi pi-sparkles",
                class: "p-button-sm p-button-outlined",
                loading: dataStore.dataStoryLoading,
                disabled: isDataStoryButtonDisabled.value,
                onClick: () => dataStore.generateDataStory(),
              }),
            ]),
          ]),
        ]),
        h("div", { class: "data-story-context" }, [
          h("label", { class: "data-story-context-label", for: "contents-data-story-context" }, "Additional Context"),
          h(Textarea, {
            id: "contents-data-story-context",
            modelValue: dataStore.dataStoryContext,
            rows: 3,
            autoResize: true,
            class: "data-story-context-input",
            placeholder: "Optional: add domain context, process background, sample type, or what you want the story to emphasize.",
            "onUpdate:modelValue": (value: string) => { dataStore.dataStoryContext = value; },
          }),
          h("p", { class: "data-story-context-hint" }, "This will be passed to the LLM as extra context for a more relevant narrative."),
        ]),
        dataStore.dataStoryLoading
          ? h("div", { class: "data-story-loading" }, [
              h(ProgressSpinner, { style: "width: 24px; height: 24px" }),
              h("span", "Generating narrative..."),
            ])
          : dataStore.dataStoryText
            ? h("div", { class: "data-story-text" }, [
                h(MemoryAttribution, { scopes: dataStore.dataStoryMemoryScopes }),
                dataStore.dataStoryText,
              ])
            : h("p", { class: "data-story-hint" }, "Click \"Generate Data Story\" to create an LLM-powered narrative describing this dataset's scientific context and characteristics."),
      ]);
    };
  },
});
</script>

<style>
.contents-panel {
  border-top: 1px solid var(--surface-border);
  padding-top: 1.25rem;
  margin-top: 1.5rem;
}

.contents-panel-header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.contents-panel-header h3 {
  margin: 0 0 0.2rem;
  font-size: 1rem;
  font-weight: 600;
}

.contents-panel-header p {
  margin: 0;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

.explore-loading,
.explore-error,
.explore-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 60px 24px;
  color: #94a3b8;
  text-align: center;
}

.explore-empty i {
  font-size: 2.5rem;
}

.explore-empty h3 {
  margin: 0;
  color: #475569;
}

.explore-empty p {
  max-width: 400px;
  line-height: 1.5;
  color: #64748b;
}

.explore-error i {
  font-size: 2rem;
  color: #f59e0b;
}

.explore-error span {
  color: #dc2626;
}

.explore-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.explore-header,
.data-story-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.explore-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 1.1rem;
  font-weight: 600;
  color: #1e293b;
}

.explore-title i {
  color: #64748b;
}

.explore-table {
  margin-bottom: 16px;
}

.table-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.explore-plot {
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
  width: 100%;
  box-sizing: border-box;
}

.explore-panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.metadata-panel {
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
}

.panel-title {
  margin: 0 0 12px;
  font-size: 0.95rem;
  font-weight: 600;
  color: #1e293b;
}

.metadata-table {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding: 6px 0;
  border-bottom: 1px solid #f1f5f9;
}

.meta-row:last-child {
  border-bottom: none;
}

.meta-key {
  font-size: 0.85rem;
  color: #64748b;
}

.meta-val {
  font-size: 0.9rem;
  color: #1e293b;
  font-weight: 500;
}

.meta-dropdown {
  width: 160px;
  font-size: 0.85rem;
}

.data-story-panel {
  margin-top: 1rem;
  padding: 0.25rem 0 0.25rem 1rem;
  background: transparent;
  border: none;
  border-left: 3px solid var(--primary-color);
  border-radius: 0;
}

.data-story-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.data-story-button-wrap {
  display: inline-flex;
}

.data-story-header .panel-title {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}

.data-story-context {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.data-story-context-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: #334155;
}

.data-story-context-input {
  width: 100%;
}

.data-story-context-hint {
  margin: 0;
  font-size: 0.8rem;
  color: #64748b;
  line-height: 1.4;
}

.ai-feature-note {
  font-size: 0.6875rem;
  font-weight: 500;
  letter-spacing: 0.02em;
  text-transform: lowercase;
  color: #8b5cf6;
  background: transparent;
  border: 1px solid color-mix(in srgb, #8b5cf6 35%, transparent);
  padding: 0.05rem 0.45rem;
  border-radius: 4px;
}

.data-story-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
  font-size: 0.9rem;
}

.data-story-text {
  font-size: 0.9rem;
  line-height: 1.6;
  color: #334155;
  white-space: pre-wrap;
}

.data-story-hint {
  color: #94a3b8;
  font-size: 0.85rem;
  font-style: italic;
  margin: 0;
}

.dataset-description {
  font-size: 0.9rem;
  color: #475569;
  line-height: 1.6;
  margin: 0;
  white-space: pre-line;
}

@media (max-width: 800px) {
  .explore-panels {
    grid-template-columns: 1fr;
  }
}
</style>
