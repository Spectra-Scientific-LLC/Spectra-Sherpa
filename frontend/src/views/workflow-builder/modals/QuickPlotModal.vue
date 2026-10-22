<template>
  <component
    :is="embedded ? 'section' : Dialog"
    v-model:visible="visible"
    :header="title"
    :style="embedded ? { width: '100%', minWidth: '0' } : { width: '85vw', maxWidth: '1200px', maxHeight: 'calc(100vh - 24px)' }"
    :contentStyle="embedded ? undefined : { overflow: 'auto', maxHeight: 'calc(100vh - 110px)' }"
    modal
    :draggable="false"
    class="quick-plot-modal"
    :class="{ 'embedded-plot': embedded }"
  >
    <p v-if="evidenceError" role="alert" class="plot-evidence-error">{{ evidenceError }}</p>
    <div class="plot-container">
      <p v-if="axisSetError" role="alert">{{ axisSetError }}</p>
      <AxisSetControls
v-model:scale-value="selectedFeatureScale"
        v-model:label-value="selectedFeatureLabels" v-model:title-value="selectedFeatureTitle"
        :scale-options="featureScaleOptions" :label-options="featureLabelSetOptions" :title-options="featureTitleSetOptions" />
      <AxisSetControls
:scale-value="'__primary__'" v-model:label-value="selectedSampleLabels"
        :title-value="'__primary__'" :scale-options="[]" :label-options="sampleLabelSetOptions" :title-options="[]" />
      <!-- Plot controls bar -->
      <div class="plot-controls">
        <!-- Plot type selector -->
        <div v-if="!tableOnly && availablePlots.length > 0" class="control-group">
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
        <template v-if="showAxisControls && !oneComponentCorrelations">
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

        <SampleMetadataStyleControls
          v-if="showSampleStyleControls"
          v-model:color-value="sampleColorField" v-model:style-value="sampleSymbolField"
          :color-options="sampleColorFieldOptions" :style-options="sampleSymbolFieldOptions" />

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
            <strong>{{ displayDataShape.rows }}</strong> {{ displayDataShape.rowLabel }}
          </span>
          <span v-if="displayDataShape.cols > 0" class="stat-item">
            <strong>{{ displayDataShape.cols }}</strong> {{ displayDataShape.colLabel }}
          </span>
          <!-- A table can mix positions and magnitudes: its overall range has no common unit. -->
          <span v-if="displayDataShape.range && !selectedPlotKey.startsWith('table_column:')" class="stat-item">
            Range: <strong>{{ scientificNumber(displayDataShape.range[0], { significantDigits: 5 }) }}</strong> - <strong>{{ scientificNumber(displayDataShape.range[1], { significantDigits: 5 }) }}</strong>
          </span>
        </div>

        <!-- View toggle: Plot vs Data Table -->
        <div class="control-group view-toggle">
          <Button
            v-if="!tableOnly && availablePlots.length > 0"
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
        {{ plotSampling.sourceNoun }} ({{ plotSampling.percent }}%).
        <span v-if="plotSampling.excluded">Excluded: {{ plotSampling.excluded }} source rows.</span>
        <span v-if="plotSampling.plottedTableOnly">Data view: plotted traces only.</span>
        <MethodHelp topic="displayExports" label="Preview sampling" />
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
          @click="selectMatrixSlice"
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
        <span v-if="usePlottedTable && isProjectedScientificKind(nodeOutput, 'visualization')" class="data-summary">Plot coordinates <MethodHelp topic="displayExports" label="Plot coordinates and sample rows" /></span>
        <span v-if="!tableOnly && availablePlots.length === 0" class="data-summary" title="No shared quantitative axis">Table-only result</span>
        <span v-if="dataPreviewSummary" class="data-summary">{{ dataPreviewSummary }}</span>
        <div v-if="totalFeatureColumns > 10" class="feature-paging">
          <Button icon="pi pi-angle-double-left" aria-label="First feature columns" :disabled="featureOffset === 0" @click="featureOffset = 0" />
          <Button icon="pi pi-angle-left" aria-label="Previous feature columns" :disabled="featureOffset === 0" @click="featureOffset = Math.max(0, featureOffset - 10)" />
          <span>Columns {{ featureOffset + 1 }}–{{ Math.min(featureOffset + 10, totalFeatureColumns) }} of {{ totalFeatureColumns }}</span>
          <Button icon="pi pi-angle-right" aria-label="Next feature columns" :disabled="featureOffset + 10 >= totalFeatureColumns" @click="featureOffset += 10" />
          <Button icon="pi pi-angle-double-right" aria-label="Last feature columns" :disabled="featureOffset + 10 >= totalFeatureColumns" @click="featureOffset = Math.floor((totalFeatureColumns - 1) / 10) * 10" />
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
          >
            <template #body="{ data }">{{ previewCell(data[col.field]) }}</template>
          </Column>
        </DataTable>
        <Paginator v-if="previewTotalRows > previewRowLimit" :first="previewFirst" :rows="previewRowLimit" :total-records="previewTotalRows" @page="previewFirst = $event.first" />
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
      <section v-if="viewMode === 'plot' && matrixSlices" aria-label="Matrix slices">
        <PlotlyChart :data="[matrixSlices.horizontal]" :layout="sliceLayout('horizontal')" :config="PLOT_CONFIG" />
        <PlotlyChart :data="[matrixSlices.vertical]" :layout="sliceLayout('vertical')" :config="PLOT_CONFIG" />
      </section>
    </div>
  </component>
