<template>
  <component
    :is="embedded ? 'section' : Dialog"
    v-model:visible="visible"
    :header="title"
    :style="embedded ? { width: '100%', minWidth: '0' } : { width: '85vw', maxWidth: '1200px', maxHeight: 'calc(100vh - 24px)' }"
    modal
    :draggable="false"
    class="quick-plot-modal"
    :class="{ 'embedded-plot': embedded }"
  >
    <div class="plot-container">
      <!-- Plot controls bar -->
      <div class="plot-controls">
        <!-- Plot type selector -->
        <div v-if="!tableOnly" class="control-group">
          <label>{{ selectedPlotKey.startsWith('table_column:') ? 'Column' : 'Plot Type' }}</label>
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
            <label>Horizontal Component</label>
            <Dropdown
              v-model="xAxis"
              :options="axisOptions"
              optionLabel="label"
              optionValue="value"
              class="axis-dropdown"
            />
          </div>
          <div class="control-group">
            <label>Vertical Component</label>
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

        <template v-if="showLibraryCompareControls">
          <div class="control-group">
            <label>Spectrum</label>
            <Dropdown
              v-model="selectedLibrarySample"
              :options="libraryCompareSampleOptions"
              optionLabel="label"
              optionValue="value"
              class="axis-dropdown"
            />
          </div>
          <div class="control-group species-rank-control">
            <label>Species rank</label>
            <div class="species-rank-list" role="listbox" aria-label="Library species to overlay">
              <button
                v-for="candidate in filteredLibraryCompareCandidates"
                :key="libraryCandidateKey(candidate)"
                type="button"
                class="species-rank-row"
                :class="{ selected: isLibraryCandidateChecked(candidate) }"
                @click="toggleLibraryCandidate(candidate)"
              >
                <input
                  type="checkbox"
                  :checked="isLibraryCandidateChecked(candidate)"
                  tabindex="-1"
                  aria-hidden="true"
                  readonly
                />
                <span
                  class="species-color-swatch"
                  :style="{ background: libraryTraceColorForCandidate(candidate) }"
                  aria-hidden="true"
                />
                <span>
                  #{{ candidate.sample_rank ?? candidate.rank ?? "?" }} {{ candidate.library ?? "Library" }}
                </span>
                <strong>HQI {{ formatHqi(candidate.hqi) }}</strong>
              </button>
            </div>
          </div>
          <span
            v-if="selectedLibraryAlignmentStatus"
            class="candidate-alignment-badge"
            :class="{ aligned: selectedLibraryAlignmentStatus.aligned }"
          >
            <i :class="selectedLibraryAlignmentStatus.aligned ? 'pi pi-check-circle' : 'pi pi-exclamation-triangle'" />
            {{ selectedLibraryAlignmentStatus.label }}
          </span>
        </template>

        <!-- Data shape summary -->
        <div class="control-group stats-summary">
          <span class="stat-item">
            <strong>{{ dataShape.rows }}</strong> {{ dataShape.rowLabel }}
          </span>
          <span v-if="dataShape.cols > 0" class="stat-item">
            <strong>{{ dataShape.cols }}</strong> {{ dataShape.colLabel }}
          </span>
          <!-- A table can mix positions and magnitudes: its overall range has no common unit. -->
          <span v-if="dataShape.range && !selectedPlotKey.startsWith('table_column:')" class="stat-item">
            Range: <strong>{{ scientificNumber(dataShape.range[0]) }}</strong> - <strong>{{ scientificNumber(dataShape.range[1]) }}</strong>
          </span>
        </div>

        <!-- View toggle: Plot vs Data Table -->
        <div class="control-group view-toggle">
          <Button
            v-if="!tableOnly"
            :icon="viewMode === 'plot' ? 'pi pi-table' : 'pi pi-chart-line'"
            :label="
              viewMode === 'plot'
                ? plotSampling?.plottedTableOnly
                  ? 'View Plotted Data'
                  : 'View Data'
                : 'View Plot'
            "
            class="p-button-outlined p-button-sm"
            @click="toggleViewMode"
            :title="
              viewMode === 'plot'
                ? plotSampling?.plottedTableOnly
                  ? 'Inspect plotted traces only'
                  : 'Switch to Data Table'
                : 'Switch to Plot'
            "
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

      <div v-if="plotSampling" class="plot-sampling-disclosure" role="status">
        <strong>Sampled plot:</strong> {{ plotSampling.shown }} of {{ plotSampling.total }}
        {{ plotSampling.sourceNoun }} ({{ plotSampling.percent }}%) are shown;
        {{ plotSampling.omitted }} are unplotted.
        {{ plotSampling.selectionDescription }}
        <template v-if="plotSampling.plottedTableOnly"
          >This result's Data view contains only these traces. Open the upstream source dataset or a
          complete-matrix export to inspect all samples.</template
        >
        <template v-else
          >The Data view retains the complete available result; its table paging is
          separate.</template
        >
      </div>

      <div v-if="metadataGroupingError || explicitGroupingError" class="plot-grouping-notice" role="status">
        <i class="pi pi-info-circle" aria-hidden="true" />
        <span>{{ metadataGroupingError || explicitGroupingError }}</span> Showing the score rows without metadata coloring.
      </div>

      <div v-if="comparisonNotices" class="plot-grouping-notice" role="status">
        <span>Original (immediate node input): {{ comparisonNotices[0] }}<br />Preprocessed: {{ comparisonNotices[1] }}<br />{{ plotLayout.meta.comparison_scale_notice }}</span>
      </div>

      <!-- Plotly chart -->
      <p v-if="downloadError" role="alert">{{ downloadError }}</p>
      <div v-if="viewMode === 'plot'" ref="plotContainerEl" class="plotly-container">
        <PlotlyChart
          ref="plotChart"
          v-if="displayPlotData.length > 0"
          :data="displayPlotData"
          :layout="displayPlotLayout"
          :config="PLOT_CONFIG"
          :style="plotCanvasStyle"
        />
        <div v-else class="empty-plot">
          <i class="pi pi-chart-line" />
          <p :role="plotRefusal ? 'alert' : undefined">{{ plotRefusal || "No data to display" }}</p>
          <small v-if="!plotRefusal">{{
            embedded
              ? "No retained table is available for this output."
              : "Execute the node first to see results"
          }}</small>
        </div>
      </div>

      <!-- Data Table -->
      <div v-else class="data-table-container">
        <span v-if="dataPreviewSummary" class="data-summary">{{ dataPreviewSummary }}</span>
        <div v-if="embedded && totalFeatureColumns > 10" class="feature-paging">
          <Button icon="pi pi-angle-left" aria-label="Previous feature columns" :disabled="featureOffset === 0" @click="featureOffset = Math.max(0, featureOffset - 10)" />
          <span>Columns {{ featureOffset + 1 }}–{{ Math.min(featureOffset + 10, totalFeatureColumns) }} of {{ totalFeatureColumns }}</span>
          <Button icon="pi pi-angle-right" aria-label="Next feature columns" :disabled="featureOffset + 10 >= totalFeatureColumns" @click="featureOffset += 10" />
        </div>
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
        <Paginator v-if="embedded && previewTotalRows > previewRowLimit" :first="previewFirst" :rows="previewRowLimit" :total-records="previewTotalRows" @page="previewFirst = $event.first" />
        <div v-if="dataPreview.length === 0" class="empty-plot">
          <i class="pi pi-table" />
          <p :role="plotRefusal ? 'alert' : undefined">{{ plotRefusal || "No data to display" }}</p>
          <small v-if="!plotRefusal">{{
            embedded
              ? "No retained table is available for this output."
              : "Execute the node first to see results"
          }}</small>
        </div>
      </div>
    </div>
  </component>
