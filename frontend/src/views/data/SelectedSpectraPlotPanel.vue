<template>
  <section class="selected-spectra-panel" aria-label="Comparison preview">
    <header>
      <div>
        <h3>Comparison preview</h3>
        <span v-if="plotFileCount">
          {{ plotFileCount }} file{{ plotFileCount === 1 ? "" : "s" }} ·
          {{ plotDatasetCount }} dataset{{ plotDatasetCount === 1 ? "" : "s" }}
        </span>
      </div>
      <Tag
        v-if="featureTablePreview"
        :value="`${featureTablePreview.totalRows.toLocaleString()} rows`"
        severity="info"
      />
      <Tag
        v-else-if="overlay.displayedSpectra"
        :value="`${overlay.displayedSpectra}${bounded ? ` / ${overlay.totalSpectra}` : ''} spectra`"
        :severity="bounded ? 'warning' : 'info'"
      />
    </header>
    <p v-if="plotDatasetCount" class="preview-scope-note">
      This preview compares the checked data only and does not change the active workflow source.
      Workflow binding follows the active dataset and its Workflow view set above.
    </p>

    <details v-if="singleDataset && !featureTablePreview" class="display-options">
      <summary>Curve styling</summary>
      <div>
        <AxisSetControls
          v-if="featureAxisState.kind === 'valid'"
          v-model:scale-value="selectedFeatureScale"
          v-model:label-value="selectedFeatureLabels"
          v-model:title-value="selectedFeatureTitle"
          :scale-options="featureAxisState.scaleOptions"
          :label-options="featureAxisState.labelOptions"
          :title-options="featureAxisState.titleOptions"
        />
        <AxisSetControls
          v-if="sampleAxisState.kind === 'valid'"
          :scale-value="PRIMARY_AXIS_SET"
          v-model:label-value="selectedSampleLabels"
          :title-value="PRIMARY_AXIS_SET"
          :scale-options="[]"
          :label-options="sampleAxisState.labelOptions"
          :title-options="[]"
        />
        <SampleMetadataStyleControls
          v-if="metadataGrouping.kind === 'valid'"
          v-model:color-value="sampleColorField"
          v-model:style-value="sampleLineField"
          :color-options="sampleColorOptions"
          :style-options="sampleLineOptions"
          style-label="Line"
        />
      </div>
    </details>

    <div v-if="plotDatasetsLoading" class="plot-state" role="status">
      <ProgressSpinner style="width: 28px; height: 28px" />
      <span>Loading selected data…</span>
    </div>
    <div v-else-if="displayError" class="plot-state error" role="alert">
      <i class="pi pi-exclamation-triangle" aria-hidden="true" />
      <div>
        <span>{{ displayError }}</span>
        <Button
          v-if="harmonizationAvailable"
          label="Open Wavenumber Align"
          icon="pi pi-arrow-right"
          size="small"
          outlined
          @click="emit('harmonize')"
        />
      </div>
    </div>
    <div v-else-if="plotDatasetCount === 0" class="plot-state empty">
      <i class="pi pi-chart-line" aria-hidden="true" />
      <span>Choose datasets or files above.</span>
    </div>
    <div v-else-if="featureTablePreview" class="feature-table-preview">
      <template v-if="featureDistributionPlot">
        <p class="feature-plot-summary">
          Pairwise feature relationships; diagonal panels show distributions.
          Hover a point for its sample and target.
          <span v-if="featureDistributionPlot.featureCount < featureTablePreview.totalFeatures">
            Showing the first {{ featureDistributionPlot.featureCount }} features.
          </span>
          <span v-if="featureDistributionPlot.scatterRows < featureDistributionPlot.totalRows">
            Scatter panels show {{ featureDistributionPlot.scatterRows }} of
            {{ featureDistributionPlot.totalRows }} selected rows; histograms use all rows.
          </span>
        </p>
        <PlotlyChart
          :data="featureDistributionPlot.data"
          :layout="featureDistributionPlot.layout"
          :config="{ displayModeBar: true, displaylogo: false }"
        />
      </template>
      <div class="feature-table-summary">
        First {{ featureTablePreview.rows.length.toLocaleString() }} of
        {{ featureTablePreview.totalRows.toLocaleString() }} rows ·
        {{ featureTablePreview.totalFeatures.toLocaleString() }} features
        <span v-if="featureTablePreview.columns.length < featureTablePreview.totalFeatures">
          · first {{ featureTablePreview.columns.length.toLocaleString() }} shown
        </span>
      </div>
      <div class="feature-table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Sample</th>
              <th v-for="column in featureTablePreview.columns" :key="column" scope="col">
                {{ column }}
              </th>
              <th v-if="featureTablePreview.targetName" scope="col">
                {{ featureTablePreview.targetName }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, rowIndex) in featureTablePreview.rows"
              :key="`${rowIndex}:${row.sample}`"
            >
              <th scope="row">{{ row.sample }}</th>
              <td v-for="(value, index) in row.values" :key="index">{{ formatCell(value) }}</td>
              <td v-if="featureTablePreview.targetName">{{ row.target }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <PlotlyChart
      v-else
      :data="plotData"
      :layout="plotLayout"
      :config="{ displayModeBar: true, displaylogo: false }"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import ProgressSpinner from "primevue/progressspinner";
import Tag from "primevue/tag";
import Button from "primevue/button";
import PlotlyChart from "@/components/PlotlyChart.vue";
import AxisSetControls from "@/components/data/AxisSetControls.vue";
import type { DatasetPlotSource } from "@/types";
import {
  alignedSpectrumIdentities,
  buildMultiDatasetOverlay,
  selectedDatasetRows,
} from "@/utils/multiDatasetOverlay";
import {
  datasetAxisDisplayState,
  PRIMARY_AXIS_SET,
  projectDatasetAxisDisplay,
} from "@/utils/datasetAxisSets";
import { buildMetadataLineTraces, metadataGroupingState } from "@/utils/sampleMetadataGrouping";
import SampleMetadataStyleControls from "@/views/workflow-builder/node-detail/panels/SampleMetadataStyleControls.vue";

const props = withDefaults(
  defineProps<{
    plotDatasets?: DatasetPlotSource[];
    plotDatasetCount?: number;
    plotFileCount?: number;
    plotDatasetsLoading?: boolean;
    plotDatasetsError?: string | null;
    activeExperimentId?: number | null;
    activeFileName?: string | null;
  }>(),
  {
    plotDatasets: () => [],
    plotDatasetCount: 0,
    plotFileCount: 0,
    plotDatasetsLoading: false,
    plotDatasetsError: null,
    activeExperimentId: null,
    activeFileName: null,
  },
);
const emit = defineEmits<{ harmonize: [] }>();

const activeCurve = computed(() =>
  props.activeExperimentId != null && props.activeFileName
    ? { experimentId: props.activeExperimentId, fileName: props.activeFileName }
    : null,
);
const overlay = computed(() => buildMultiDatasetOverlay(props.plotDatasets, 50, activeCurve.value));
const singleSource = computed(() =>
  props.plotDatasets.length === 1 ? props.plotDatasets[0] : null,
);
const singleMember = computed(() =>
  props.plotDatasets.length === 1 && props.plotDatasets[0].members.length === 1
    ? props.plotDatasets[0].members[0]
    : null,
);
const singleDataset = computed(() => singleMember.value?.dataset ?? null);
const selectedRowIndexes = computed(() => {
  const dataset = singleDataset.value;
  if (!dataset) return [];
  const files = singleSource.value?.selectedFileNames;
  return files ? selectedDatasetRows(dataset, files) : dataset.data.map((_, index) => index);
});
function selectedRows<T>(rows: T[]): T[] {
  return (selectedRowIndexes.value ?? []).map((index) => rows[index]);
}
const selectedFeatureScale = ref(PRIMARY_AXIS_SET);
const selectedFeatureLabels = ref(PRIMARY_AXIS_SET);
const selectedFeatureTitle = ref(PRIMARY_AXIS_SET);
const selectedSampleLabels = ref(PRIMARY_AXIS_SET);
const sampleColorField = ref("__none__");
const sampleLineField = ref("__none__");
const FEATURE_TABLE_ROW_LIMIT = 10;
const FEATURE_TABLE_COLUMN_LIMIT = 32;

const featureTablePreview = computed(() => {
  const dataset = singleDataset.value;
  if (!dataset || dataset.data_role !== "X_features" || !Array.isArray(dataset.data)) return null;
  if (selectedRowIndexes.value === null) return null;
  const totalRows = selectedRowIndexes.value.length;
  const totalFeatures = dataset.n_features;
  const featureLabels = dataset.x_axis?.labels;
  if (
    !Number.isInteger(totalFeatures) ||
    totalFeatures < 1 ||
    !Array.isArray(featureLabels) ||
    featureLabels.length !== totalFeatures ||
    !featureLabels.every((label) => typeof label === "string" && label.trim())
  ) {
    return null;
  }
  const admittedIndexes = selectedRowIndexes.value.slice(0, FEATURE_TABLE_ROW_LIMIT);
  const admittedRows = admittedIndexes.map((index) => dataset.data[index]);
  if (
    !admittedRows.every(
      (row) =>
        Array.isArray(row) &&
        row.length === totalFeatures &&
        row.every(
          (value) => value === null || (typeof value === "number" && Number.isFinite(value)),
        ),
    )
  ) {
    return null;
  }
  const columnCount = Math.min(totalFeatures, FEATURE_TABLE_COLUMN_LIMIT);
  const sampleLabels = dataset.sample_axis?.labels ?? dataset.y_axis?.labels;
  const targets =
    Array.isArray(dataset.target) && dataset.target.length === dataset.data.length
      ? dataset.target
      : null;
  const targetName = targets
    ? dataset.target_context?.target_name || dataset.target_context?.target_names?.[0] || "Target"
    : null;
  const classNames = dataset.target_context?.class_names ?? [];
  const displayTarget = (value: unknown): string => {
    if (
      dataset.target_context?.target_type === "categorical" &&
      typeof value === "number" &&
      Number.isInteger(value) &&
      value >= 0 &&
      value < classNames.length
    ) {
      return classNames[value];
    }
    return value == null ? "Missing" : String(value);
  };
  return {
    totalRows,
    totalFeatures,
    columns: featureLabels.slice(0, columnCount),
    targetName,
    rows: admittedRows.map((row, position) => ({
      sample:
        Array.isArray(sampleLabels) && typeof sampleLabels[admittedIndexes[position]] === "string"
          ? sampleLabels[admittedIndexes[position]]
          : `Sample ${admittedIndexes[position] + 1}`,
      values: (row as Array<number | null>).slice(0, columnCount),
      target: targets ? displayTarget(targets[admittedIndexes[position]]) : "",
    })),
  };
});
const FEATURE_PLOT_LIMIT = 4;
const FEATURE_SCATTER_ROW_LIMIT = 600;
const FEATURE_COLORS = [
  "#2563eb", "#dc2626", "#059669", "#9333ea", "#d97706", "#0891b2",
];

const featureDistributionPlot = computed(() => {
  const dataset = singleDataset.value;
  const preview = featureTablePreview.value;
  if (!dataset || !preview || preview.totalRows === 0) return null;
  const featureCount = Math.min(preview.totalFeatures, FEATURE_PLOT_LIMIT);
  if (featureCount === 0) return null;
  const selected = selectedRowIndexes.value ?? [];
  const labels = dataset.sample_axis?.labels ?? dataset.y_axis?.labels ?? [];
  const targets =
    Array.isArray(dataset.target) && dataset.target.length === dataset.data.length
      ? dataset.target
      : null;
  const categorical = dataset.target_context?.target_type === "categorical";
  const classNames = dataset.target_context?.class_names ?? [];
  const targetLabel = (index: number): string => {
    if (!targets) return "Not selected";
    const value = targets[index];
    if (categorical && typeof value === "number" && Number.isInteger(value)) {
      return classNames[value] ?? String(value);
    }
    return value == null ? "Missing" : String(value);
  };
  const groups = new Map<string, number[]>();
  for (const index of selected) {
    const group = categorical ? targetLabel(index) : "Samples";
    const rows = groups.get(group) ?? [];
    rows.push(index);
    groups.set(group, rows);
  }
  const traces: Record<string, unknown>[] = [];
  const axes: Record<string, unknown> = {};
  const groupCount = Math.max(groups.size, 1);
  const perGroupLimit = Math.max(1, Math.floor(FEATURE_SCATTER_ROW_LIMIT / groupCount));
  let scatterRows = 0;
  const scatterIndexes = new Map<string, number[]>();
  for (const [group, indexes] of groups) {
    const stride = Math.max(1, Math.ceil(indexes.length / perGroupLimit));
    const sampled = indexes.filter((_, position) => position % stride === 0);
    scatterIndexes.set(group, sampled);
    scatterRows += sampled.length;
  }
  for (let row = 0; row < featureCount; row += 1) {
    for (let column = 0; column < featureCount; column += 1) {
      const subplot = row * featureCount + column + 1;
      const xaxis = subplot === 1 ? "x" : `x${subplot}`;
      const yaxis = subplot === 1 ? "y" : `y${subplot}`;
      axes[subplot === 1 ? "xaxis" : `xaxis${subplot}`] = {
        title: row === featureCount - 1 ? preview.columns[column] : undefined,
        showticklabels: row === featureCount - 1,
        tickfont: { size: 9 },
        zeroline: false,
      };
      axes[subplot === 1 ? "yaxis" : `yaxis${subplot}`] = {
        // Label every left-column panel with its row feature, diagonal
        // included: the row identifies the feature even where the histogram
        // plots counts. Its hovertemplate still discloses "Count".
        title: column === 0 ? preview.columns[row] : undefined,
        showticklabels: column === 0,
        tickfont: { size: 9 },
        zeroline: false,
      };
      let groupIndex = 0;
      for (const [group, indexes] of groups) {
        const color = FEATURE_COLORS[groupIndex % FEATURE_COLORS.length];
        const name = categorical ? group : "Samples";
        const valid = (index: number) =>
          typeof dataset.data[index]?.[column] === "number" &&
          Number.isFinite(dataset.data[index][column]) &&
          (row === column ||
            (typeof dataset.data[index]?.[row] === "number" &&
              Number.isFinite(dataset.data[index][row])));
        if (row === column) {
          const admitted = indexes.filter(valid);
          traces.push({
            type: "histogram",
            xaxis,
            yaxis,
            x: admitted.map((index) => dataset.data[index][column]),
            name,
            legendgroup: name,
            showlegend: subplot === 1,
            marker: { color },
            opacity: 0.58,
            hovertemplate: "Value: %{x}<br>Count: %{y}<extra></extra>",
          });
        } else {
          const admitted = (scatterIndexes.get(group) ?? []).filter(valid);
          traces.push({
            type: "scattergl",
            mode: "markers",
            xaxis,
            yaxis,
            x: admitted.map((index) => dataset.data[index][column]),
            y: admitted.map((index) => dataset.data[index][row]),
            customdata: admitted.map((index) => [
              typeof labels[index] === "string" ? labels[index] : `Sample ${index + 1}`,
              targetLabel(index),
            ]),
            name,
            legendgroup: name,
            showlegend: false,
            marker: { color, size: 6, opacity: 0.72 },
            hovertemplate:
              "<b>%{customdata[0]}</b><br>Target: %{customdata[1]}<br>" +
              "X: %{x}<br>Y: %{y}<extra></extra>",
          });
        }
        groupIndex += 1;
      }
    }
  }
  return {
    data: traces,
    featureCount,
    scatterRows,
    totalRows: selected.length,
    layout: {
      ...axes,
      grid: { rows: featureCount, columns: featureCount, pattern: "independent" },
      barmode: "overlay",
      height: Math.max(420, featureCount * 190),
      margin: { t: 30, r: 30, b: 70, l: 90 },
      showlegend: categorical && groups.size > 1,
      legend: { orientation: "h", y: 1.08 },
      plot_bgcolor: "#fafafa",
      paper_bgcolor: "#ffffff",
      uirevision: `${singleSource.value?.experimentId ?? ""}:${preview.columns.join("|")}`,
    },
  };
});
const featureAxisState = computed(() =>
  datasetAxisDisplayState(singleDataset.value?.x_axis, singleDataset.value?.n_features),
);
const sampleAxisState = computed(() =>
  datasetAxisDisplayState(singleDataset.value?.y_axis, singleDataset.value?.data.length),
);
const featureAxisDisplay = computed(() =>
  projectDatasetAxisDisplay(
    featureAxisState.value,
    selectedFeatureScale.value,
    selectedFeatureLabels.value,
    selectedFeatureTitle.value,
  ),
);
const sampleAxisDisplay = computed(() =>
  projectDatasetAxisDisplay(
    sampleAxisState.value,
    PRIMARY_AXIS_SET,
    selectedSampleLabels.value,
    PRIMARY_AXIS_SET,
  ),
);
const metadataGrouping = computed(() =>
  metadataGroupingState(singleDataset.value?.y_axis, singleDataset.value?.data.length ?? 0),
);
const sampleColorOptions = computed(() =>
  metadataGrouping.value.kind === "valid"
    ? [{ label: "None", value: "__none__" }, ...metadataGrouping.value.colorOptions]
    : [],
);
const sampleLineOptions = computed(() =>
  metadataGrouping.value.kind === "valid" ? metadataGrouping.value.symbolOptions : [],
);

function preserveChoice(current: { value: string }, options: Array<{ value: string }>): void {
  if (options.length && !options.some((option) => option.value === current.value)) {
    current.value = options[0].value;
  }
}

watch(
  [featureAxisState, sampleAxisState, sampleColorOptions, sampleLineOptions],
  ([feature, sample, colors, lines]) => {
    if (feature.kind === "valid") {
      preserveChoice(selectedFeatureScale, feature.scaleOptions);
      preserveChoice(selectedFeatureLabels, feature.labelOptions);
      preserveChoice(selectedFeatureTitle, feature.titleOptions);
    }
    if (sample.kind === "valid") preserveChoice(selectedSampleLabels, sample.labelOptions);
    preserveChoice(sampleColorField, colors);
    preserveChoice(sampleLineField, lines);
  },
  { immediate: true },
);

const singlePlotData = computed(() => {
  const dataset = singleDataset.value;
  if (!dataset?.data.length) return [];
  const x = featureAxisDisplay.value?.values?.length
    ? featureAxisDisplay.value.values
    : dataset.x_axis?.data;
  if (!x?.length) return [];
  const labels = selectedRows(
    sampleAxisDisplay.value?.labels?.length === dataset.data.length
      ? sampleAxisDisplay.value.labels
      : (dataset.y_axis?.labels ?? []),
  );
  const identities = alignedSpectrumIdentities(
    dataset,
    dataset.data.length,
    singleMember.value?.fileName ?? "",
  );
  const fileNames = selectedRows(identities.map(({ fileName }) => fileName));
  const rows = selectedRows(dataset.data);
  const isActive = (index: number) =>
    props.activeExperimentId === singleSource.value?.experimentId &&
    props.activeFileName === fileNames[index];
  if (
    metadataGrouping.value.kind === "valid" &&
    sampleColorField.value !== "__none__" &&
    metadataGrouping.value.columns[sampleColorField.value]
  ) {
    const traces = buildMetadataLineTraces(
      x,
      rows as number[][],
      {
        ...metadataGrouping.value,
        sampleIds: labels,
        columns: Object.fromEntries(
          Object.entries(metadataGrouping.value.columns).map(([key, values]) => [
            key,
            selectedRows(values),
          ]),
        ),
        columnLabels: Object.fromEntries(
          Object.entries(metadataGrouping.value.columnLabels).map(([key, values]) => [
            key,
            selectedRows(values),
          ]),
        ),
      },
      sampleColorField.value,
      sampleLineField.value,
      50,
    );
    const spectralTraceCount = Math.min(rows.length, 50);
    return traces.map((trace, index) => {
      if (index >= spectralTraceCount) return trace;
      const customdata = (trace.customdata as unknown[][]).map((values) => [
        ...values,
        fileNames[index],
      ]);
      return {
        ...trace,
        customdata,
        line: {
          ...((trace.line as Record<string, unknown> | undefined) ?? {}),
          width: isActive(index) ? 3.2 : 1.5,
        },
        hovertemplate: String(trace.hovertemplate).replace(
          "X: %{x}",
          "Filename: %{customdata[3]}<br>X: %{x}",
        ),
      };
    });
  }
  return rows.slice(0, 50).map((row, index) => ({
    type: "scatter",
    mode: "lines",
    x,
    y: row,
    name: labels[index] || `Spectrum ${index + 1}`,
    showlegend: false,
    line: { width: isActive(index) ? 3.2 : 1.4 },
    customdata: x.map(() => [labels[index] || `Spectrum ${index + 1}`, fileNames[index]]),
    hovertemplate:
      "<b>%{customdata[0]}</b><br>Filename: %{customdata[1]}<br>" +
      "X: %{x}<br>Value: %{y:.4f}<extra></extra>",
  }));
});
const plotData = computed(() =>
  singleDataset.value ? singlePlotData.value : overlay.value.traces,
);
const bounded = computed(() => overlay.value.displayedSpectra < overlay.value.totalSpectra);
const displayError = computed(() => {
  if (props.plotDatasetsError) return props.plotDatasetsError;
  if (featureTablePreview.value) return null;
  if (props.plotDatasetCount > 0 && props.plotDatasets.length !== props.plotDatasetCount) {
    return "Some selected data could not be plotted.";
  }
  return overlay.value.error;
});
const harmonizationAvailable = computed(() =>
  displayError.value?.includes("preprocess.wavenumber_align"),
);
// Preserve a scientist's zoom while files on the same compatible axes are
// included, excluded, or highlighted.  A genuinely different axis authority
// receives a new revision and therefore a fresh viewport.
const viewportRevision = computed(() => `${overlay.value.xAxisTitle}|${overlay.value.yAxisTitle}`);
const plotLayout = computed(() => ({
  // Plotly retains user zoom/pan while the selected source membership or
  // active-curve emphasis changes on the same compatible axis authority.
  uirevision: viewportRevision.value,
  xaxis: {
    uirevision: viewportRevision.value,
    title: singleDataset.value
      ? displayAxisTitle(featureAxisDisplay.value?.title, featureAxisDisplay.value?.units)
      : overlay.value.xAxisTitle,
  },
  yaxis: { title: overlay.value.yAxisTitle, uirevision: viewportRevision.value },
  autosize: true,
  height: 480,
  margin: { t: 20, r: 20, b: 58, l: 66 },
  showlegend: false,
  plot_bgcolor: "#fafafa",
  paper_bgcolor: "#ffffff",
}));

function displayAxisTitle(title?: string | null, units?: string | null): string {
  if (title && units) return `${title} (${units})`;
  return title || units || "";
}

function formatCell(value: number | null): string {
  if (value === null) return "Missing";
  return Number.isInteger(value) ? String(value) : Number(value.toPrecision(6)).toString();
}
</script>

<style scoped>
.selected-spectra-panel {
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  margin-bottom: 1rem;
  padding: 0.85rem 1rem 0.5rem;
}

.selected-spectra-panel header {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.selected-spectra-panel header div {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.selected-spectra-panel h3 {
  font-size: 0.95rem;
  margin: 0;
}

.selected-spectra-panel header span {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
}

.preview-scope-note {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
  margin: 0.45rem 0 0;
}

.display-options {
  border-top: 1px solid var(--surface-border);
  margin-top: 0.65rem;
  padding-top: 0.45rem;
}

.display-options summary {
  color: var(--text-color-secondary);
  cursor: pointer;
  font-size: 0.78rem;
}

.display-options > div {
  align-items: end;
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding: 0.65rem 0;
}

.plot-state {
  align-items: center;
  color: var(--text-color-secondary);
  display: flex;
  gap: 0.65rem;
  justify-content: center;
  min-height: 11rem;
}

.plot-state.error {
  color: var(--red-700, #b91c1c);
}

.plot-state.empty i {
  font-size: 1.2rem;
}

.feature-table-preview {
  margin-top: 0.75rem;
}

.feature-plot-summary {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
  margin: 0 0 0.5rem;
}

.feature-table-summary {
  color: var(--text-color-secondary);
  font-size: 0.78rem;
  margin-bottom: 0.45rem;
}

.feature-table-scroll {
  max-height: 25rem;
  overflow: auto;
}

.feature-table-scroll table {
  border-collapse: collapse;
  font-size: 0.78rem;
  min-width: 100%;
  white-space: nowrap;
}

.feature-table-scroll th,
.feature-table-scroll td {
  border-bottom: 1px solid var(--surface-border);
  padding: 0.45rem 0.6rem;
  text-align: right;
}

.feature-table-scroll th:first-child,
.feature-table-scroll td:first-child {
  left: 0;
  position: sticky;
  text-align: left;
}

.feature-table-scroll thead th {
  background: var(--surface-card);
  position: sticky;
  top: 0;
  z-index: 1;
}

.feature-table-scroll thead th:first-child {
  z-index: 2;
}

.feature-table-scroll tbody th {
  background: var(--surface-card);
  font-weight: 600;
}
</style>