</template>

<script setup lang="ts">
import { SCIENTIFIC_COLORS } from "@/theme/plotTheme";
import { seriesPalette } from "@/utils/colors";
import MethodHelp from "@/components/MethodHelp.vue";
import AxisSetControls from "@/components/data/AxisSetControls.vue";
import { plotMatrixSlices } from "@/utils/plotMatrixSlices";
import SampleMetadataStyleControls from "../node-detail/panels/SampleMetadataStyleControls.vue";
import { scientificNumber } from "@/utils/scientificEncoding";
import { useDisplayPreferences } from "@/composables/useDisplayPreferences";
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
  evidenceError?: string;
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
      excluded: population.excluded ?? 0,
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
    excluded: 0,
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
  sampleColorField, sampleSymbolField, sampleColorFieldOptions, sampleSymbolFieldOptions,
  featureScaleOptions, featureLabelSetOptions, featureTitleSetOptions, sampleLabelSetOptions, axisSetError,
  selectedFeatureScale, selectedFeatureLabels, selectedFeatureTitle, selectedSampleLabels,
} = useQuickPlotProjection(nodeOutputRef, nodeTypeRef, nodeInputRef, nodeInputsRef, props.plotSelection);

// Offer sample styling wherever the selected plot represents exact sample rows.
// Variable/loadings/aggregate plots have no per-sample marks to style.
const sampleStylePlotKeys = new Set([
  "scientific_pca_summary", "scientific_pca_scores", "pca_scores", "pca_biplot",
  "scientific_pls_scores", "scientific_plsda_scores", "pls_scores", "plsda_scores",
  "classification_scores", "spectra_overlay", "scientific_spectral_overlay",
  "generic_scatter", "generic_boxplot",
]);
const showSampleStyleControls = computed(() =>
  !props.tableOnly && sampleStylePlotKeys.has(selectedPlotKey.value) &&
  !["component_concentrations", "component_spectra"].includes(props.nodeOutput?.metadata?.scientific_matrix_role ?? "") &&
  (sampleColorFieldOptions.value.length > 0 || sampleSymbolFieldOptions.value.length > 0),
);

const correlationCircleSelected = computed(() => selectedPlotKey.value === "scientific_pca_variable_correlations");
const correlationTrace = computed(() => correlationCircleSelected.value
  ? plotData.value.find((trace: any) => Array.isArray(trace.customdata))
  : null);
const oneComponentCorrelations = computed(() => correlationTrace.value?.type === "bar");
const displayDataShape = computed(() => selectedPlotKey.value === "scientific_selection_stability"
  ? { rows: props.nodeOutput?.presentation_value?.per_variable_frequency?.length ?? 0, rowLabel: "variables", cols: 1, colLabel: "selection frequency", range: null }
  : correlationCircleSelected.value
  ? { rows: Array.isArray(correlationTrace.value?.x) ? correlationTrace.value.x.length : 0,
      rowLabel: "variables plotted", cols: oneComponentCorrelations.value ? 1 : 2,
      colLabel: oneComponentCorrelations.value ? "component" : "components", range: null }
  : dataShape.value);

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
      line: { color: SCIENTIFIC_COLORS.inverse, width: 2 },
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