</template>

<script setup lang="ts">
import { scientificNumber } from "@/utils/scientificEncoding";
import { scientificPlotRefusal } from "@/utils/scientificPlotState";
/* eslint-disable @typescript-eslint/no-explicit-any -- quick-plot consumes generic backend visualization payloads. */
import { ref, computed, watch } from "vue";
import Dialog from "primevue/dialog";
import Dropdown from "primevue/dropdown";
import Button from "primevue/button";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Paginator from "primevue/paginator";
import PlotlyChart from "@/components/PlotlyChart.vue";
import {
  useQuickPlotProjection,
  PLOT_CONFIG,
  type QuickPlotSelection,
} from "@/composables/useScientificPlotProjection";
import { t2QDiagnosticRows } from "@/utils/scientificPlots";
import { isProjectedScientificKind } from "@/utils/scientificPresentation";
import {
  normalizeSampleLabel,
  compactSampleLabel,
  detectLabelDelimiter,
  splitLabelByDelimiter,
} from "@/utils/sampleLabels";
import { metadataGroupingState } from "@/utils/sampleMetadataGrouping";
import { scaleLibraryTraceToSamplePeaks } from "@/utils/libraryTraceScaling";

interface Props {
  embedded?: boolean;
  tableOnly?: boolean;
  modelValue: boolean;
  nodeOutput: any;
  nodeType: string;
  nodeLabel: string;
  nodeInput?: any;
  nodeInputs?: Record<string, any>;
  plotSelection?: QuickPlotSelection;
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

const explicitGroupingError = computed(() => {
  if (!props.nodeType.startsWith("model.")) return "";
  const scores = props.nodeOutput?.data;
  if (!Array.isArray(scores) || scores.length === 0) return "";
  const value = props.nodeOutput?.presentation_value ?? props.nodeOutput?.ports?.scores?.value;
  const grouping = metadataGroupingState(value?.y_axis, scores.length);
  return grouping.kind === "invalid" ? grouping.message : "";
});

const plotRefusal = computed(() => scientificPlotRefusal(plotLayout.value));
const comparisonNotices = computed(() => plotLayout.value?.meta?.comparison_notices);

const plotSampling = computed(() => {
  const population = (plotLayout.value as any)?.meta?.display_population;
  if (
    population?.method === "first_rows" &&
    (population.total > population.shown || population.excluded > 0)
  ) {
    return {
      shown: population.shown,
      total: population.total,
      omitted: population.total - population.shown,
      percent: ((100 * population.shown) / population.total).toFixed(1),
      sourceNoun: comparisonNotices.value ? "active preprocessed result rows" : "active result rows",
      selectionDescription: `Traces are the first active rows in retained order. ${population.excluded ?? 0} of ${population.available ?? population.total} retained rows are excluded by the sample mask.`,
      plottedTableOnly: false,
    };
  }
  if (props.nodeType !== "output.plot") return null;
  const visualization = props.nodeOutput?.ports?.visualization?.value;
  const metadata = visualization?.metadata ?? props.nodeOutput?.metadata;
  if (metadata?.subsampled !== true) return null;
  const shown = Number(metadata.shown_traces);
  const total = Number(metadata.n_samples);
  if (!Number.isInteger(shown) || !Number.isInteger(total) || shown < 1 || total <= shown) return null;
  return {
    plottedTableOnly: true,
    selectionDescription: "Traces were selected at evenly spaced source rows.",
    shown,
    total,
    omitted: total - shown,
    percent: (100 * shown / total).toFixed(1),
    sourceNoun: visualization?.plot_type === "spectra" ? "source spectra" : "source samples",
  };
});

// Use the shared plot composable (same functions as Detailed View)
const nodeOutputRef = computed(() => props.nodeOutput);
const nodeTypeRef = computed(() => props.nodeType);
const nodeInputRef = computed(() => props.nodeInput);
const nodeInputsRef = computed(() => props.nodeInputs || {});

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
  metadataGroupingError,
} = useQuickPlotProjection(nodeOutputRef, nodeTypeRef, nodeInputRef, nodeInputsRef, props.plotSelection);