const matrixSlices = ref<ReturnType<typeof plotMatrixSlices>>(null);
const sliceTrace = ref<any>(null);
watch(displayPlotData, () => { matrixSlices.value = null; sliceTrace.value = null; });
const selectMatrixSlice = (event: any) => {
  const point = event?.points?.[0];
  const trace = displayPlotData.value[point?.curveNumber];
  if (!trace || !point) return;
  matrixSlices.value = plotMatrixSlices(trace, point);
  sliceTrace.value = matrixSlices.value ? trace : null;
};
const sliceLayout = (direction: "horizontal" | "vertical") => {
  const layout = displayPlotLayout.value;
  const trace = sliceTrace.value;
  const axis = direction === "horizontal" ? trace?.xaxis : trace?.yaxis;
  const key = axis ? `${axis[0]}axis${axis.slice(1)}` : direction === "horizontal" ? "xaxis" : "yaxis";
  return {
    height: 280,
    title: direction === "horizontal" ? `Row: ${matrixSlices.value?.rowLabel}` : `Column: ${matrixSlices.value?.columnLabel}`,
    xaxis: { title: layout[key]?.title },
    yaxis: { title: trace?.colorbar?.title ?? layout.coloraxis?.colorbar?.title ?? "Value" },
    margin: { t: 45, b: 55, l: 65, r: 25 },
  };
};

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
const defaultViewMode = () => props.tableOnly || props.nodeType === "output.data_table" ? "data" as const : "plot" as const;
const viewMode = ref<"plot" | "data">(defaultViewMode());
watch(() => [props.tableOnly, props.nodeType], () => { viewMode.value = defaultViewMode(); });
const displayPreferences = useDisplayPreferences();
const previewRowLimit = computed(() => displayPreferences.maxRows);
const previewFirst = ref(0);
const featureOffset = ref(0);
const usePlottedTable = computed(() => !props.tableOnly && availablePlots.value.length > 0 && (selectedPlotKey.value === "scientific_selection_stability" || isProjectedScientificKind(props.nodeOutput, "visualization") || correlationCircleSelected.value || selectedPlotKey.value !== availablePlots.value[0]?.key
  || isProjectedScientificKind(props.nodeOutput, "variable_profile")
  || isProjectedScientificKind(props.nodeOutput, "regression_coefficients")
  || !Array.isArray(props.nodeOutput?.data) || props.nodeOutput.data.length === 0));
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
    if (isVisible) viewMode.value = defaultViewMode();
  },
);

function toggleViewMode() {
  viewMode.value = viewMode.value === "plot" ? "data" : "plot";
}

function previewCell(value: unknown): string {
  if (typeof value === "number") return Number.isInteger(value)
    ? String(value) : scientificNumber(value, { significantDigits: 6 });
  return value == null ? "—" : String(value);
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
  const palette = seriesPalette("library");
  const index = Number(candidate.library_trace_index ?? candidate.library_index ?? candidate.sample_rank ?? 0);
  return palette[Math.abs(Math.trunc(Number.isFinite(index) ? index : 0)) % palette.length];
}