type LibraryCompareCandidate = {
  rank?: number;
  sample_rank?: number;
  sample_index?: number;
  library_index?: number;
  sample_trace_index?: number;
  library_trace_index?: number;
  sample?: string;
  library?: string;
  hqi?: number;
  hqi_band?: string;
  candidate_status?: string;
  confidence_caveats?: string;
  sample_spacing?: number | null;
  library_spacing?: number | null;
  alignment_spacing?: number | null;
  grid_aligned?: boolean;
  interpolation?: string;
  x?: Array<number | null>;
  sample_x?: Array<number | null>;
  sample_y?: Array<number | null>;
  library_x?: Array<number | null>;
  library_y?: Array<number | null>;
  comparison_x?: Array<number | null>;
  comparison_sample_y?: Array<number | null>;
  comparison_library_y?: Array<number | null>;
  y_units?: string;
};

type LibraryCompareTrace = {
  sample_index?: number;
  library_index?: number;
  sample?: string;
  library?: string;
  x?: Array<number | null>;
  y?: Array<number | null>;
};

const selectedLibrarySample = ref<string | null>(null);
const selectedLibraryCandidateKeys = ref<string[]>([]);

const libraryCompareTracePayload = computed(() => props.nodeOutput?.plots?.library_compare_candidates || {});

const libraryCompareCandidates = computed<LibraryCompareCandidate[]>(() => {
  const raw = libraryCompareTracePayload.value?.data;
  return Array.isArray(raw) ? raw : [];
});

const libraryCompareSampleTraceMap = computed(() => {
  const traces = libraryCompareTracePayload.value?.samples;
  const map = new Map<number, LibraryCompareTrace>();
  if (!Array.isArray(traces)) return map;
  for (const trace of traces) {
    const index = Number(trace?.sample_index);
    if (Number.isFinite(index)) map.set(index, trace as LibraryCompareTrace);
  }
  return map;
});

const libraryCompareLibraryTraceMap = computed(() => {
  const traces = libraryCompareTracePayload.value?.libraries;
  const map = new Map<number, LibraryCompareTrace>();
  if (!Array.isArray(traces)) return map;
  for (const trace of traces) {
    const index = Number(trace?.library_index);
    if (Number.isFinite(index)) map.set(index, trace as LibraryCompareTrace);
  }
  return map;
});

const libraryCompareSampleOptions = computed(() => {
  const seen = new Set<string>();
  const options: Array<{ label: string; value: string }> = [];
  for (const candidate of libraryCompareCandidates.value) {
    const label = String(candidate.sample ?? `Sample ${Number(candidate.sample_index ?? options.length) + 1}`);
    if (seen.has(label)) continue;
    seen.add(label);
    options.push({ label, value: label });
  }
  return options;
});

const filteredLibraryCompareCandidates = computed(() => {
  if (!selectedLibrarySample.value) return libraryCompareCandidates.value;
  return libraryCompareCandidates.value.filter((candidate) => String(candidate.sample ?? "") === selectedLibrarySample.value);
});

const selectedLibraryCandidateRecords = computed<LibraryCompareCandidate[]>(() =>
  filteredLibraryCompareCandidates.value.filter((candidate) =>
    selectedLibraryCandidateKeys.value.includes(libraryCandidateKey(candidate))
  )
);

const showLibraryCompareControls = computed(() =>
  props.nodeType === "analysis.compare_library"
    && selectedPlotKey.value === "library_compare"
    && libraryCompareCandidates.value.length > 0
);

const selectedLibraryAlignmentStatus = computed(() => {
  const candidate =
    selectedLibraryCandidateRecords.value[0] ?? filteredLibraryCompareCandidates.value[0];
  if (!candidate) return null;
  const aligned = candidate.grid_aligned !== false;
  const spacing = formatSpacing(candidate.alignment_spacing);
  const sampleSpacing = formatSpacing(candidate.sample_spacing);
  const librarySpacing = formatSpacing(candidate.library_spacing);
  const spacingLabel = spacing
    ? `Δ ${spacing} cm-1`
    : sampleSpacing && librarySpacing
      ? `sample/library Δ ${sampleSpacing}/${librarySpacing} cm-1`
      : "";
  return {
    aligned,
    label: `${aligned ? "Grid aligned" : "Grid alignment warning"}${spacingLabel ? ` · ${spacingLabel}` : ""}`,
  };
});

watch(
  libraryCompareSampleOptions,
  (options) => {
    if (options.length === 0) {
      selectedLibrarySample.value = null;
      selectedLibraryCandidateKeys.value = [];
      return;
    }
    if (!options.some((option) => option.value === selectedLibrarySample.value)) {
      selectedLibrarySample.value = options[0].value;
    }
  },
  { immediate: true },
);

watch(
  () => selectedLibrarySample.value,
  () => {
    selectedLibraryCandidateKeys.value = [];
  },
);

watch(
  () => filteredLibraryCompareCandidates.value.map(libraryCandidateKey).join("|"),
  () => {
    if (filteredLibraryCompareCandidates.value.length === 0) {
      selectedLibraryCandidateKeys.value = [];
      return;
    }
    const validKeys = new Set(filteredLibraryCompareCandidates.value.map(libraryCandidateKey));
    const nextKeys = selectedLibraryCandidateKeys.value.filter((key) => validKeys.has(key));
    if (nextKeys.length === 0) {
      nextKeys.push(libraryCandidateKey(filteredLibraryCompareCandidates.value[0]));
    }
    selectedLibraryCandidateKeys.value = nextKeys;
  },
  { immediate: true },
);

const libraryCompareQuickPlotData = computed(() => {
  const candidates = selectedLibraryCandidateRecords.value;
  const firstCandidate = candidates[0] ?? filteredLibraryCompareCandidates.value[0];
  if (!firstCandidate) return [];
  const firstSampleTraceIndex = Number(firstCandidate?.sample_trace_index ?? firstCandidate?.sample_index);
  const firstSampleTrace = Number.isFinite(firstSampleTraceIndex)
    ? libraryCompareSampleTraceMap.value.get(firstSampleTraceIndex)
    : undefined;
  const sampleX = firstCandidate?.sample_x ?? firstCandidate?.x ?? firstSampleTrace?.x;
  const sampleY = firstCandidate?.sample_y ?? firstSampleTrace?.y;
  if (!sampleX || !sampleY) return [];
  const traces: any[] = [
    {
      type: "scatter",
      mode: "lines",
      x: sampleX,
      y: sampleY,
      name: firstCandidate.sample || "Sample",
      line: { color: "#f8fafc", width: 2 },
    },
  ];
  for (const candidate of candidates) {
    const libraryTraceIndex = Number(candidate?.library_trace_index ?? candidate?.library_index);
    const libraryTrace = Number.isFinite(libraryTraceIndex)
      ? libraryCompareLibraryTraceMap.value.get(libraryTraceIndex)
      : undefined;
    const libraryX = candidate?.library_x ?? candidate?.x ?? libraryTrace?.x;
    const libraryY = candidate?.library_y ?? libraryTrace?.y;
    if (!libraryX || !libraryY) continue;
    traces.push({
      type: "scatter",
      mode: "lines",
      x: libraryX,
      y: scaleLibraryTraceToSamplePeaks(libraryX, libraryY, sampleX, sampleY),
      name: `${candidate.library || "Library"} (HQI ${formatHqi(candidate.hqi)})`,
      line: { color: libraryTraceColorForCandidate(candidate), width: 2 },
    });
  }
  return traces;
});