// Data preview for table view
const plottedPointPreview = computed(() => {
  if (correlationCircleSelected.value) {
    const variables = Array.isArray(correlationTrace.value?.customdata)
      ? correlationTrace.value.customdata as Array<[string, number, number?]>
      : [];
    return {
      rows: variables.slice(previewFirst.value, previewFirst.value + previewRowLimit.value)
        .map((variable, index) => ({
          _index: previewFirst.value + index + 1,
          variable: variable[0],
          correlation: variable[1],
          ...(!oneComponentCorrelations.value ? { correlation_y: variable[2] } : {}),
        })),
      total: variables.length,
    };
  }
  const rows: Record<string, unknown>[] = [];
  let total = 0;
  for (const [traceIndex, trace] of (plotData.value ?? []).entries()) {
    const series = trace.name || `Trace ${traceIndex + 1}`;
    if (!Array.isArray(trace.x) || !Array.isArray(trace.y)) continue;
    if (Array.isArray(trace.z)) {
      for (let y = 0; y < trace.y.length; y += 1) {
        for (let x = 0; x < trace.x.length; x += 1) {
          if (total >= previewFirst.value && rows.length < previewRowLimit.value) rows.push({ _index: total + 1, series, x: trace.x[x], y: trace.y[y], value: trace.z[y]?.[x] });
          total += 1;
        }
      }
      continue;
    }
    const count = Math.min(trace.x.length, trace.y.length);
    const start = Math.max(0, previewFirst.value - total);
    for (let index = start; index < count && rows.length < previewRowLimit.value; index += 1) {
      const id = trace.ids?.[index];
      const pointLabel = Array.isArray(trace.text) ? trace.text[index] : undefined;
      const axisLabel = (axisRef: string, dimension: string) => {
        const axis = plotLayout.value?.[axisRef.replace(dimension, `${dimension}axis`)];
        return typeof axis?.title === "string" ? axis.title : axis?.title?.text || axisRef;
      };
      const multiAxis = (plotData.value ?? []).some(t => (t.xaxis && t.xaxis !== "x") || (t.yaxis && t.yaxis !== "y"));
      rows.push({ _index: total + index + 1, series,
        ...(typeof id === "string" || typeof id === "number" ? { point_id: id } : {}),
        ...(typeof pointLabel === "string" && pointLabel && !/[<>]/.test(pointLabel) ? { point_label: pointLabel } : {}),
        ...(multiAxis ? { x_quantity: axisLabel(trace.xaxis || "x", "x"), y_quantity: axisLabel(trace.yaxis || "y", "y") } : {}),
        x: trace.x[index], y: trace.y[index] });
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
      .slice(previewFirst.value, previewFirst.value + previewRowLimit.value)
      .map((row, index) => ({
        _index: previewFirst.value + index + 1,
        sample: row.sample,
        t2: row.t2,
        q: row.q,
        outlier: row.outlier === null ? "Not screened" : row.outlier ? "Yes" : "No",
      }));
  }
  if (!Array.isArray(data) || data.length === 0) return plottedPointPreview.value.rows;

  if (data.length > 0 && typeof data[0] === "object" && !Array.isArray(data[0])) {
    const rows = props.nodeType === "analysis.compare_library" && selectedLibrarySample.value
      ? data.filter((row: any) => String(row?.sample ?? "") === selectedLibrarySample.value)
      : data;
    return rows.slice(previewFirst.value, previewFirst.value + previewRowLimit.value).map((row: any, i: number) => ({
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

  return data.slice(previewFirst.value, previewFirst.value + previewRowLimit.value).map((row: any, rowIndex: number) => {
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
        obj[`col_${featureOffset.value + j}`] = typeof val === "number" ? String(Number.isInteger(val) ? val : Number(val.toPrecision(6))) : val;
      });
    } else {
      obj.value = typeof row === "number" ? String(Number.isInteger(row) ? row : Number(row.toPrecision(6))) : row;
    }
    return obj;
  });
});

const dataPreviewSummary = computed(() => {
  if (plotSampling.value?.plottedTableOnly && viewMode.value === "data") {
    return `${plotSampling.value.shown} plotted traces of ${plotSampling.value.total} ${plotSampling.value.sourceNoun}; full source matrix is not in this view`;
  }
  if (usePlottedTable.value) return `${previewFirst.value + 1}–${Math.min(previewFirst.value + previewRowLimit.value, previewTotalRows.value)} of ${previewTotalRows.value} plotted points`;
  if (props.embedded) return `${previewFirst.value + 1}–${Math.min(previewFirst.value + previewRowLimit.value, previewTotalRows.value)} of ${previewTotalRows.value} rows`;
  if (isProjectedScientificKind(props.nodeOutput, "t2_q_diagnostics")) {
    const totalRows = t2QDiagnosticRows(
      props.nodeOutput?.presentation_value,
      props.nodeOutput?.metadata || {},
    ).length;
    return `${Math.min(totalRows, previewRowLimit.value)} of ${totalRows} samples`;
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
  const shownRows = Math.min(totalRows, previewRowLimit.value);
  const shownCols = Math.min(Math.max(0, totalCols - featureOffset.value), 10);
  let summary = `${shownRows} of ${totalRows} rows`;
  if (totalCols > 10) summary += `, ${shownCols} of ${totalCols} columns`;
  return summary;
});

const dataPreviewColumns = computed(() => {
  if (!dataPreview.value.length) return [];
  if (usePlottedTable.value) {
    const title = (axis: any, fallback: string) => {
      const label = typeof axis?.title === "string" ? axis.title : axis?.title?.text || fallback;
      return Array.isArray(axis?.ticktext) && Array.isArray(axis?.tickvals)
        ? `${label} (plot coordinate)` : label;
    };
    const multiAxis = dataPreview.value.some(row => "x_quantity" in row);
    const labels: Record<string, string> = { _index: "#", series: "Series", point_id: "Retained point ID", point_label: "Retained point label", x_quantity: "X quantity", y_quantity: "Y quantity", x: multiAxis ? "X coordinate" : title(plotLayout.value?.xaxis, "X"), y: multiAxis ? "Y coordinate" : title(plotLayout.value?.yaxis, "Y"), value: "Value" };
    return [...new Set(dataPreview.value.flatMap(row => Object.keys(row)))].map(field => ({ field, header: labels[field] || field }));
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
  const isLoadingMatrix = ["pca_loadings", "pca_variable_correlations", "pls_loadings", "plsda_loadings"]
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
      } else if (correlationCircleSelected.value && key === "variable") {
        header = "Variable";
      } else if (correlationCircleSelected.value && key === "correlation") {
        header = String(pcLabels[xAxis.value] || `PC${xAxis.value + 1}`);
      } else if (correlationCircleSelected.value && key === "correlation_y") {
        header = String(pcLabels[yAxis.value] || `PC${yAxis.value + 1}`);
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
          header = typeof featureNames[colIdx] === "number"
            ? previewCell(featureNames[colIdx]) : normalizeSampleLabel(featureNames[colIdx]);
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
.feature-paging { display: flex; align-items: center; gap: .5rem; margin: .5rem 0; color: var(--ss-panel-secondary); }
.embedded-plot .feature-paging { color: var(--text-color); }
.embedded-plot .plot-controls, .embedded-plot .data-table-container { background: var(--surface-card); color: var(--text-color); }
.embedded-plot .control-group label, .embedded-plot .stat-item, .embedded-plot .stat-item strong { color: var(--text-color); }
.embedded-plot :deep(.p-dropdown) { background: var(--surface-card); border-color: var(--surface-border); color: var(--text-color); }
.embedded-plot :deep(.p-dropdown-label) { color: var(--text-color); }
/* Inline result plots fit beside their controls instead of filling 70% of a tall screen. */
.embedded-plot .plot-container { height: clamp(420px, 60vh, 680px); min-height: 420px; }
.quick-plot-modal :deep(.p-dialog-content) {
  padding: 0;
  background: var(--ss-panel-inset);
  overflow: auto;
}

.plot-container {
  display: flex;
  flex-direction: column;
  height: min(70vh, calc(100vh - 96px));
  min-height: min(500px, calc(100vh - 96px));
}

.plot-controls {
  color: var(--ss-panel-secondary);
  display: flex;
  align-items: center;
  gap: 10px 14px;
  padding: 10px 12px;
  background: var(--ss-panel);
  border-bottom: 1px solid var(--ss-panel-border);
  flex-wrap: wrap;
}

.plot-sampling-disclosure {
  padding: 10px 14px;
  border-bottom: 1px solid var(--ss-warning);
  background: var(--ss-panel-warning-surface);
  color: var(--ss-panel-warning);
  font-size: 0.85rem;
  line-height: 1.45;
}

.plot-grouping-notice {
  display: flex;
  gap: 0.45rem;
  align-items: flex-start;
  padding: 0.55rem 0.8rem;
  border-bottom: 1px solid var(--ss-panel-border);
  background: var(--ss-panel);
  color: var(--ss-panel-secondary);
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
  color: var(--ss-panel-muted);
  white-space: nowrap;
}

.plot-controls :deep(.control-group > label) {
  color: var(--ss-panel-secondary);
}

.embedded-plot .plot-controls :deep(.control-group > label) {
  color: var(--text-color);
}

.plot-type-dropdown {
  min-width: 180px;
}

.quick-plot-modal:not(.embedded-plot) .plot-controls :deep(.p-dropdown-label),
.quick-plot-modal:not(.embedded-plot) .plot-controls :deep(.p-dropdown-trigger) {
  color: var(--ss-panel-text);
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
  border: 1px solid var(--ss-panel-border);
  border-radius: 6px;
  background: var(--ss-panel-inset);
  color: var(--ss-panel-secondary);
  cursor: pointer;
  font-size: 0.76rem;
  line-height: 1.15;
  padding: 4px 6px;
  text-align: left;
}

.species-rank-row:hover,
.species-rank-row.selected {
  border-color: var(--ss-info-border);
  background: color-mix(in srgb, var(--ss-info) 14%, transparent);
}

.species-rank-row input {
  pointer-events: none;
}

.species-color-swatch {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--ss-shadow-color) 28%, transparent);
}

.species-rank-row span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.species-rank-row strong {
  color: var(--ss-panel-secondary);
  font-weight: 600;
  white-space: nowrap;
}

.candidate-alignment-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  color: var(--ss-panel-warning);
  border: 1px solid var(--ss-warning);
  border-radius: 6px;
  background: color-mix(in srgb, var(--ss-warning) 22%, transparent);
  padding: 0 10px;
  font-size: 0.8rem;
  font-weight: 600;
}

.candidate-alignment-badge.aligned {
  color: var(--ss-panel-success);
  border-color: var(--ss-success);
  background: color-mix(in srgb, var(--ss-success) 24%, transparent);
}

.stats-summary {
  margin-left: auto;
  gap: 10px;
}

.stat-item {
  font-size: 0.85rem;
  color: var(--ss-panel-muted);
}

.stat-item strong {
  color: var(--ss-panel-text);
}

.plotly-container {
  flex: 1;
  min-height: 0;
  padding: 16px;
  overflow: auto;
  box-sizing: border-box;
}

/* Keep the score map visible when the metadata controls wrap on a narrow screen.
   Scroll the dialog as one surface, rather than shrinking the chart behind its own scrollbar. */
.quick-plot-modal:not(.embedded-plot) .plot-container {
  height: auto;
  min-height: 0;
}

.quick-plot-modal:not(.embedded-plot) .plotly-container {
  flex: none;
  height: clamp(360px, 55vh, 680px);
  min-height: 360px;
  overflow: visible;
}

@media (max-width: 700px) {
  .quick-plot-modal:not(.embedded-plot) .plot-controls {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .quick-plot-modal:not(.embedded-plot) .plot-controls > .control-group {
    min-width: 0;
    margin: 0;
    flex-direction: column;
    align-items: stretch;
  }

  .quick-plot-modal:not(.embedded-plot) .plot-controls :deep(.p-dropdown) {
    width: 100%;
    min-width: 0;
  }

  .quick-plot-modal:not(.embedded-plot) .stats-summary {
    grid-column: 1 / -1;
    flex-direction: row !important;
    flex-wrap: wrap;
    gap: 4px 12px;
  }
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
  color: var(--ss-panel-muted);
}

.empty-plot i {
  font-size: 3rem;
  margin-bottom: 16px;
  color: var(--ss-text-secondary);
}

.empty-plot p {
  font-size: 1.1rem;
  margin: 0 0 8px;
}

.empty-plot small {
  font-size: 0.85rem;
  color: var(--ss-text-secondary);
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
  background: var(--ss-panel-inset);
}

.data-summary {
  display: block;
  font-size: 0.8rem;
  color: var(--ss-panel-muted);
  margin-bottom: 8px;
}

.preview-datatable {
  font-size: 0.76rem;
}

:deep(.preview-datatable .p-datatable-thead > tr > th) {
  background: var(--ss-panel);
  color: var(--ss-panel-text);
  border-color: var(--ss-panel-border);
  font-weight: 600;
  padding: 3px 8px;
  line-height: 1.15;
}

:deep(.preview-datatable .p-datatable-tbody > tr) {
  background: var(--ss-panel-inset);
  color: var(--ss-panel-secondary);
}

:deep(.preview-datatable .p-datatable-tbody > tr > td) {
  border-color: var(--ss-panel-border);
  padding: 2px 8px;
  line-height: 1.15;
}

:deep(.preview-datatable .p-datatable-tbody > tr:nth-child(even)) {
  background: var(--ss-panel);
}

:deep(.preview-datatable .p-datatable-tbody > tr:hover) {
  background: var(--ss-panel-raised);
}

/* PrimeVue overrides for dark theme */
:deep(.p-dropdown) {
  background: var(--ss-panel-inset);
  border-color: var(--ss-panel-border);
}

:deep(.p-dropdown:hover) {
  border-color: var(--ss-panel-border);
}

:deep(.p-dialog) {
  background: var(--ss-panel);
  border: 1px solid var(--ss-panel-border);
}

:deep(.p-dialog-header) {
  background: var(--ss-panel);
  color: var(--ss-panel-text);
  border-bottom: 1px solid var(--ss-panel-border);
  padding: 16px 20px;
}

:deep(.p-dialog-header-icon) {
  color: var(--ss-panel-muted);
}

:deep(.p-dialog-header-icon:hover) {
  background: var(--ss-panel-raised);
  color: var(--ss-panel-text);
}
</style>