const libraryCompareQuickPlotLayout = computed(() => {
  const candidate =
    selectedLibraryCandidateRecords.value[0] ?? filteredLibraryCompareCandidates.value[0];
  const backendLayout = props.nodeOutput?.plots?.library_compare_candidates?.layout || {};
  return {
    ...plotLayout.value,
    ...backendLayout,
    title: candidate
      ? `${candidate.sample || "Sample"} vs selected library signatures`
      : backendLayout.title || "Normalized Sample vs. Library Candidate",
    yaxis: {
      ...(plotLayout.value?.yaxis || {}),
      ...(backendLayout.yaxis || {}),
      title: candidate?.y_units || "Max-normalized response",
    },
  };
});

const displayPlotData = computed(() => {
  if (
    props.nodeType === "analysis.compare_library" &&
    libraryCompareQuickPlotData.value.length > 0
  ) {
    return libraryCompareQuickPlotData.value;
  }
  return plotData.value;
});

const displayPlotLayout = computed(() => {
  if (
    props.nodeType === "analysis.compare_library" &&
    libraryCompareQuickPlotData.value.length > 0
  ) {
    return libraryCompareQuickPlotLayout.value;
  }
  return plotLayout.value;
});

const plotCanvasStyle = computed(() => {
  const requestedHeight = Number(displayPlotLayout.value?.height);
  if (Number.isFinite(requestedHeight) && requestedHeight > 640) {
    return {
      height: `${requestedHeight}px`,
      minHeight: `${requestedHeight}px`,
    };
  }
  return {
    height: "100%",
    minHeight: "320px",
  };
});

// View mode toggle
const viewMode = ref<"plot" | "data">(props.tableOnly ? "data" : "plot");
watch(() => props.tableOnly, (tableOnly) => { viewMode.value = tableOnly ? "data" : "plot"; });
const previewRowLimit = 100;
const previewFirst = ref(0);
const featureOffset = ref(0);
const usePlottedTable = computed(() => !props.tableOnly && (selectedPlotKey.value !== availablePlots.value[0]?.key
  || isProjectedScientificKind(props.nodeOutput, "variable_profile")));
const totalFeatureColumns = computed(() => !usePlottedTable.value && Array.isArray(props.nodeOutput?.data?.[0]) ? props.nodeOutput.data[0].length : 0);
const previewTotalRows = computed(() => {
  if (usePlottedTable.value) return plottedPointPreview.value.total;
  if (isProjectedScientificKind(props.nodeOutput, "t2_q_diagnostics")) return t2QDiagnosticRows(props.nodeOutput?.presentation_value, props.nodeOutput?.metadata || {}).length;
  const data = props.nodeOutput?.data;
  if (!Array.isArray(data) || !data.length) return plottedPointPreview.value.total;
  return props.nodeType === "analysis.compare_library" && selectedLibrarySample.value
    ? data.filter((row: any) => String(row?.sample ?? "") === selectedLibrarySample.value).length : data.length;
});
watch(() => [props.nodeOutput, selectedPlotKey.value, selectedLibrarySample.value], () => { previewFirst.value = 0; featureOffset.value = 0; });

watch(
  () => props.modelValue,
  (isVisible) => {
    if (isVisible) viewMode.value = props.tableOnly ? "data" : "plot";
  },
);

function toggleViewMode() {
  viewMode.value = viewMode.value === "plot" ? "data" : "plot";
}

function formatHqi(value?: number): string {
  if (!Number.isFinite(Number(value))) return "n/a";
  return scientificNumber(Number(value));
}

function formatSpacing(value?: number | null): string {
  if (!Number.isFinite(Number(value))) return "";
  return scientificNumber(Number(value));
}

function libraryCandidateKey(candidate: LibraryCompareCandidate): string {
  return `${Number(candidate.sample_index ?? -1)}:${Number(candidate.library_index ?? -1)}`;
}

function isLibraryCandidateChecked(candidate: LibraryCompareCandidate): boolean {
  return selectedLibraryCandidateKeys.value.includes(libraryCandidateKey(candidate));
}

function toggleLibraryCandidate(candidate: LibraryCompareCandidate): void {
  const key = libraryCandidateKey(candidate);
  selectedLibraryCandidateKeys.value = isLibraryCandidateChecked(candidate)
    ? selectedLibraryCandidateKeys.value.filter((item) => item !== key)
    : [...selectedLibraryCandidateKeys.value, key];
}

function libraryTraceColorForCandidate(candidate: LibraryCompareCandidate): string {
  const palette = [
    "#38bdf8", "#f59e0b", "#22c55e", "#e879f9", "#fb7185", "#a78bfa",
    "#14b8a6", "#f97316", "#84cc16", "#60a5fa", "#f472b6", "#c084fc",
  ];
  const index = Number(candidate.library_trace_index ?? candidate.library_index ?? candidate.sample_rank ?? 0);
  return palette[Math.abs(Math.trunc(Number.isFinite(index) ? index : 0)) % palette.length];
}

// Data preview for table view
const plottedPointPreview = computed(() => {
  const rows: Record<string, unknown>[] = [];
  let total = 0;
  for (const trace of plotData.value ?? []) {
    if (!Array.isArray(trace.x) || !Array.isArray(trace.y)) continue;
    if (Array.isArray(trace.z)) {
      for (let y = 0; y < trace.y.length; y += 1) {
        for (let x = 0; x < trace.x.length; x += 1) {
          if (total >= previewFirst.value && rows.length < previewRowLimit) rows.push({ _index: total + 1, series: trace.name ?? "", x: trace.x[x], y: trace.y[y], value: trace.z[y]?.[x] });
          total += 1;
        }
      }
      continue;
    }
    const count = Math.min(trace.x.length, trace.y.length);
    const start = Math.max(0, previewFirst.value - total);
    for (let index = start; index < count && rows.length < previewRowLimit; index += 1) {
      rows.push({ _index: total + index + 1, series: trace.name ?? "", x: trace.x[index], y: trace.y[index] });
    }
    total += count;
  }
  return { rows, total };
});

const dataPreview = computed(() => {
  if (usePlottedTable.value) return plottedPointPreview.value.rows;
  const data = props.nodeOutput?.data;
  const metadata = props.nodeOutput?.metadata || {};
  if (isProjectedScientificKind(props.nodeOutput, "t2_q_diagnostics")) {
    return t2QDiagnosticRows(props.nodeOutput?.presentation_value, metadata)
      .slice(previewFirst.value, previewFirst.value + previewRowLimit)
      .map((row, index) => ({
        _index: previewFirst.value + index + 1,
        sample: row.sample,
        t2: row.t2,
        q: row.q,
        outlier: row.outlier ? "Yes" : "No",
      }));
  }
  if (!Array.isArray(data) || data.length === 0) return plottedPointPreview.value.rows;

  if (data.length > 0 && typeof data[0] === "object" && !Array.isArray(data[0])) {
    const rows = props.nodeType === "analysis.compare_library" && selectedLibrarySample.value
      ? data.filter((row: any) => String(row?.sample ?? "") === selectedLibrarySample.value)
      : data;
    return rows.slice(previewFirst.value, previewFirst.value + previewRowLimit).map((row: any, i: number) => ({
      _index: previewFirst.value + i + 1,
      ...row,
    }));
  }

  const isPlsVariance = isProjectedScientificKind(props.nodeOutput, "pls_explained_variance");
  const labelsRaw = isPlsVariance
    ? data.map((_: unknown, index: number) => `LV ${index + 1}`)
    : metadata.sample_labels || metadata.labels || [];
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

  return data.slice(previewFirst.value, previewFirst.value + previewRowLimit).map((row: any, rowIndex: number) => {
    const i = previewFirst.value + rowIndex;
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
      row.slice(featureOffset.value, featureOffset.value + 10).forEach((val: any, j: number) => {
        obj[`col_${featureOffset.value + j}`] = typeof val === "number" ? scientificNumber(val) : val;
      });
    } else {
      obj.value = typeof row === "number" ? scientificNumber(row) : row;
    }
    return obj;
  });
});

const dataPreviewSummary = computed(() => {
  if (plotSampling.value?.plottedTableOnly && viewMode.value === "data") {
    return `${plotSampling.value.shown} plotted traces of ${plotSampling.value.total} ${plotSampling.value.sourceNoun}; full source matrix is not in this view`;
  }
  if (usePlottedTable.value) return `${previewFirst.value + 1}–${Math.min(previewFirst.value + previewRowLimit, previewTotalRows.value)} of ${previewTotalRows.value} plotted points`;
  if (props.embedded) return `${previewFirst.value + 1}–${Math.min(previewFirst.value + previewRowLimit, previewTotalRows.value)} of ${previewTotalRows.value} rows`;
  if (isProjectedScientificKind(props.nodeOutput, "t2_q_diagnostics")) {
    const totalRows = t2QDiagnosticRows(
      props.nodeOutput?.presentation_value,
      props.nodeOutput?.metadata || {},
    ).length;
    return `${Math.min(totalRows, previewRowLimit)} of ${totalRows} samples`;
  }
  const data = props.nodeOutput?.data;
  if (!Array.isArray(data) || data.length === 0) {
    return `${plottedPointPreview.value.rows.length} of ${plottedPointPreview.value.total} plotted points`;
  }
  const rows = props.nodeType === "analysis.compare_library" && selectedLibrarySample.value
    ? data.filter((row: any) => String(row?.sample ?? "") === selectedLibrarySample.value)
    : data;
  const totalRows = rows.length;
  const firstRow = rows[0] ?? data[0];
  const totalCols = Array.isArray(firstRow)
    ? firstRow.length
    : firstRow && typeof firstRow === "object"
      ? Object.keys(firstRow).length + 1
      : 1;
  const shownRows = Math.min(totalRows, previewRowLimit);
  const shownCols = Math.min(totalCols, 10);
  let summary = `${shownRows} of ${totalRows} rows`;
  if (totalCols > 10) summary += `, ${shownCols} of ${totalCols} columns`;
  return summary;
});

const dataPreviewColumns = computed(() => {
  if (!dataPreview.value.length) return [];
  if (usePlottedTable.value) {
    const title = (axis: any, fallback: string) => typeof axis?.title === "string" ? axis.title : axis?.title?.text || fallback;
    const labels: Record<string, string> = { _index: "#", series: "Series", x: title(plotLayout.value?.xaxis, "X"), y: title(plotLayout.value?.yaxis, "Y"), value: "Value" };
    return Object.keys(dataPreview.value[0]).map(field => ({ field, header: labels[field] || field }));
  }
  if (isProjectedScientificKind(props.nodeOutput, "t2_q_diagnostics")) {
    return [
      { field: "_index", header: "#" },
      { field: "sample", header: "Sample" },
      { field: "t2", header: "Hotelling T²" },
      { field: "q", header: "Q residual (SPE)" },
      { field: "outlier", header: "Screened outlier" },
    ];
  }
  const first = dataPreview.value[0] as Record<string, any>;
  const metadata = props.nodeOutput?.metadata || {};
  const pcLabels = metadata.pc_labels || [];
  const presentationValue = props.nodeOutput?.presentation_value;
  const presentationDataset =
    presentationValue && typeof presentationValue === "object" && !Array.isArray(presentationValue)
      ? presentationValue as Record<string, any>
      : {};
  const featureAxis = presentationDataset.x_axis || presentationDataset.feature_axis || {};
  const featureNames = [featureAxis.labels, featureAxis.data, featureAxis.values, metadata.feature_names]
    .find((candidate) => Array.isArray(candidate) && candidate.length > 0) || [];
  const xTitle = metadata.x_title || "";
  const isPCA = metadata.type === "PCA" || metadata.isPCA;
  const isMCR = metadata.type === "MCR_ALS";
  const isPlsVariance = isProjectedScientificKind(props.nodeOutput, "pls_explained_variance");
  const isLoadingMatrix = ["pca_loadings", "pls_loadings", "plsda_loadings"]
    .some((kind) => isProjectedScientificKind(props.nodeOutput, kind));
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
        header = isPlsVariance ? "Latent Variable" : "Label";
      } else if (key.startsWith("_label_")) {
        const labelIdx = Number.parseInt(key.replace("_label_", ""), 10);
        header = Number.isNaN(labelIdx) ? "Label" : `Field ${labelIdx + 1}`;
      } else if (key.startsWith("col_")) {
        const colIdx = parseInt(key.replace("col_", ""));
        if (isPlsVariance) {
          header = colIdx === 0 ? "X variance" : colIdx === 1 ? "Y variance" : `Domain ${colIdx + 1}`;
        } else if (isLoadingMatrix && featureNames[colIdx]) {
          header = normalizeSampleLabel(featureNames[colIdx]);
        } else if (isPCA && pcLabels[colIdx]) {
          header = pcLabels[colIdx];
        } else if (isMCR && mcrLabels[colIdx]) {
          header = mcrLabels[colIdx];
        } else if (featureNames.length > colIdx) {
          header = normalizeSampleLabel(featureNames[colIdx]);
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

const plotChart = ref<InstanceType<typeof PlotlyChart> | null>(null);
const downloadError = ref("");
async function downloadPlot() {
  downloadError.value = "";
  try {
    if (!plotChart.value) throw new Error("Open an available plot before downloading.");
    await plotChart.value.downloadImage({
      format: "png",
      width: 1200,
      height: Math.max(800, Number(displayPlotLayout.value?.height) || 800),
      filename: `${props.nodeLabel.replace(/\s+/g, "_")}_output`,
    });
  } catch (error) {
    downloadError.value =
      error instanceof Error ? error.message : "Plot download failed. Try again.";
  }
}
</script>

<style scoped>
.feature-paging { display: flex; align-items: center; gap: .5rem; margin: .5rem 0; }
.embedded-plot .plot-controls, .embedded-plot .data-table-container { background: var(--surface-card); color: var(--text-color); }
.embedded-plot .control-group label, .embedded-plot .stat-item, .embedded-plot .stat-item strong { color: var(--text-color); }
.embedded-plot :deep(.p-dropdown) { background: var(--surface-card); border-color: var(--surface-border); color: var(--text-color); }
.embedded-plot :deep(.p-dropdown-label) { color: var(--text-color); }
.quick-plot-modal :deep(.p-dialog-content) {
  padding: 0;
  background: #0f172a;
  overflow: hidden;
}

.plot-container {
  display: flex;
  flex-direction: column;
  height: min(70vh, calc(100vh - 96px));
  min-height: min(500px, calc(100vh - 96px));
}

.plot-controls {
  display: flex;
  align-items: center;
  gap: 10px 14px;
  padding: 10px 12px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
  flex-wrap: wrap;
}

.plot-sampling-disclosure {
  padding: 10px 14px;
  border-bottom: 1px solid #a16207;
  background: #422d13;
  color: #fef3c7;
  font-size: 0.85rem;
  line-height: 1.45;
}

.plot-grouping-notice {
  display: flex;
  gap: 0.45rem;
  align-items: flex-start;
  padding: 0.55rem 0.8rem;
  border-bottom: 1px solid #475569;
  background: #1e293b;
  color: #cbd5e1;
  font-size: 0.82rem;
  line-height: 1.4;
}

.control-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.control-group label {
  font-size: 0.85rem;
  color: #94a3b8;
  white-space: nowrap;
}

.plot-type-dropdown {
  min-width: 180px;
}

.quick-plot-modal:not(.embedded-plot) .plot-controls :deep(.p-dropdown-label),
.quick-plot-modal:not(.embedded-plot) .plot-controls :deep(.p-dropdown-trigger) {
  color: #f1f5f9;
}

.axis-dropdown {
  min-width: 120px;
}

.species-rank-control {
  align-items: flex-start;
  flex-direction: column;
  gap: 4px;
}

.species-rank-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 4px;
  max-height: 96px;
  min-width: min(680px, 70vw);
  overflow: auto;
}

.species-rank-row {
  display: grid;
  grid-template-columns: 16px 10px minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
  border: 1px solid #334155;
  border-radius: 6px;
  background: #0f172a;
  color: #cbd5e1;
  cursor: pointer;
  font-size: 0.76rem;
  line-height: 1.15;
  padding: 4px 6px;
  text-align: left;
}

.species-rank-row:hover,
.species-rank-row.selected {
  border-color: #38bdf8;
  background: rgba(14, 165, 233, 0.14);
}

.species-rank-row input {
  pointer-events: none;
}

.species-color-swatch {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(248, 250, 252, 0.28);
}

.species-rank-row span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.species-rank-row strong {
  color: #e2e8f0;
  font-weight: 600;
  white-space: nowrap;
}

.candidate-alignment-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  color: #fde68a;
  border: 1px solid #a16207;
  border-radius: 6px;
  background: rgba(113, 63, 18, 0.22);
  padding: 0 10px;
  font-size: 0.8rem;
  font-weight: 600;
}

.candidate-alignment-badge.aligned {
  color: #bbf7d0;
  border-color: #15803d;
  background: rgba(22, 101, 52, 0.24);
}

.stats-summary {
  margin-left: auto;
  gap: 10px;
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
  min-height: 0;
  padding: 16px;
  overflow: auto;
  box-sizing: border-box;
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
  font-size: 0.76rem;
}

:deep(.preview-datatable .p-datatable-thead > tr > th) {
  background: #1e293b;
  color: #f8fafc;
  border-color: #334155;
  font-weight: 600;
  padding: 3px 8px;
  line-height: 1.15;
}

:deep(.preview-datatable .p-datatable-tbody > tr) {
  background: #0f172a;
  color: #e2e8f0;
}

:deep(.preview-datatable .p-datatable-tbody > tr > td) {
  border-color: #334155;
  padding: 2px 8px;
  line-height: 1.15;
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
