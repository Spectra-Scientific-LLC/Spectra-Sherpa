import { matrixColorEncoding, encodingAnnotation, scoreGeometry, scoreOrientationNotice, componentOrientationNotice, componentPercent, scientificNumber } from "@/utils/scientificEncoding";
import { projectActiveSpectralCohort } from "@/utils/scientificCohort";
import { refusedScientificPlot } from "@/utils/scientificPlotState";
import { numericTableColumns, numericTableColumnPlot } from "@/utils/numericTablePlot";
/* eslint-disable @typescript-eslint/no-explicit-any -- plot payloads from backend nodes are intentionally heterogeneous in this translation layer. */
/**
 * Canonical frontend boundary for scientific presentation projection.
 *
 * The detailed canvas, Quick Plot, retained Run details, Compare navigation,
 * and report image capture all enter through this module. The renderer core is
 * deliberately private to this facade so consumers cannot grow a second
 * interpretation of scientific output payloads.
 */
import { ref, computed, watch, type Ref, type ComputedRef } from "vue";
import {
  useScientificPlotProjectionCore,
  type ScientificPlotProjectionDeps,
} from "@/composables/scientificPlotProjectionCore";
import { resolvePortPayload } from "@/utils/nodeOutput";
import { createCategoryColorMap } from "@/utils/colors";
import { getYAxisLabel, shouldReverseFeatureAxis } from "@/utils/plotLabels";
import {
  SCIENTIFIC_PLOT_LAYOUT,
  buildComponentConcentrationHeatmap,
  buildCategoryCountsPlot,
  buildClassificationResponsesPlot,
  buildConfusionMatrixPlot,
  buildDeclaredVisualizationPlot,
  buildExplainedVariancePlot,
  buildOutOfFoldEvidencePlot,
  buildPeakTablePlot,
  buildPredictedVsActualPlot,
  buildRankedVipPlot,
  buildSalientFeaturesPlot,
  buildScientificMatrixPlot,
  buildVipPlot,
  definedScientificMetadata,
  exactScientificFeatureLabels,
  numericMatrix,
  scientificLabelSequence,
  scientificPortMetadata,
  scientificFeatureCoordinates,
  t2QDiagnosticRows,
} from "@/utils/scientificPlots";
import {
  isProjectedScientificKind,
  projectedPresentationIdentity,
  scientificEvidenceShape,
  scientificPlotOptions,
} from "@/utils/scientificPresentation";
import {
  normalizeSampleLabel,
} from "@/utils/sampleLabels";

// ============================================================================
// Constants
// ============================================================================

export const BASE_PLOT_LAYOUT: Record<string, any> = SCIENTIFIC_PLOT_LAYOUT;

export const PLOT_CONFIG = {
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ["lasso2d", "select2d"],
  displaylogo: false,
};

export interface QuickPlotSelection {
  pcaXAxis: Ref<number>;
  pcaYAxis: Ref<number>;
  featureXAxis: Ref<number>;
  featureYAxis: Ref<number>;
  regressionTargetIdx: Ref<number>;
  scoreColorMode: Ref<string>;
  sampleColorField: Ref<string>;
  sampleSymbolField: Ref<string>;
  selectedFeatureScale: Ref<string>;
  selectedFeatureLabels: Ref<string>;
  selectedFeatureTitle: Ref<string>;
  selectedSampleLabels: Ref<string>;
}

const CATEGORY_COLORS = [
  "#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6",
  "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#6366f1",
];

// ============================================================================
// Plot option interface
// ============================================================================

export interface PlotOption {
  key: string;
  label: string;
}

/** Detailed/canvas projection entry point. */
export function useScientificPlotProjection(deps: ScientificPlotProjectionDeps) {
  return useScientificPlotProjectionCore(deps);
}

export interface RetainedScientificResultAddress {
  runId: number;
  projectId?: number | string | null;
  nodeId?: string | null;
  presentationId?: string | null;
}

export interface ScientificPlotImageTarget {
  nodeId: string;
  element: HTMLElement;
}

/** Build the one route shape used to inspect a retained scientific projection. */
export function retainedScientificResultRoute(address: RetainedScientificResultAddress) {
  return {
    path: `/runs/${address.runId}`,
    query: {
      project: address.projectId ?? undefined,
      node: address.nodeId ?? undefined,
      presentation: address.presentationId ?? undefined,
      view: "Results",
    },
  };
}

/** Normalize report capture inputs without reinterpreting projected plot data. */
export function scientificPlotImageTargets(
  plotRefs?: Map<string, HTMLElement>,
): ScientificPlotImageTarget[] {
  if (!plotRefs) return [];
  return Array.from(plotRefs, ([nodeId, element]) => ({ nodeId, element }));
}

// ============================================================================
// Label helpers
// ============================================================================

const labelSequence = scientificLabelSequence;

function getLabelArray(raw: unknown, fallbackCount: number, prefix = "Sample"): string[] {
  const sequence = labelSequence(raw);
  if (sequence.length > 0) {
    return sequence.map((item, idx) => {
      const n = normalizeSampleLabel(item);
      return n.length > 0 ? n : `${prefix} ${idx + 1}`;
    });
  }
  return Array.from({ length: fallbackCount }, (_, i) => `${prefix} ${i + 1}`);
}

function getCategoryArray(raw: unknown): string[] {
  const normalized = labelSequence(raw)
    .map((item) => normalizeSampleLabel(item))
    .filter((item) => item.length > 0);
  return Array.from(new Set(normalized));
}

function exactCategoryLabels(raw: unknown, expectedLength: number): string[] | null {
  const labels = getCategoryArray(raw);
  return labels.length === expectedLength ? labels : null;
}

const definedMetadata = definedScientificMetadata;
const portMetadata = scientificPortMetadata;
const exactFeatureLabels = exactScientificFeatureLabels;

function formatHoldoutMetric(value: unknown, digits = 3): string {
  const n = Number(value);
  return Number.isFinite(n) ? scientificNumber(n, { decimalPlaces: digits }) : "n/a";
}

function scientificDimensionLabel(role: unknown, fallback: string): string {
  if (typeof role !== "string" || !role.trim()) return fallback;
  const labels: Record<string, string> = {
    actual_predicted_value: "values",
    comparison_field: "comparison fields",
    component: "components",
    observation: "observations",
    sample: "samples",
    spectral_variable: "spectral variables",
    target: "targets",
    variable: "variables",
    feature: "features",
    actual_class: "actual-class rows",
    predicted_class: "prediction-class columns",
  };
  return labels[role] || role.replace(/_/g, " ");
}

function holdoutSplitSummary(viz: Record<string, unknown>): string {
  const metadata = (viz.metadata as Record<string, any> | undefined) ?? {};
  const train = metadata.train ?? {};
  const test = metadata.test ?? {};
  const r2Train = metadata.r2_train ?? train.R2;
  const rmseTrain = metadata.rmse_train ?? train.RMSE;
  const r2Test = metadata.r2_test ?? metadata.r2 ?? test.R2;
  const rmseTest = metadata.rmse_test ?? metadata.rmse ?? test.RMSE;
  if (r2Train === undefined && rmseTrain === undefined) {
    return `Test R²=${formatHoldoutMetric(r2Test)} · RMSE=${formatHoldoutMetric(rmseTest)}`;
  }
  return [
    `Train R²=${formatHoldoutMetric(r2Train)} · RMSE=${formatHoldoutMetric(rmseTrain)}`,
    `Test R²=${formatHoldoutMetric(r2Test)} · RMSE=${formatHoldoutMetric(rmseTest)}`,
  ].join("    ");
}

// ============================================================================
// Axis helpers
// ============================================================================

function resolveXValues(
  metadata: any,
  expectedLength: number,
  portPayload?: any,
): any[] | null {
  return scientificFeatureCoordinates(metadata, expectedLength, portPayload);
}

function shouldReverseX(metadata: any, portPayload?: any): boolean {
  const axis = portPayload?.x_axis || portPayload?.feature_axis || {};
  return shouldReverseFeatureAxis({
    title: axis.title || metadata.x_title,
    units: axis.units || metadata.x_units,
    quantity: axis.quantity || metadata.x_quantity,
    axis_type: axis.axis_type || metadata.x_axis_type,
  });
}

function isFeatureRole(metadata: any, portPayload?: any): boolean {
  const dataRole =
    metadata?.["sherpa.data_role"] ||
    metadata?.data_role ||
    portPayload?.metadata?.["sherpa.data_role"] ||
    portPayload?.metadata?.data_role ||
    portPayload?.data_role;
  return dataRole === "X_features";
}

function xAxisLabel(metadata: any, portPayload?: any): string {
  const axis = portPayload?.x_axis || portPayload?.feature_axis || {};
  const portTitle = axis.title;
  const portUnits = axis.units || metadata.x_units;
  if (portTitle) return portUnits ? `${portTitle} (${portUnits})` : portTitle;
  const xTitle = metadata.x_title || "Feature";
  const xUnits = portUnits || "";
  return xUnits ? `${xTitle} (${xUnits})` : xTitle;
}

// ============================================================================
// Scores plot builder (shared by PCA, PLS, Classification)
// ============================================================================

function buildScoresTraces(
  scores: number[][],
  metadata: any,
  xAxis: number,
  yAxis: number,
  componentPrefix: string,
): any[] {
  if (!scores || !scores.length) return [];

  const pcLabels = metadata.pc_labels || [];
  const sampleLabels = getLabelArray(metadata.sample_labels, scores.length, "Sample");
  const persistedClassLabels = getLabelArray(metadata.sample_classes, 0, "Class");
  const categoryLabels = persistedClassLabels.length === scores.length
    ? persistedClassLabels
    : getLabelArray(metadata.sample_labels, scores.length, "Sample");
  const labelCategories = getCategoryArray(metadata.label_categories);
  const useCategorical = labelCategories.length > 1 && labelCategories.length < 50
    && labelCategories.length < categoryLabels.length;

  const xLabel = pcLabels[xAxis] || `${componentPrefix}${xAxis + 1}`;
  const yLabel = pcLabels[yAxis] || `${componentPrefix}${yAxis + 1}`;
  const hoverSuffix = `<br>${xLabel}: %{x:.15g}<br>${yLabel}: %{y:.15g}<extra></extra>`;

  if (useCategorical) {
    const colorMap = createCategoryColorMap(categoryLabels, labelCategories);
    const groups = new Map<string | number, { x: number[]; y: number[]; labels: string[] }>();
    labelCategories.forEach((cat) => groups.set(cat, { x: [], y: [], labels: [] }));

    scores.forEach((row, idx) => {
      const cat = categoryLabels[idx];
      const g = groups.get(cat);
      if (g) {
        g.x.push(row[xAxis]);
        g.y.push(row[yAxis]);
        g.labels.push(String(sampleLabels[idx]));
      }
    });

    const traces: any[] = [];
    labelCategories.forEach((cat) => {
      const g = groups.get(cat);
      if (g && g.x.length > 0) {
        traces.push({
          type: "scatter",
          mode: "markers",
          x: g.x,
          y: g.y,
          text: g.labels,
          name: String(cat),
          marker: {
            size: 10,
            color: colorMap.get(cat),
            opacity: 0.8,
            line: { width: 1, color: "rgba(0,0,0,0.3)" },
          },
          hovertemplate: `%{text}${hoverSuffix}`,
        });
      }
    });
    if (traces.length > 0) return traces;
  }

  // Fallback: single trace
  return [{
    type: "scatter",
    mode: "markers",
    x: scores.map((row) => row[xAxis]),
    y: scores.map((row) => row[yAxis]),
    text: sampleLabels,
    marker: { size: 10, color: "#3b82f6", opacity: 0.8, line: { width: 1, color: "#1e40af" } },
    hovertemplate: `%{text}${hoverSuffix}`,
  }];
}

function scoresLayout(
  metadata: any,
  xAxis: number,
  yAxis: number,
  componentPrefix: string,
): Record<string, any> {
  const pcLabels = metadata.pc_labels || [];
  const labelCategories = getCategoryArray(metadata.label_categories);
  const hasCat = labelCategories.length > 1 && labelCategories.length < 50;

  const layout: Record<string, any> = {
    ...BASE_PLOT_LAYOUT,
    showlegend: hasCat,
    annotations: [encodingAnnotation(scoreOrientationNotice)],
    margin: {...BASE_PLOT_LAYOUT.margin, t:85},
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: pcLabels[xAxis] || `${componentPrefix}${xAxis + 1}` },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: pcLabels[yAxis] || `${componentPrefix}${yAxis + 1}`, ...scoreGeometry },
  };
  if (hasCat) {
    layout.legend = {
      bgcolor: "rgba(30, 41, 59, 0.8)",
      bordercolor: "#334155",
      borderwidth: 1,
      x: 1, y: 1, xanchor: "right", yanchor: "top",
    };
  }
  return layout;
}

// ============================================================================
// Loadings plot builder
// ============================================================================

function buildLoadingsTraces(
  loadings: number[][],
  metadata: any,
  componentPrefix: string,
  portPayload?: any,
): any[] {
  if (!loadings || !loadings.length) return [];
  const pcLabels = metadata.pc_labels || [];
  const nFeatures = loadings[0]?.length || 0;
  const xValues = resolveXValues(metadata, nFeatures, portPayload) ||
    Array.from({ length: nFeatures }, (_, i) => i);

  return loadings.map((loading, i) => ({
    type: "scatter",
    mode: "lines",
    x: xValues,
    y: loading,
    name: pcLabels[i] || `${componentPrefix}${i + 1}`,
    line: { width: 2 },
  }));
}

function loadingsLayout(metadata: any, portPayload?: any): Record<string, any> {
  const axis = portPayload?.x_axis || portPayload?.feature_axis || {};
  const namedFeatureAxis = [axis.labels, metadata.feature_names].some(
    (labels) =>
      Array.isArray(labels) &&
      labels.length > 0 &&
      labels.some((label: unknown) => typeof label === "string"),
  );
  const title = xAxisLabel(metadata, portPayload);
  return {
    ...BASE_PLOT_LAYOUT,
    ...(namedFeatureAxis
      ? { margin: { ...(BASE_PLOT_LAYOUT.margin || {}), b: 150 } }
      : {}),
    annotations: [encodingAnnotation(componentOrientationNotice)],
    margin: { ...BASE_PLOT_LAYOUT.margin, t:95, ...(namedFeatureAxis ? {b:150} : {}) },
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
    xaxis: {
      ...BASE_PLOT_LAYOUT.xaxis,
      title: namedFeatureAxis ? { text: title, standoff: 24 } : title,
      ...(namedFeatureAxis ? { automargin: true, tickangle: -45 } : {}),
      autorange: shouldReverseX(metadata, portPayload) ? "reversed" : true,
    },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: "Loading" },
  };
}

// ============================================================================
// Server-projected plots
// ============================================================================

function prebuiltPlot(output: any, plotKey: string): { data: any[]; layout: Record<string, any> } {
  const plots = output?.plots || {};
  const plot = plots[plotKey];
  const data = plot?.data || [];
  const backendLayout = plot?.layout || {};
  return {
    data,
    layout: {
      ...BASE_PLOT_LAYOUT,
      ...backendLayout,
      paper_bgcolor: BASE_PLOT_LAYOUT.paper_bgcolor,
      plot_bgcolor: BASE_PLOT_LAYOUT.plot_bgcolor,
      font: BASE_PLOT_LAYOUT.font,
      xaxis: { ...backendLayout.xaxis, gridcolor: "#334155", zerolinecolor: "#475569" },
      yaxis: { ...backendLayout.yaxis, gridcolor: "#334155", zerolinecolor: "#475569" },
    },
  };
}

function hasPrebuiltPlotData(output: any, plotKey: string): boolean {
  const data = output?.plots?.[plotKey]?.data;
  return Array.isArray(data) && data.length > 0;
}

// ============================================================================
// Regression: Predicted vs Actual
// ============================================================================

function regressionPlot(
  metadata: any,
  targetIdx: number,
  actual: unknown = metadata.y_true,
  predicted: unknown = metadata.y_pred,
) {
  const targetNames = metadata.target_names || [];
  const targetName = targetNames[targetIdx] || "";
  const r2List = metadata.r2_per_target;
  const rmseList = metadata.rmse_per_target;
  const r2 = Array.isArray(r2List) && typeof r2List[targetIdx] === "number" ? r2List[targetIdx] : null;
  const rmse = Array.isArray(rmseList) && typeof rmseList[targetIdx] === "number" ? rmseList[targetIdx] : null;

  return buildPredictedVsActualPlot({
    actual,
    predicted,
    targetIndex: targetIdx,
    targetName,
    r2,
    rmse,
  });
}

// ============================================================================
// Classification accuracy builder
// ============================================================================

function getHoldoutMetricsDict(output: any): Record<string, unknown> | null {
  const ports = output?.ports as Record<string, { value?: unknown }> | undefined;
  const metricsValue = ports?.metrics?.value;
  if (metricsValue && typeof metricsValue === "object") {
    // The metrics port value is the flat dict — scalar keys (accuracy,
    // test_accuracy/rmse_test/r2_test, plus legacy aliases) sit at the top
    // level alongside the table wrapper. Prefer this named port before the
    // top-level wrapper, whose metadata may also look like ClassificationTest.
    return metricsValue as Record<string, unknown>;
  }

  if (output && typeof output === "object") {
    const direct = output as Record<string, unknown>;
    const directMeta = direct.metadata as Record<string, unknown> | undefined;
    const directType = directMeta?.type;
    if (
      direct.task_type === "classification" ||
      direct.task_type === "regression" ||
      directType === "ClassificationTest" ||
      directType === "RegressionTest" ||
      "test_accuracy" in direct ||
      "rmse_test" in direct ||
      "r2_test" in direct
    ) {
      return direct;
    }
  }

  const defaultValue = ports?.default?.value;
  if (defaultValue && typeof defaultValue === "object") {
    const bundled = (defaultValue as Record<string, unknown>).metrics;
    if (bundled && typeof bundled === "object") {
      return bundled as Record<string, unknown>;
    }
  }
  return null;
}

function getHoldoutPerClassRows(metrics: Record<string, unknown> | null): Array<Record<string, unknown>> {
  if (!metrics) return [];
  const direct = metrics.per_class;
  if (Array.isArray(direct)) {
    return direct.filter((row): row is Record<string, unknown> => !!row && typeof row === "object" && !Array.isArray(row));
  }
  const tableData = metrics.data;
  if (Array.isArray(tableData)) {
    return tableData.filter((row): row is Record<string, unknown> => !!row && typeof row === "object" && !Array.isArray(row));
  }
  const nestedMetrics = metrics.metrics;
  if (nestedMetrics && typeof nestedMetrics === "object" && !Array.isArray(nestedMetrics)) {
    const nestedPerClass = (nestedMetrics as Record<string, unknown>).per_class;
    if (Array.isArray(nestedPerClass)) {
      return nestedPerClass.filter((row): row is Record<string, unknown> => !!row && typeof row === "object" && !Array.isArray(row));
    }
  }
  return [];
}

/** Format a numeric metric for display in the metrics table. */
function formatMetricValue(v: number): string {
  return scientificNumber(v);
}

// ============================================================================
// Spectra overlay / heatmap builders (data/preprocess nodes)
// ============================================================================

function buildSpectraOverlayPlot(output: any) {
  const matrix = output.data || [];
  const metadata = output.metadata || {};
  const layout: Record<string, any> = spectraOverlayLayout(metadata);
  const refuse = (reason: string) => ({
    data: [],
    layout: { ...layout, meta: { refusal_reason: reason } },
  });
  if (!Array.isArray(matrix) || !Array.isArray(matrix[0]))
    return refuse("No retained spectral rows are available.");
  const axis = output.presentation_value?.sample_axis ?? output.presentation_value?.y_axis;
  const mask = axis?.include_mask;
  if (
    mask != null &&
    (!Array.isArray(mask) ||
      mask.length !== matrix.length ||
      mask.some((v: unknown) => typeof v !== "boolean"))
  ) {
    return refuse("Sample inclusion mask does not match the retained result rows.");
  }
  const active = matrix
    .map((_: unknown, index: number) => index)
    .filter((index: number) => !mask || mask[index]);
  const chosen = active.slice(0, 50);
  if (!chosen.length)
    return refuse("All retained observations are excluded by the sample inclusion mask.");
  const nFeatures = matrix[0].length;
  const featureNames = metadata.feature_names;
  const wn = metadata.wavenumbers;
  const wavenumbers = isFeatureRole(metadata) && Array.isArray(featureNames) && featureNames.length === nFeatures
    ? featureNames
    : (Array.isArray(wn) && wn.length === nFeatures)
      ? wn
      : Array.isArray(featureNames) && featureNames.length === nFeatures
        ? featureNames
        : Array.from({ length: nFeatures }, (_, i) => i + 1);
  const sourceLabels = axis?.labels ?? metadata.labels ?? metadata.sample_labels;
  if (
    sourceLabels != null &&
    (!Array.isArray(sourceLabels) || sourceLabels.length !== matrix.length)
  ) {
    return refuse("Sample labels do not match the retained result rows.");
  }
  const labels = getLabelArray(sourceLabels, matrix.length, "Spectrum");
  const data = chosen.map((index: number) => ({
    type: "scatter",
    mode: "lines",
    x: wavenumbers,
    y: matrix[index],
    name: labels[index],
    meta: { source_row_index: index, sample_label: sourceLabels?.[index] ?? null },
    line: { width: 1.5 }, opacity: 0.8,
  }));
  const excluded = matrix.length - active.length;
  if (active.length > data.length || excluded) {
    const population = {
      shown: data.length,
      total: active.length,
      available: matrix.length,
      excluded,
      method: "first_rows",
      scope: "active_result_rows",
      source_row_indices: chosen,
      sample_labels: chosen.map((index: number) => sourceLabels?.[index] ?? null),
      table_scope: "complete_result",
    };
    layout.meta = { display_population: population };
    layout.title = {
      text: `Spectral overlay<br><sup>First ${data.length} of ${active.length} active result rows; ${excluded} excluded of ${matrix.length} retained</sup>`,
    };
  }
  return { data, layout };
}

function componentSpectraValueLabel(metadata: any): string {
  const raw = String(metadata.value_units_label || metadata.value_units || "Response").trim();
  return raw ? `${raw.charAt(0).toUpperCase()}${raw.slice(1)}` : "Response";
}

function spectraOverlayLayout(metadata: any): Record<string, any> {
  const featureTable = isFeatureRole(metadata);
  const xTitle = featureTable ? "Feature" : metadata.x_title || "Feature";
  const xUnits = metadata.x_units || "";
  const xLabel = xUnits ? `${xTitle} (${xUnits})` : xTitle;
  const reverse = !isFeatureRole(metadata) && shouldReverseX(metadata);
  const yLabel = metadata.scientific_matrix_role === "component_spectra"
    ? componentSpectraValueLabel(metadata)
    : featureTable ? "Value" : getYAxisLabel(metadata) || "Response";

  return {
    ...BASE_PLOT_LAYOUT,
    showlegend: !featureTable,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)", font: { size: 10 } },
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: xLabel, autorange: reverse ? "reversed" : true },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: yLabel },
  };
}

function buildHeatmapTraces(output: any): any[] {
  const data = output.data || [];
  const metadata = output.metadata || {};
  if (!Array.isArray(data[0])) return [];

  const nFeatures = data[0].length;
  const wn = metadata.wavenumbers;
  const xValues = isFeatureRole(metadata) && metadata.feature_names?.length === nFeatures
    ? metadata.feature_names
    : (Array.isArray(wn) && wn.length === nFeatures) ? wn
      : metadata.feature_names?.length === nFeatures ? metadata.feature_names
        : Array.from({ length: nFeatures }, (_, i) => i);
  const sampleLabels = getLabelArray(
    metadata.labels || metadata.sample_labels,
    data.length,
    "Sample",
  );
  const xTitle = metadata.x_title || "Feature";
  const yTitle = metadata.y_title || "Sample";

  return [{
    type: "heatmap",
    z: data, x: xValues, y: sampleLabels,
    ...matrixColorEncoding(data, metadata.value_semantics).trace,
    colorbar: metadata.scientific_matrix_role === "component_spectra"
      ? { title: { text: componentSpectraValueLabel(metadata) } }
      : undefined,
    hovertemplate: `${xTitle}: %{x}<br>${yTitle}: %{y}<br>Value: %{z:.15g}<extra></extra>`,
  }];
}

function heatmapLayout(metadata: any): Record<string, any> {
  const xTitle = metadata.x_title || "Feature";
  const xUnits = metadata.x_units || "";
  const xLabel = xUnits ? `${xTitle} (${xUnits})` : xTitle;
  const reverse = !isFeatureRole(metadata) && shouldReverseX(metadata);

  return {
    ...BASE_PLOT_LAYOUT,
    margin: { ...BASE_PLOT_LAYOUT.margin, l: 160 },
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: xLabel, autorange: reverse ? "reversed" : true },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: metadata.y_title || "Sample", automargin: true },
  };
}

// ============================================================================
// Generic dataset builders (box plot, feature scatter)
// ============================================================================

function buildBoxPlotTraces(output: any): any[] {
  const data = output.data;
  const metadata = output.metadata || {};
  if (!data || !Array.isArray(data) || data.length === 0 || !Array.isArray(data[0])) return [];

  const featureNames = metadata.feature_names || [];
  const sampleLabels = getLabelArray(metadata.sample_classes ?? metadata.labels, data.length, "Sample");
  const nFeatures = Math.min(data[0].length, 10);
  const categories = [...new Set(sampleLabels)];
  const hasCategories = categories.length > 1 && categories.length < 20;

  const traces: any[] = [];
  for (let f = 0; f < nFeatures; f++) {
    traces.push({
      type: "box",
      y: data.map((row: number[]) => row[f]),
      name: featureNames[f] || `Feature ${f + 1}`,
      marker: { color: "#64748b" },
      boxpoints: false,
      showlegend: false,
    });
  }

  if (hasCategories) {
    categories.forEach((cat, catIdx) => {
      const indices = sampleLabels
        .map((label: string, idx: number) => label === cat ? idx : -1)
        .filter((idx: number) => idx !== -1);

      const xValues: string[] = [];
      const yValues: number[] = [];
      for (let f = 0; f < nFeatures; f++) {
        const fname = featureNames[f] || `Feature ${f + 1}`;
        indices.forEach((rowIdx: number) => {
          xValues.push(fname);
          yValues.push(data[rowIdx][f]);
        });
      }
      traces.push({
        type: "scatter", mode: "markers",
        x: xValues, y: yValues,
        name: String(cat),
        marker: { color: CATEGORY_COLORS[catIdx % CATEGORY_COLORS.length], size: 6, opacity: 0.7 },
        legendgroup: String(cat), showlegend: true,
        hovertemplate: `${cat}<br>%{x}: %{y:.15g}<extra></extra>`,
      });
    });
  }
  return traces;
}

function boxPlotLayout(metadata: any): Record<string, any> {
  const sampleLabels = getLabelArray(metadata.sample_classes ?? metadata.labels, 0, "Sample");
  const categories = [...new Set(sampleLabels)];
  const hasCat = categories.length > 1 && categories.length < 20;

  return {
    ...BASE_PLOT_LAYOUT,
    showlegend: hasCat,
    boxmode: "group",
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: "Feature" },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: "Value" },
    legend: hasCat ? {
      ...BASE_PLOT_LAYOUT.legend,
      x: 1, y: 1, xanchor: "right", yanchor: "top",
    } : undefined,
  };
}

function buildFeatureScatterTraces(output: any, xIdx: number, yIdx: number): any[] {
  const data = output.data;
  const metadata = output.metadata || {};
  if (!data || !Array.isArray(data) || data.length === 0 || !Array.isArray(data[0])) return [];

  const featureNames = metadata.feature_names || [];
  const sampleLabels = getLabelArray(metadata.sample_classes ?? metadata.labels, data.length, "Sample");
  const xName = featureNames[xIdx] || `Feature ${xIdx + 1}`;
  const yName = featureNames[yIdx] || `Feature ${yIdx + 1}`;
  const categories = [...new Set(sampleLabels)];
  const hasCategories = categories.length > 1 && categories.length < 20;

  if (hasCategories) {
    return categories.map((cat, catIdx) => {
      const indices = sampleLabels
        .map((label: string, idx: number) => label === cat ? idx : -1)
        .filter((idx: number) => idx !== -1);
      return {
        type: "scatter", mode: "markers",
        x: indices.map((i: number) => data[i][xIdx]),
        y: indices.map((i: number) => data[i][yIdx]),
        name: String(cat),
        marker: { size: 10, color: CATEGORY_COLORS[catIdx % CATEGORY_COLORS.length], opacity: 0.8, line: { width: 1, color: "rgba(0,0,0,0.3)" } },
        hovertemplate: `%{text}<br>${xName}: %{x:.15g}<br>${yName}: %{y:.15g}<extra>${cat}</extra>`,
        text: indices.map((i: number) => `Sample ${i + 1}`),
      };
    });
  }

  return [{
    type: "scatter", mode: "markers",
    x: data.map((row: number[]) => row[xIdx]),
    y: data.map((row: number[]) => row[yIdx]),
    text: sampleLabels,
    marker: { size: 10, color: "#3b82f6", opacity: 0.8, line: { width: 1, color: "#1e40af" } },
    hovertemplate: `%{text}<br>${xName}: %{x:.15g}<br>${yName}: %{y:.15g}<extra></extra>`,
  }];
}

function featureScatterLayout(metadata: any, xIdx: number, yIdx: number): Record<string, any> {
  const featureNames = metadata.feature_names || [];
  const xName = featureNames[xIdx] || `Feature ${xIdx + 1}`;
  const yName = featureNames[yIdx] || `Feature ${yIdx + 1}`;
  const sampleLabels = getLabelArray(metadata.sample_classes ?? metadata.labels, 0, "Sample");
  const categories = [...new Set(sampleLabels)];
  const hasCat = categories.length > 1 && categories.length < 20;

  return {
    ...BASE_PLOT_LAYOUT,
    showlegend: hasCat,
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: xName },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: yName },
    legend: hasCat ? { x: 1, y: 1, xanchor: "right", yanchor: "top", bgcolor: "rgba(0,0,0,0)" } : undefined,
  };
}

// ============================================================================
// Stats distribution builder (fallback for non-spectral data)
// ============================================================================

function buildStatsDistributionTraces(output: any): any[] {
  const data = output.data || [];
  const values: number[] = [];
  for (const row of data) {
    if (Array.isArray(row)) {
      for (const val of row) {
        if (typeof val === "number" && !isNaN(val)) values.push(val);
      }
    } else if (typeof row === "number") {
      values.push(row);
    }
  }
  return [{
    type: "histogram", x: values, nbinsx: 50,
    marker: { color: "#3b82f6" },
    hovertemplate: "Range: %{x}<br>Count: %{y}<extra></extra>",
  }];
}

function statsDistributionLayout(): Record<string, any> {
  return {
    ...BASE_PLOT_LAYOUT,
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: "Value" },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: "Count" },
    bargap: 0.05,
  };
}

// Stats mean & std spectrum builder
// ============================================================================

function buildStatsMeanStdTraces(output: any): any[] {
  const plots = output.plots || {};
  const meanSpec = plots.mean_spectrum ?? plots.mean_feature_response;
  const stdSpec = plots.std_spectrum ?? plots.std_feature_response;
  if (!meanSpec?.x?.length || !meanSpec?.y?.length) return [];

  const x: number[] = meanSpec.x;
  const means: number[] = meanSpec.y;
  const stds: number[] = stdSpec?.y ?? [];
  const traces: any[] = [];

  // Mean ± std shaded band
  if (stds.length === x.length) {
    const upperY = means.map((m: number, i: number) => m + stds[i]);
    const lowerY = means.map((m: number, i: number) => m - stds[i]);
    traces.push({
      x: [...x, ...[...x].reverse()],
      y: [...upperY, ...[...lowerY].reverse()],
      type: "scatter",
      fill: "toself",
      fillcolor: "rgba(59,130,246,0.15)",
      line: { color: "transparent" },
      showlegend: false,
      hoverinfo: "skip",
    });
  }

  // Mean line
  traces.push({
    x, y: means,
    type: "scatter", mode: "lines",
    name: "Mean",
    line: { color: "#3b82f6", width: 2 },
    hovertemplate: "x: %{x:.15g}<br>Mean: %{y:.15g}<extra></extra>",
  });

  // Std line
  if (stds.length === x.length) {
    traces.push({
      x, y: stds,
      type: "scatter", mode: "lines",
      name: "Std Dev",
      line: { color: "#f59e0b", width: 1.5, dash: "dash" },
      yaxis: "y2",
      hovertemplate: "x: %{x:.15g}<br>Std: %{y:.15g}<extra></extra>",
    });
  }

  return traces;
}

function statsMeanStdLayout(): Record<string, any> {
  return {
    ...BASE_PLOT_LAYOUT,
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: "Wavelength / Channel" },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: "Mean Intensity", side: "left" },
    yaxis2: {
      title: "Std Dev",
      overlaying: "y",
      side: "right",
      gridcolor: "transparent",
      color: "#f59e0b",
    },
    legend: { x: 0.01, y: 0.99, bgcolor: "rgba(0,0,0,0.3)", font: { size: 11 } },
  };
}

// ============================================================================
// Preprocessing comparison (independent axes and populations in stacked panels)
// ============================================================================

function preprocessingComparison(input: any, output: any, heatmap: boolean) {
  const panel = (source: any, sourceLabel: string): { data: any[]; layout: Record<string, any>; notice: string } => {
    const value = source?.presentation_value ?? resolvePortPayload(source);
    const data = value?.data ?? source?.data;
    if (!Array.isArray(data?.[0])) return { data: [], layout: {}, notice: `Comparison unavailable: ${sourceLabel} was not retained or is not available.` };
    const projected = projectActiveSpectralCohort({
      data, presentation_value: value,
      metadata: { ...portMetadata(source), ...portMetadata(value),
        ...(value?.units ? { value_units: value.units } : {}),
        scientific_presentation: { kind: "spectral_dataset" } },
    });
    if (projected.error) return { data: [], layout: {}, notice: projected.error };
    const result = projected.output;
    const plot = heatmap
      ? { data: buildHeatmapTraces(result), layout: heatmapLayout(result.metadata) }
      : buildSpectraOverlayPlot(result);
    const color = heatmap ? matrixColorEncoding(result.data, result.metadata.value_semantics) : null;
    const refusal = color?.error ?? plot.layout.meta?.refusal_reason;
    if (refusal) return { data: [], layout: plot.layout, notice: refusal };
    const population = projected.population;
    const shown = heatmap ? result.data.length : plot.data.length;
    const total = result.data.length;
    const displayPopulation = {
      ...population,
      shown, total,
      available: population?.available ?? total,
      excluded: population?.excluded ?? 0,
      method: !heatmap && shown < total ? "first_rows" : "all_active",
      scope: "active_result_rows",
      table_scope: "complete_result",
      source_row_indices: (population?.source_row_indices ?? Array.from({ length: total }, (_, i) => i)).slice(0, shown),
      sample_labels: (result.metadata.sample_labels ?? result.metadata.labels ?? Array(total).fill(null)).slice(0, shown),
    };
    const notice = `${shown} of ${total} active rows shown${shown < total ? `; first ${shown} rows, ${total - shown} unplotted` : ""}${population ? `; ${population.excluded} rows and ${population.excluded_features} features excluded` : ""}${color?.notice ? `; ${color.notice}` : ""}`;
    return { ...plot,
      layout: { ...plot.layout, meta: { ...plot.layout.meta, display_population: displayPopulation } },
      data: plot.data.map((trace: any) => ({ ...trace,
      meta: { ...trace.meta, ...(population && trace.meta?.source_row_index != null
        ? { source_row_index: population.source_row_indices[trace.meta.source_row_index] } : {}) },
    })), notice };
  };
  const original = panel(input, "immediate node input");
  const processed = panel(output, "preprocessed output");
  const scaleNotice = heatmap
    ? "Panels use independent axes and color scales; matching colors do not imply equal values."
    : "Panels use independent axes; matching heights do not imply equal values.";
  const annotations = [original, processed].map((p, i) => ({
    text: `<b>${i === 0 ? "Original (immediate node input)" : "Preprocessed"}</b><br><sup>${p.notice}${i === 0 ? `<br>${scaleNotice}` : ""}</sup>`,
    x: 0, y: i === 0 ? 1 : 0.44, xref: "paper", yref: "paper",
    xanchor: "left", yanchor: "bottom", showarrow: false,
  }));
  return {
    data: [original, processed].flatMap((p, i) => p.data.map((trace: any) => ({
      ...trace, name: heatmap ? (i === 0 ? "Original" : "Preprocessed") : trace.name,
      xaxis: i === 0 ? "x" : "x2", yaxis: i === 0 ? "y" : "y2", showlegend: false,
      ...(heatmap ? { colorbar: { ...trace.colorbar, len: 0.38, y: i === 0 ? 0.8 : 0.2 } } : {}),
    }))),
    layout: {
      ...BASE_PLOT_LAYOUT, height: 850, showlegend: false,
      margin: { ...BASE_PLOT_LAYOUT.margin, t: 95, l: heatmap ? 160 : 80 }, annotations,
      xaxis: { ...original.layout.xaxis, anchor: "y", domain: [0, 1] },
      yaxis: { ...original.layout.yaxis, anchor: "x", domain: [0.6, 1] },
      xaxis2: { ...processed.layout.xaxis, anchor: "y2", domain: [0, 1] },
      yaxis2: { ...processed.layout.yaxis, anchor: "x2", domain: [0, 0.4] },
      meta: {
        // Preserve the existing output-population contract; inputs have their
        // own population and must never be counted as additional result rows.
        display_population: processed.layout.meta?.display_population,
        comparison_populations: {
          original: original.layout.meta?.display_population ?? null,
          preprocessed: processed.layout.meta?.display_population ?? null,
        },
        comparison_notices: [original.notice, processed.notice],
        comparison_scale_notice: scaleNotice,
      },
    },
  };
}

export function useQuickPlotProjection(
  retainedNodeOutput: Ref<any> | ComputedRef<any>,
  nodeType: Ref<string> | ComputedRef<string>,
  nodeInput?: Ref<any> | ComputedRef<any>,
  nodeInputs?: Ref<Record<string, any>> | ComputedRef<Record<string, any>>,
  selection?: QuickPlotSelection,
) {
  const cohort = computed(() => projectActiveSpectralCohort(retainedNodeOutput.value));
  const nodeOutput = computed(() => cohort.value.output);
  // ---- Type detection ----

  const plotMetadata = computed(() => {
    const inputMetadata = nodeInput?.value?.metadata || {};
    const outputMetadata = nodeOutput.value?.metadata || {};
    const namedInputs = nodeInputs?.value || {};
    const featureInput = namedInputs.X ?? namedInputs.x;
    const otherInputs = Object.entries(namedInputs)
      .filter(([name]) => name !== "X" && name !== "x")
      .map(([, port]) => port);
    return {
      ...otherInputs.reduce(
        (metadata, port) => ({ ...metadata, ...portMetadata(port) }),
        {} as Record<string, any>,
      ),
      ...portMetadata(featureInput),
      ...definedMetadata(inputMetadata.diagnostics),
      ...definedMetadata(inputMetadata),
      ...definedMetadata(outputMetadata.diagnostics),
      ...definedMetadata(outputMetadata),
    };
  });

  const scientificFeatureLabels = (expectedLength: number): string[] | null => {
    const outputMetadata = nodeOutput.value?.metadata || {};
    const inputMetadata = nodeInput?.value?.metadata || {};
    const namedInputs = nodeInputs?.value || {};
    const featureInput = namedInputs.X ?? namedInputs.x;
    const candidates = [
      outputMetadata.diagnostics,
      portMetadata(featureInput),
      inputMetadata.diagnostics,
      inputMetadata,
      ...Object.values(namedInputs).map((port) => portMetadata(port)),
      outputMetadata,
      plotMetadata.value,
    ];
    for (const candidate of candidates) {
      const labels = exactFeatureLabels(candidate, expectedLength);
      if (labels) return labels;
    }
    return null;
  };

  const outputType = computed(() => {
    const metadata = nodeOutput.value?.metadata;
    return metadata?.type || null;
  });

  const isPCA = computed(() => {
    const identity = projectedPresentationIdentity(nodeOutput.value);
    if (identity) return ["pca_scores", "pca_loadings", "pca_explained_variance", "t2_q_diagnostics"].includes(identity.kind);
    const metadata = nodeOutput.value?.metadata || {};
    return nodeType.value === "model.pca" || metadata.type === "PCA" || metadata.isPCA === true;
  });

  const isMCR = computed(() => {
    const t = outputType.value;
    return t === "MCR_ALS" || t === "SIMPLISMA" || t === "NMF" || t === "FastICA";
  });

  const isPLS = computed(() => outputType.value === "PLS");
  const isPLSDA = computed(() => outputType.value === "PLS_DA");
  const isHCA = computed(() => outputType.value === "HCA");

  const isClassification = computed(() => {
    const t = outputType.value;
    return t === "PLS_DA" || t === "SIMCA" || t === "KNN";
  });

  const isSpectra = computed(() => {
    const metadata = nodeOutput.value?.metadata || {};
    if (metadata.is_spectra !== undefined) return metadata.is_spectra;
    const xTitle = (metadata.x_title || "").toLowerCase();
    return ["wavenumber", "wavelength", "raman", "cm-1", "cm⁻¹", "nm", "shift"].some(
      (kw) => xTitle.includes(kw),
    );
  });

  const isGenericDataset = computed(() => {
    const metadata = nodeOutput.value?.metadata || {};
    const hasFeatures = metadata.feature_names && metadata.feature_names.length > 0;
    if (!hasFeatures) return false;
    if (metadata.is_spectra === true || metadata.data_type === "spectra") return false;
    return !isPCA.value && !isMCR.value && !isPLS.value && !isPLSDA.value && !isClassification.value && !isHCA.value;
  });

  const isDataOrPreprocess = computed(() => {
    const nt = nodeType.value;
    return nt.startsWith("data.") || nt.startsWith("preprocess.") || nt.startsWith("baseline.") ||
      nt.startsWith("normalize.") || nt.startsWith("smooth.") || nt.startsWith("time_series.") ||
      nt === "selection.variable_select";
  });

  const isRegressionComparison = computed(() =>
    isProjectedScientificKind(nodeOutput.value, "regression_comparison"),
  );

  const hasOutput = computed(() => {
    const o = nodeOutput.value;
    return o && (o.data || o.plots);
  });

  const isPreprocessNode = computed(() => {
    const nt = nodeType.value;
    return nt === "data.filter_samples" || nt.startsWith("preprocess.") || nt.startsWith("baseline.") ||
      nt.startsWith("normalize.") || nt.startsWith("smooth.") || nt.startsWith("time_series.") ||
      nt.startsWith("transfer.") || nt === "selection.variable_select";
  });

  // A node may expose its matrix through a named X port while the legacy
  // `nodeInput` slot is only a summary (or is absent altogether). Keep the
  // before/after preview and its input metadata on the same authoritative
  // payload in both shapes.
  const primaryInput = computed(() => {
    const direct = nodeInput?.value;
    const named = nodeInputs?.value || {};
    if (["transfer.ds", "transfer.pds", "transfer.sws"].includes(nodeType.value)) return named.X_secondary ?? null;
    // A declared but unavailable X must not be replaced by a reference/target port.
    if ("X" in named) return named.X;
    if ("x" in named) return named.x;
    if ("default" in named) return named.default;
    return direct ?? null;
  });

  // ---- Interactive state ----

  const xAxis = selection?.pcaXAxis ?? ref(0);
  const yAxis = selection?.pcaYAxis ?? ref(1);
  const featureXAxis = selection?.featureXAxis ?? ref(0);
  const featureYAxis = selection?.featureYAxis ?? ref(1);
  const regressionTargetIdx = selection?.regressionTargetIdx ?? ref(0);

  // Clamp axes when component count changes
  watch(
    () => nodeOutput.value?.metadata?.n_components,
    (nComponents) => {
      if ((isPCA.value || isPLS.value || isClassification.value) && typeof nComponents === "number") {
        const maxIdx = Math.max(0, nComponents - 1);
        if (xAxis.value > maxIdx) xAxis.value = maxIdx;
        if (yAxis.value > maxIdx) yAxis.value = maxIdx;
        if (nComponents === 1) { xAxis.value = 0; yAxis.value = 0; }
        else if (xAxis.value === yAxis.value && nComponents > 1) {
          yAxis.value = (xAxis.value + 1) % nComponents;
        }
      }
    },
    { immediate: true },
  );

  // Reset axes on type change
  const currentType = computed(() => outputType.value);
  watch(currentType, (newT, oldT) => {
    if (oldT && newT !== oldT) {
      xAxis.value = 0;
      yAxis.value = 1;
    }
  });

  // ---- Axis options ----

  const axisOptions = computed(() => {
    const metadata = nodeOutput.value?.metadata || {};
    const kind = projectedPresentationIdentity(nodeOutput.value)?.kind;
    const prefix = kind === "pls_scores" || kind === "plsda_scores" ? "LV" : "PC";
    const componentLabels = metadata.pc_labels || metadata.component_labels || [];
    const projectedMatrix = numericMatrix(nodeOutput.value);
    const n = componentLabels.length || metadata.n_components || projectedMatrix?.[0]?.length || 1;
    const variance = kind === "pca_scores"
      ? metadata.explained_variance_ratio || metadata.diagnostics?.explained_variance_ratio || []
      : metadata.x_explained_variance || metadata.diagnostics?.x_explained_variance || [];
    return Array.from({ length: n }, (_, i) => {
      const base = componentLabels[i] || `${prefix}${i + 1}`;
      const label = typeof variance[i] === "number" && !base.includes("%")
        ? `${base} (${componentPercent(variance[i])}%)`
        : base;
      return { label, value: i };
    });
  });

  watch(
    axisOptions,
    (options) => {
      const count = options.length;
      if (count <= 1) {
        xAxis.value = 0;
        yAxis.value = 0;
        return;
      }
      xAxis.value = Math.min(xAxis.value, count - 1);
      yAxis.value = Math.min(yAxis.value, count - 1);
      if (xAxis.value === yAxis.value) yAxis.value = (xAxis.value + 1) % count;
    },
    { immediate: true },
  );

  watch([xAxis, yAxis], ([nextX, nextY], [previousX, previousY]) => {
    if (axisOptions.value.length <= 1 || nextX !== nextY) return;
    if (nextX !== previousX) {
      yAxis.value = (nextX + 1) % axisOptions.value.length;
    } else if (nextY !== previousY) {
      xAxis.value = (nextY + 1) % axisOptions.value.length;
    }
  });

  const featureAxisOptions = computed(() => {
    const metadata = nodeOutput.value?.metadata || {};
    const featureNames = metadata.feature_names || [];
    if (featureNames.length === 0) {
      const n = nodeOutput.value?.data?.[0]?.length || 4;
      return Array.from({ length: n }, (_, i) => ({ label: `Feature ${i + 1}`, value: i }));
    }
    return featureNames.map((name: string, i: number) => ({ label: name, value: i }));
  });

  const regressionTargetOptions = computed(() => {
    const metadata = nodeOutput.value?.metadata || {};
    const targetPayload = resolvePortPayload(nodeInputs?.value?.y);
    const yTrue = metadata.y_true ?? targetPayload?.data ?? nodeInputs?.value?.y?.data;
    if (!Array.isArray(yTrue) || yTrue.length === 0) return [];
    const nTargets = Array.isArray(yTrue[0]) ? yTrue[0].length : 1;
    const names = metadata.target_names || [];
    return Array.from({ length: nTargets }, (_, i) => ({
      label: names[i] || `Target ${i + 1}`,
      value: i,
    }));
  });

  const regressionActual = computed(() => {
    const metadata = nodeOutput.value?.metadata || {};
    const targetPayload = resolvePortPayload(nodeInputs?.value?.y);
    return metadata.y_true ?? targetPayload?.data ?? nodeInputs?.value?.y?.data;
  });

  const regressionPredicted = computed(() => {
    const metadata = nodeOutput.value?.metadata || {};
    if (metadata.y_pred !== undefined) return metadata.y_pred;
    return nodeType.value === "model.fitted_pls" ? nodeOutput.value?.data : undefined;
  });

  const sharedOutput = computed(() => nodeOutput.value
    ? { ...nodeOutput.value, metadata: plotMetadata.value }
    : null);
  const { projectPlot, metadataGroupingError: coreMetadataGroupingError } = useScientificPlotProjectionCore({
    nodeOutput: sharedOutput,
    nodeType,
    nodeTypeKey: nodeType,
    hasOutput: computed(() => Boolean(hasOutput.value)),
    isPCAOutput: isPCA,
    pcaXAxis: xAxis,
    pcaYAxis: yAxis,
    scoreColorMode: selection?.scoreColorMode ?? ref("auto"),
    sampleColorField: selection?.sampleColorField ?? ref(""),
    sampleSymbolField: selection?.sampleSymbolField ?? ref(""),
    selectedFeatureScale: selection?.selectedFeatureScale ?? ref("__primary__"),
    selectedFeatureLabels: selection?.selectedFeatureLabels ?? ref("__primary__"),
    selectedFeatureTitle: selection?.selectedFeatureTitle ?? ref("__primary__"),
    selectedSampleLabels: selection?.selectedSampleLabels ?? ref("__primary__"),
    plsdaLoadingsViewMode: ref("lines"),
    featureXAxis,
    featureYAxis,
    contourClickPoint: ref(null),
    regressionTargetOptions,
  });

  // ---- Available plots ----

  const availablePlots = computed<PlotOption[]>(() => {
    if (!hasOutput.value) return [];
    const plots: PlotOption[] = [];
    const nt = nodeType.value;
    const identity = projectedPresentationIdentity(nodeOutput.value);
    if (nt === "output.data_table" && (!nodeOutput.value?.presentation_contract || identity?.kind === "visualization")) {
      return numericTableColumns(nodeOutput.value).map((label, index) => ({ key: `table_column:${index}`, label }));
    }
    if (isPreprocessNode.value && (identity?.kind === "spectral_dataset" || (!identity && !nodeOutput.value?.presentation_contract))) {
      return [
        { key: "spectra_overlay", label: "Data Overlay" },
        { key: "spectra_heatmap", label: "Heatmap" },
      ];
    }
    if (projectedPresentationIdentity(nodeOutput.value)) {
      return scientificPlotOptions(nodeOutput.value);
    }
    if (nodeOutput.value?.presentation_contract) {
      // Current canonical outputs are rendered only after exact source-port
      // projection. A missing/invalid projection must not fall through to the
      // historical node-name and JavaScript-shape adapters below.
      return [];
    }

    if (isPCA.value) {
      plots.push(
        { key: "pca_scores", label: "Scores Plot" },
        { key: "pca_biplot", label: "Biplot" },
        { key: "pca_loadings", label: "Loadings Plot" },
        { key: "pca_scree", label: "Scree Plot" },
        { key: "pca_diagnostics", label: "Diagnostics Plot" },
      );
      return plots;
    }

    if (isMCR.value) {
      const metadata = nodeOutput.value?.metadata || {};
      const t = metadata.type;
      const cLabel = t === "NMF" ? "Concentrations (W)" : t === "FastICA" ? "Sources (S)" : "Concentrations (C)";
      const sLabel = t === "NMF" ? "Basis Spectra (H)" : t === "FastICA" ? "Spectral Profiles (Sᵀ)" : "Pure Spectra (Sᵀ)";
      plots.push(
        { key: "mcr_concentrations", label: cLabel },
        { key: "mcr_spectra", label: sLabel },
      );
      if (t === "MCR_ALS") {
        plots.push(
          { key: "mcr_original_contour", label: "Original Contour" },
          { key: "mcr_reconstructed_contour", label: "Reconstructed Contour" },
          { key: "mcr_residual_contour", label: "Residual Contour" },
        );
      }
      return plots;
    }

    if (isPLS.value) {
      plots.push(
        { key: "pls_scores", label: "Scores Plot" },
        { key: "pls_loadings", label: "Loadings Plot" },
        { key: "regression", label: "Predicted vs Actual" },
      );
      return plots;
    }

    if (isPLSDA.value) {
      const output = nodeOutput.value;
      if (hasPrebuiltPlotData(output, "scores")) {
        plots.push({ key: "plsda_scores", label: "Scores Plot" });
      }
      if (
        hasPrebuiltPlotData(output, "loadings_lines") ||
        hasPrebuiltPlotData(output, "loadings") ||
        hasPrebuiltPlotData(output, "loadings_biplot")
      ) {
        plots.push({ key: "plsda_loadings", label: "Loadings Plot" });
      }
      if (hasPrebuiltPlotData(output, "vip")) {
        plots.push({ key: "plsda_vip", label: "VIP Scores" });
      }
      if (hasPrebuiltPlotData(output, "confusion_matrix_train")) {
        plots.push({ key: "plsda_cm_train", label: "Confusion Matrix (Training)" });
      }
      if (hasPrebuiltPlotData(output, "confusion_matrix_cv")) {
        plots.push({ key: "plsda_cm_cv", label: "Confusion Matrix (Cross-Validation)" });
      }
      if (projectPlot("classification_accuracy")!.data.length > 0) {
        plots.push({ key: "classification_accuracy", label: "Per-Class Accuracy" });
      }
      return plots;
    }

    if (isClassification.value && !isPLSDA.value) {
      // SIMCA, KNN
      plots.push(
        { key: "classification_scores", label: "Scores Plot" },
        { key: "classification_cm_train", label: "Confusion Matrix (Training)" },
        { key: "classification_cm_cv", label: "Confusion Matrix (CV)" },
        { key: "classification_accuracy", label: "Class Accuracy" },
      );
      return plots;
    }

    if (isHCA.value) {
      plots.push({ key: "hca_dendrogram", label: "Dendrogram" });
      return plots;
    }

    if (isRegressionComparison.value && regressionActual.value && regressionPredicted.value) {
      plots.push({ key: "regression", label: "Predicted vs Actual" });
      if (nt === "model.fitted_pls") {
        const vipPayload = resolvePortPayload(nodeOutput.value?.ports?.vip_scores);
        const vipScores = vipPayload?.data ?? nodeOutput.value?.ports?.vip_scores?.data;
        if (Array.isArray(vipScores) && vipScores.length > 0) {
          plots.push({ key: "regression_vip", label: "VIP Scores" });
        }
        const diagnostics = nodeOutput.value?.metadata?.diagnostics || {};
        if (
          Array.isArray(diagnostics.x_explained_variance) &&
          Array.isArray(diagnostics.y_explained_variance)
        ) {
          plots.push({ key: "regression_explained_variance", label: "Explained Variance" });
        }
      }
      return plots;
    }

    if (nt === "stats.summary") {
      const statsPlots = (nodeOutput.value as any)?.plots;
      if (statsPlots?.mean_spectrum || statsPlots?.mean_feature_response) {
        plots.push({ key: "stats_mean_std", label: isGenericDataset.value ? "Mean & Std Feature Response" : "Mean & Std Spectrum" });
      } else {
        plots.push({ key: "stats_distribution", label: "Distribution Plot" });
      }
      return plots;
    }

    if (nt === "analysis.peak_finding") {
      plots.push({ key: "peak_finding", label: "Spectra with Peaks" });
      return plots;
    }

    if (nt === "analysis.compare_library") {
      plots.push({ key: "library_compare", label: "Library Overlay" });
      return plots;
    }

    if (nt === "output.plot" || nt === "output.contour") {
      plots.push({ key: "plot_visualization", label: "Visualization" });
      return plots;
    }

    if (nt === "output.data_table") return plots;

    if (
      nt === "diagnostics.regression_evaluator" ||
      nt === "diagnostics.classification_evaluator" ||
      nt === "diagnostics.cross_validation"
    ) {
      // Canonical evaluator nodes expose a typed `visualization` port.
      // Cross-validation retains its bundled shape until it adopts that
      // current evaluator contract.
      const ports = nodeOutput.value?.ports;
      const vizObj =
        (ports?.visualization?.value as Record<string, unknown> | undefined) ??
        ((ports?.default?.value as Record<string, unknown> | undefined)?.visualization as
          | Record<string, unknown>
          | undefined);
      if (vizObj?.type === "confusion_matrix") {
        plots.push({ key: "holdout_confusion", label: "Evaluation Results" });
      } else if (vizObj?.type === "predicted_vs_actual") {
        plots.push({ key: "holdout_regression", label: "Evaluation Results" });
      }
      return plots;
    }

    // Data / Preprocess nodes
    if (isDataOrPreprocess.value || plots.length === 0) {
      if (isGenericDataset.value) {
        plots.push(
          { key: "generic_boxplot", label: "Box Plot by Label" },
          { key: "generic_scatter", label: "Feature Scatter Plot" },
        );
      } else {
        plots.push(
          { key: "spectra_overlay", label: isSpectra.value ? "Spectra Overlay" : "Data Overlay" },
          { key: "spectra_heatmap", label: "Heatmap" },
        );
      }
    }

    return plots;
  });

  // ---- Selected plot key ----

  const selectedPlotKey = ref("");

  // Auto-select first plot when available plots change
  watch(
    availablePlots,
    (plots) => {
      if (plots.length > 0 && !plots.some((p) => p.key === selectedPlotKey.value)) {
        selectedPlotKey.value = plots[0].key;
      } else if (plots.length === 0) {
        selectedPlotKey.value = "";
      }
    },
    { immediate: true },
  );

  watch(
    () => projectedPresentationIdentity(nodeOutput.value)?.source_port ?? "",
    (sourcePort, previousSourcePort) => {
      if (previousSourcePort !== undefined && sourcePort !== previousSourcePort) {
        selectedPlotKey.value = availablePlots.value[0]?.key ?? "";
      }
    },
  );

  // ---- Controls visibility ----

  const showAxisControls = computed(() => {
    const key = selectedPlotKey.value;
    return key === "scientific_pca_scores" || key === "scientific_pls_scores" || key === "scientific_plsda_scores" ||
      key === "pca_scores" || key === "pca_biplot" || key === "pca_diagnostics" ||
      key === "pls_scores" || key === "classification_scores";
  });

  const showFeatureControls = computed(() => {
    return selectedPlotKey.value === "generic_scatter";
  });

  const showRegressionTargetControl = computed(() => {
    return selectedPlotKey.value === "regression" && regressionTargetOptions.value.length > 1;
  });

  // ---- Plot data and layout ----

  const rawPlotResult = computed<{ data: any[]; layout: Record<string, any> }>(() => {
    const output = nodeOutput.value;
    if (!output) return { data: [], layout: BASE_PLOT_LAYOUT };
    const metadata = plotMetadata.value;
    const plotOutput = { ...output, metadata };
    const key = selectedPlotKey.value;
    const sharedPlot = projectPlot(key);
    if (sharedPlot) return sharedPlot;

    if (key.startsWith("table_column:")) {
      const plotted = numericTableColumnPlot(output, Number(key.slice("table_column:".length)));
      return plotted ? { data: plotted.data, layout: { ...BASE_PLOT_LAYOUT, ...plotted.layout } }
        : refusedScientificPlot("The selected numeric table column is unavailable.", BASE_PLOT_LAYOUT);
    }

    if (key.startsWith("scientific_visualization:")) {
      return buildDeclaredVisualizationPlot(
        output,
        key.slice("scientific_visualization:".length),
      );
    }

    switch (key) {
      case "scientific_category_counts":
        return buildCategoryCountsPlot(output);
      case "scientific_confusion_matrix":
        return buildConfusionMatrixPlot(output, metadata);
      case "scientific_classification_responses":
        return buildClassificationResponsesPlot(output, metadata);
      case "scientific_out_of_fold":
        return buildOutOfFoldEvidencePlot(output);
      case "scientific_peak_table":
        return buildPeakTablePlot(output);
      case "scientific_salient_features":
        return buildSalientFeaturesPlot(output);
      case "scientific_pls_scores":
      case "scientific_plsda_scores": {
        const metadataWithLabels = {
          ...metadata,
          pc_labels: axisOptions.value.map((option) => option.label),
        };
        return {
          data: buildScoresTraces(
            numericMatrix(output) || [],
            metadataWithLabels,
            xAxis.value,
            yAxis.value,
            "LV",
          ),
          layout: scoresLayout(metadataWithLabels, xAxis.value, yAxis.value, "LV"),
        };
      }
      case "scientific_component_scores": {
        const matrix = numericMatrix(output);
        const payload = resolvePortPayload(output.presentation_value);
        const componentLabels = labelSequence(
          payload?.x_axis?.labels ?? metadata.component_labels ?? metadata.feature_names,
        );
        const componentCount = matrix?.[0]?.length ?? 0;
        return buildScientificMatrixPlot({
          value: output,
          seriesBy: "columns",
          xTitle: "Sample",
          yTitle: "Score",
          seriesPrefix: "Component",
          seriesLabels:
            componentLabels.length === componentCount ? componentLabels : undefined,
        });
      }
      case "scientific_pls_loadings":
      case "scientific_plsda_loadings":
        return {
          data: buildLoadingsTraces(
            numericMatrix(output) || [],
            metadata,
            "LV",
            output.presentation_value,
          ),
          layout: loadingsLayout(metadata, output.presentation_value),
        };
      case "scientific_component_loadings":
        return buildScientificMatrixPlot({
          value: output,
          seriesBy: "rows",
          xTitle: "Variable",
          yTitle: "Loading",
          seriesPrefix: "LV",
        });
      case "scientific_regression_coefficients": {
        const coefficientMatrix = numericMatrix(output);
        const targetCount = coefficientMatrix?.[0]?.length ?? 0;
        const loadingsPayload = resolvePortPayload(nodeOutput.value?.ports?.loadings);
        const outputMetadata = nodeOutput.value?.metadata || {};
        const outputDiagnostics = outputMetadata.diagnostics || {};
        const targetLabels = [
          outputMetadata.target_names,
          outputMetadata.classes,
          outputMetadata.label_categories,
          outputDiagnostics.target_names,
          outputDiagnostics.classes,
          outputDiagnostics.label_categories,
          outputDiagnostics.metrics?.classes,
          plotMetadata.value.target_names,
          plotMetadata.value.classes,
          plotMetadata.value.label_categories,
        ]
          .map((candidate) => exactCategoryLabels(candidate, targetCount))
          .find((labels): labels is string[] => labels !== null);
        const featureAxis = loadingsPayload?.x_axis || loadingsPayload?.feature_axis || {};
        const featureTable =
          (plotMetadata.value.data_role === "X_features" ||
          plotMetadata.value["sherpa.data_role"] === "X_features") &&
          !featureAxis.units && !plotMetadata.value.x_units;
        return buildScientificMatrixPlot({
          value: output,
          seriesBy: "columns",
          xTitle: featureTable ? "Variable" : xAxisLabel({ ...plotMetadata.value, x_title: "Feature" }, loadingsPayload),
          yTitle: "Coefficient",
          seriesPrefix: "Target",
          pointLabels:
            resolveXValues(
              plotMetadata.value,
              coefficientMatrix?.length ?? 0,
              loadingsPayload,
            ) ?? scientificFeatureLabels(coefficientMatrix?.length ?? 0),
          seriesLabels: targetLabels,
          reverseX: shouldReverseX(plotMetadata.value, loadingsPayload),
        });
      }
      case "scientific_variable_profile":
      {
        const scores = Array.isArray(output.data) ? output.data : [];
        const namedInputs = nodeInputs?.value || {};
        const featureInput = resolvePortPayload(namedInputs.X ?? namedInputs.x);
        return buildVipPlot({
          scores,
          featureLabels:
            resolveXValues(plotMetadata.value, scores.length, featureInput)
            ?? scientificFeatureLabels(scores.length),
          xTitle: xAxisLabel(plotMetadata.value, featureInput),
          reverseX: shouldReverseX(plotMetadata.value, featureInput),
        });
      }
      case "scientific_spectral_overlay":
        if (metadata.scientific_matrix_role === "component_concentrations") {
          const matrix = numericMatrix(output);
          const payload = resolvePortPayload(output.presentation_value);
          const sampleAxis = payload?.y_axis;
          const componentAxis = payload?.x_axis;
          const sampleCount = matrix?.length ?? 0;
          const componentCount = matrix?.[0]?.length ?? 0;
          const sampleLabels = labelSequence(
            sampleAxis?.labels ?? metadata.sample_labels ?? metadata.labels,
          );
          const sampleValues = Array.isArray(sampleAxis?.data) && sampleAxis.data.length === sampleCount
            ? sampleAxis.data
            : Array.from({ length: sampleCount }, (_, index) => index + 1);
          const componentLabels = labelSequence(
            componentAxis?.labels ?? metadata.feature_names,
          );
          return buildScientificMatrixPlot({
            value: output,
            seriesBy: "columns",
            xTitle: sampleAxis?.title || metadata.y_title || "Sample",
            yTitle: payload?.units || metadata.value_units || "Relative concentration",
            seriesPrefix: "Component",
            pointLabels: sampleValues,
            pointHoverLabels: sampleLabels.length === sampleCount ? sampleLabels : undefined,
            seriesLabels: componentLabels.length === componentCount ? componentLabels : undefined,
          });
        }
        return isFeatureRole(metadata)
          ? { data: buildBoxPlotTraces(plotOutput), layout: boxPlotLayout(metadata) }
          : buildSpectraOverlayPlot(plotOutput);
      case "scientific_spectral_heatmap":
        if (metadata.scientific_matrix_role === "component_concentrations") {
          return buildComponentConcentrationHeatmap(output);
        }
        return { data: buildHeatmapTraces(output), layout: heatmapLayout(metadata) };
      case "scientific_time_series":
        return buildScientificMatrixPlot({
          value: output,
          seriesBy: "columns",
          xTitle: "Observation",
          yTitle: "Response",
          seriesPrefix: "Series",
        });
      case "scientific_visualization":
        return buildDeclaredVisualizationPlot(output);
      case "scientific_pls_explained_variance":
        return buildExplainedVariancePlot({
          xVariance: numericMatrix(output)?.map((row) => row[0]),
          yVariance: numericMatrix(output)?.map((row) => row[1]),
        });
      case "scientific_explained_variance": {
        const matrix = numericMatrix(output);
        return buildExplainedVariancePlot({
          xVariance: matrix?.map((row) => row[0]),
          yVariance: matrix?.map((row) => row[1]),
        });
      }
      // PLS
      case "pls_scores":
        return {
          data: buildScoresTraces(output.data, metadata, xAxis.value, yAxis.value, "LV"),
          layout: scoresLayout(metadata, xAxis.value, yAxis.value, "LV"),
        };
      case "pls_loadings": {
        const loadingsPort = output.ports?.X_loadings;
        const loadingsPayload = resolvePortPayload(loadingsPort);
        const loadings = loadingsPort?.data || metadata.X_loadings || [];
        return {
          data: buildLoadingsTraces(loadings, metadata, "LV", loadingsPayload),
          layout: loadingsLayout(metadata, loadingsPayload),
        };
      }

      // Regression (PLS, PCR, SVR)
      case "regression":
        return regressionPlot(
          metadata,
          regressionTargetIdx.value,
          regressionActual.value,
          regressionPredicted.value,
        );
      case "regression_vip": {
        const vipPayload = resolvePortPayload(output.ports?.vip_scores);
        return buildVipPlot({
          scores: vipPayload?.data ?? output.ports?.vip_scores?.data,
          featureLabels: metadata.feature_names,
        });
      }
      case "regression_explained_variance": {
        const diagnostics = metadata.diagnostics || {};
        return buildExplainedVariancePlot({
          xVariance: diagnostics.x_explained_variance,
          yVariance: diagnostics.y_explained_variance,
        });
      }

      // PLS-DA (pre-built plots)
      case "plsda_scores":
        return prebuiltPlot(output, "scores");
      case "plsda_loadings":
        return prebuiltPlot(output, "loadings_lines") || prebuiltPlot(output, "loadings");
      case "plsda_loadings_biplot":
        return prebuiltPlot(output, "loadings_biplot");
      case "plsda_vip": {
        // The node-owned plot was the pre-C2zr Inspector authority. Preserve
        // it exactly when present; a normalized ranked projection is only the
        // fallback for older/current results that expose raw VIP values alone.
        const prebuilt = prebuiltPlot(output, "vip");
        if (prebuilt.data.length > 0) return prebuilt;
        const rawVip = metadata.vip_scores;
        if (Array.isArray(rawVip) && rawVip.length > 0) {
          const loadingsPayload = resolvePortPayload(
            output.ports?.loadings || output.ports?.X_loadings,
          );
          return buildRankedVipPlot({
            scores: rawVip,
            featureLabels: metadata.feature_names || loadingsPayload?.x_axis?.data || metadata.wavenumbers,
            height: 350,
          });
        }
        return prebuilt;
      }
      case "plsda_cm_train":
      case "classification_cm_train":
        return prebuiltPlot(output, "confusion_matrix_train");
      case "plsda_cm_cv":
      case "classification_cm_cv":
        return prebuiltPlot(output, "confusion_matrix_cv");

      // Classification (SIMCA, KNN, or PLS-DA fallback)
      case "classification_scores": {
        // Try pre-built first for PLS-DA
        if (isPLSDA.value && output.plots?.scores?.data) {
          return prebuiltPlot(output, "scores");
        }
        return {
          data: buildScoresTraces(output.data, metadata, xAxis.value, yAxis.value, "Dimension "),
          layout: scoresLayout(metadata, xAxis.value, yAxis.value, "Dimension "),
        };
      }
      // HCA
      case "hca_dendrogram":
        return prebuiltPlot(output, "dendrogram");

      // Peak finding
      case "peak_finding":
        return prebuiltPlot(output, "peak_finding");

      // Compare vs. Library
      case "library_compare":
        return prebuiltPlot(output, "library_compare");

      // Plot/Contour nodes (server-rendered)
      case "plot_visualization": {
        const viz = output.ports?.visualization?.value || metadata;
        return {
          data: viz.data || output.data || [],
          layout: {
            ...BASE_PLOT_LAYOUT,
            ...(viz.layout || {}),
            paper_bgcolor: BASE_PLOT_LAYOUT.paper_bgcolor,
            plot_bgcolor: BASE_PLOT_LAYOUT.plot_bgcolor,
            font: BASE_PLOT_LAYOUT.font,
          },
        };
      }

      // Canonical evaluator / Cross-Validation evaluation
      //
      // Payload shapes:
      //   Multi-target (new): viz.series = [{name, actual, predicted}, ...]
      //   Single-target (legacy): viz.data = number[][] of [actual, predicted] pairs.
      // When real reference property names are present in viz.metadata.target_names
      // (e.g. Moisture/Oil/Protein/Starch), incorporate them into the plot
      // title and y-axis so the plot is self-describing — matches the layout
      // logic used by NodeDetailView.holdoutRegressionLayout.
      case "holdout_regression": {
        const ports = output.ports as Record<string, { value?: unknown }> | undefined;
        const vizObj =
          (ports?.visualization?.value as Record<string, unknown> | undefined) ??
          ((ports?.default?.value as Record<string, unknown> | undefined)?.visualization as
            | Record<string, unknown>
            | undefined);
        if (!vizObj) return { data: [], layout: BASE_PLOT_LAYOUT };

        const vizMeta = (vizObj.metadata as Record<string, unknown> | undefined) ?? {};
        const rawNames = vizMeta.target_names;
        const targetNames = Array.isArray(rawNames)
          ? rawNames.map((n) => String(n)).filter(Boolean)
          : [];
        const hasRealNames = targetNames.length > 0
          && !targetNames.every((n) => /^Target_\d+$/.test(n));

        const series = vizObj.series as
          | Array<{ name?: string; actual?: number[]; predicted?: number[]; train_actual?: number[]; train_predicted?: number[] }>
          | undefined;
        if (Array.isArray(series) && series.length > 0) {
          const traces: Array<Record<string, unknown>> = [];
          const allActual: number[] = [];
          const allPredicted: number[] = [];
          for (const [idx, s] of series.entries()) {
            const sActual = Array.isArray(s.actual) ? s.actual.map(Number) : [];
            const sPredicted = Array.isArray(s.predicted) ? s.predicted.map(Number) : [];
            const trainActual = Array.isArray(s.train_actual) ? s.train_actual.map(Number) : [];
            const trainPredicted = Array.isArray(s.train_predicted) ? s.train_predicted.map(Number) : [];
            const color = CATEGORY_COLORS[idx % CATEGORY_COLORS.length];
            const name = String(s.name || "Target");
            if (trainActual.length && trainPredicted.length) {
              traces.push({
                x: trainActual,
                y: trainPredicted,
                mode: "markers",
                type: "scatter",
                name: `${name} train`,
                marker: { color, size: 7, symbol: "circle-open" },
              });
              allActual.push(...trainActual);
              allPredicted.push(...trainPredicted);
            }
            if (sActual.length && sPredicted.length) {
              traces.push({
                x: sActual,
                y: sPredicted,
                mode: "markers",
                type: "scatter",
                name: `${name} test`,
                marker: { color, size: 8, symbol: "circle" },
              });
              allActual.push(...sActual);
              allPredicted.push(...sPredicted);
            }
          }
          if (traces.length === 0) return { data: [], layout: BASE_PLOT_LAYOUT };
          const minVal = Math.min(...allActual, ...allPredicted);
          const maxVal = Math.max(...allActual, ...allPredicted);
          traces.push({
            x: [minVal, maxVal],
            y: [minVal, maxVal],
            mode: "lines",
            type: "scatter",
            name: "1:1 Line",
            line: { dash: "dash", color: "#94a3b8" },
          });
          const joined = targetNames.join(", ");
          const titleText = hasRealNames
            ? `Predicted vs Actual \u2014 ${joined}`
            : "Predicted vs Actual (per target)";
          const yTitle = hasRealNames ? `Predicted (${joined})` : "Predicted";
          return {
            data: traces,
            layout: {
              ...BASE_PLOT_LAYOUT,
              title: { text: `${titleText}<br><sup>${holdoutSplitSummary(vizObj)}</sup>`, font: { color: "#e2e8f0", size: 14 } },
              margin: { ...BASE_PLOT_LAYOUT.margin, t: 66 },
              xaxis: { title: "Actual", color: "#94a3b8" },
              yaxis: { title: yTitle, color: "#94a3b8" },
              showlegend: true,
            },
          };
        }

        // Legacy single-target path.
        const pairs = (vizObj.data as number[][]) || [];
        if (!pairs.length) return { data: [], layout: BASE_PLOT_LAYOUT };
        const trainPairs = ((vizObj.metadata as Record<string, any> | undefined)?.train?.data as number[][] | undefined) || [];
        const actual = pairs.map((p: number[]) => p[0]);
        const predicted = pairs.map((p: number[]) => p[1]);
        const trainActual = trainPairs.map((p: number[]) => p[0]);
        const trainPredicted = trainPairs.map((p: number[]) => p[1]);
        const minVal = Math.min(...actual, ...predicted, ...trainActual, ...trainPredicted);
        const maxVal = Math.max(...actual, ...predicted, ...trainActual, ...trainPredicted);
        const singleName = hasRealNames ? targetNames[0] : "";
        const titleText = singleName
          ? `Predicted vs Actual \u2014 ${singleName}`
          : "Predicted vs Actual";
        const yTitle = singleName ? `Predicted ${singleName}` : "Predicted";
        const traces = [
          ...(trainPairs.length
            ? [{
                x: trainActual,
                y: trainPredicted,
                mode: "markers",
                type: "scatter",
                name: "Train",
                marker: { color: "#3b82f6", size: 7, symbol: "circle-open" },
              }]
            : []),
          { x: actual, y: predicted, mode: "markers", type: "scatter", name: "Test", marker: { color: "#3b82f6", size: 8, symbol: "circle" } },
          { x: [minVal, maxVal], y: [minVal, maxVal], mode: "lines", type: "scatter", name: "1:1 Line", line: { dash: "dash", color: "#94a3b8" } },
        ];
        return {
          data: traces,
          layout: {
            ...BASE_PLOT_LAYOUT,
            title: { text: `${titleText}<br><sup>${holdoutSplitSummary(vizObj)}</sup>`, font: { color: "#e2e8f0", size: 14 } },
            margin: { ...BASE_PLOT_LAYOUT.margin, t: 66 },
            xaxis: { title: "Actual", color: "#94a3b8" },
            yaxis: { title: yTitle, color: "#94a3b8" },
            showlegend: trainPairs.length > 0,
          },
        };
      }
      case "holdout_confusion": {
        const ports = output.ports as Record<string, { value?: unknown }> | undefined;
        const vizObj =
          (ports?.visualization?.value as Record<string, unknown> | undefined) ??
          ((ports?.default?.value as Record<string, unknown> | undefined)?.visualization as
            | Record<string, unknown>
            | undefined);
        const cm = (vizObj?.data as number[][]) || [];
        if (!cm.length) return { data: [], layout: BASE_PLOT_LAYOUT };
        const vizMetadata = (vizObj?.metadata as Record<string, unknown>) ?? {};
        const labels =
          ((vizMetadata.labels ?? vizMetadata.classes) as string[] | undefined) ||
          cm.map((_: unknown, i: number) => `Class ${i}`);
        // Row-normalized: each row shows the fraction of true-class samples
        // predicted into each class. Diagonal = recall per class.
        const cmNormalized = cm.map((row: number[]) => {
          const total = row.reduce((a: number, b: number) => a + b, 0);
          return total > 0 ? row.map((v: number) => v / total) : row.map(() => 0);
        });
        const textLabels = cm.map((row: number[], i: number) =>
          row.map((v: number, j: number) => {
            const frac = cmNormalized[i][j];
            return `${v}\n${(frac * 100).toFixed(1)}%`;
          })
        );
        return {
          data: [{
            z: cmNormalized, x: labels, y: labels, type: "heatmap", colorscale: "Blues", showscale: true,
            zmin: 0, zmax: 1,
            text: textLabels,
            texttemplate: "%{text}",
            hovertemplate: "True: %{y}<br>Predicted: %{x}<br>Row fraction: %{z:.15g}<extra></extra>",
            colorbar: { title: { text: "Row fraction", font: { color: "#94a3b8" } } },
          }],
          layout: {
            ...BASE_PLOT_LAYOUT,
            title: { text: "Confusion Matrix (normalized by true class)", font: { color: "#e2e8f0", size: 14 } },
            xaxis: { title: "Predicted", color: "#94a3b8" },
            yaxis: { title: "True", color: "#94a3b8", autorange: "reversed" },
          },
        };
      }

      case "holdout_per_class": {
        // Small multiples: one subplot per metric (sensitivity, specificity,
        // precision, F1), each a bar chart over classes.
        const metrics = getHoldoutMetricsDict(output);
        const perClass = getHoldoutPerClassRows(metrics);
        if (!perClass.length) return { data: [], layout: BASE_PLOT_LAYOUT };
        const classNames = perClass.map((e) => String(e.class ?? ""));
        const metricKeys: Array<{ key: string; label: string }> = [
          { key: "sensitivity", label: "Sensitivity" },
          { key: "specificity", label: "Specificity" },
          { key: "precision", label: "Precision" },
          { key: "f1", label: "F1" },
        ];
        const traces = metricKeys.map((m, idx) => ({
          x: classNames,
          y: perClass.map((e) => Number(e[m.key] ?? 0)),
          type: "bar",
          name: m.label,
          xaxis: `x${idx + 1}`,
          yaxis: `y${idx + 1}`,
          marker: { color: ["#3b82f6", "#22c55e", "#f59e0b", "#a855f7"][idx] },
          text: perClass.map((e) => Number(e[m.key] ?? 0).toFixed(3)),
          textposition: "outside",
          hovertemplate: `%{x}: %{y:.15g}<extra>${m.label}</extra>`,
        }));
        return {
          data: traces,
          layout: {
            ...BASE_PLOT_LAYOUT,
            title: { text: "Per-Class Metrics", font: { color: "#e2e8f0", size: 14 } },
            grid: { rows: 2, columns: 2, pattern: "independent" },
            showlegend: false,
            annotations: metricKeys.map((m, idx) => {
              const col = idx % 2;
              const row = Math.floor(idx / 2);
              return {
                text: m.label,
                showarrow: false,
                x: 0.5,
                y: 1.0,
                xref: `x${idx + 1} domain` as const,
                yref: `y${idx + 1} domain` as const,
                yanchor: "bottom" as const,
                font: { color: "#e2e8f0", size: 12 },
                xshift: col * 0,
                yshift: row * 0,
              };
            }),
            xaxis: { color: "#94a3b8", automargin: true },
            xaxis2: { color: "#94a3b8", automargin: true },
            xaxis3: { color: "#94a3b8", automargin: true },
            xaxis4: { color: "#94a3b8", automargin: true },
            yaxis: { color: "#94a3b8", range: [0, 1.1] },
            yaxis2: { color: "#94a3b8", range: [0, 1.1] },
            yaxis3: { color: "#94a3b8", range: [0, 1.1] },
            yaxis4: { color: "#94a3b8", range: [0, 1.1] },
          },
        };
      }

      case "holdout_predictions": {
        // Scatter of individual predictions, indexed by sample.
        // For classification: points colored by predicted class, y-axis is the
        // predicted label, revealing misclassification runs and clusters.
        // For regression: points at their predicted value vs. sample index.
        const ports = output.ports as Record<string, { value?: unknown; data?: unknown }> | undefined;
        const predictionsRaw =
          ports?.predictions?.data ??
          ports?.predictions?.value ??
          [];
        const preds = Array.isArray(predictionsRaw) ? (predictionsRaw as Array<number | string>) : [];
        if (!preds.length) return { data: [], layout: BASE_PLOT_LAYOUT };
        const sampleIndex = preds.map((_, i) => i);
        // Detect classification by checking if values are strings.
        const isCls = typeof preds[0] === "string";
        if (isCls) {
          const classes = Array.from(new Set(preds.map(String)));
          const colors = ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#a855f7", "#06b6d4"];
          const traces = classes.map((cls, idx) => {
            const xs: number[] = [];
            const ys: string[] = [];
            preds.forEach((p, i) => {
              if (String(p) === cls) {
                xs.push(i);
                ys.push(cls);
              }
            });
            return {
              x: xs,
              y: ys,
              mode: "markers" as const,
              type: "scatter" as const,
              name: cls,
              marker: { color: colors[idx % colors.length], size: 8 },
              hovertemplate: `Sample %{x}<br>Predicted: %{y}<extra></extra>`,
            };
          });
          return {
            data: traces,
            layout: {
              ...BASE_PLOT_LAYOUT,
              title: { text: "Predictions by Sample Index", font: { color: "#e2e8f0", size: 14 } },
              xaxis: { title: "Sample Index", color: "#94a3b8" },
              yaxis: { title: "Predicted Class", color: "#94a3b8", type: "category", categoryorder: "array", categoryarray: classes },
              showlegend: true,
            },
          };
        }
        // Regression
        return {
          data: [{
            x: sampleIndex,
            y: preds.map(Number),
            mode: "markers",
            type: "scatter",
            name: "Predictions",
            marker: { color: "#3b82f6", size: 6 },
            hovertemplate: "Sample %{x}<br>Predicted: %{y:.15g}<extra></extra>",
          }],
          layout: {
            ...BASE_PLOT_LAYOUT,
            title: { text: "Predictions by Sample Index", font: { color: "#e2e8f0", size: 14 } },
            xaxis: { title: "Sample Index", color: "#94a3b8" },
            yaxis: { title: "Predicted Value", color: "#94a3b8" },
            showlegend: false,
          },
        };
      }

      case "holdout_residuals": {
        // Regression residuals: residual vs predicted scatter, with a 0-line.
        // Supports both single-target (viz.data = number[][]) and
        // multi-target (viz.series = per-target actual/predicted arrays).
        const ports = output.ports as Record<string, { value?: unknown }> | undefined;
        const vizObj =
          (ports?.visualization?.value as Record<string, unknown> | undefined) ??
          ((ports?.default?.value as Record<string, unknown> | undefined)?.visualization as
            | Record<string, unknown>
            | undefined);
        if (!vizObj) return { data: [], layout: BASE_PLOT_LAYOUT };

        const series = vizObj.series as
          | Array<{ name?: string; actual?: number[]; predicted?: number[] }>
          | undefined;
        if (Array.isArray(series) && series.length > 0) {
          const traces: Array<Record<string, unknown>> = [];
          const allPredicted: number[] = [];
          for (const s of series) {
            const sActual = Array.isArray(s.actual) ? s.actual.map(Number) : [];
            const sPredicted = Array.isArray(s.predicted) ? s.predicted.map(Number) : [];
            if (!sActual.length || !sPredicted.length) continue;
            const sResiduals = sActual.map((a, i) => a - sPredicted[i]);
            traces.push({
              x: sPredicted,
              y: sResiduals,
              mode: "markers",
              type: "scatter",
              name: String(s.name || "Target"),
              hovertemplate:
                `${String(s.name || "")}<br>Predicted: %{x:.15g}<br>Residual: %{y:.15g}<extra></extra>`,
            });
            allPredicted.push(...sPredicted);
          }
          if (traces.length === 0) return { data: [], layout: BASE_PLOT_LAYOUT };
          const minP = Math.min(...allPredicted);
          const maxP = Math.max(...allPredicted);
          traces.push({
            x: [minP, maxP],
            y: [0, 0],
            mode: "lines",
            type: "scatter",
            name: "Zero",
            line: { dash: "dash", color: "#94a3b8" },
            hoverinfo: "skip",
          });
          return {
            data: traces,
            layout: {
              ...BASE_PLOT_LAYOUT,
              title: { text: "Residuals vs Predicted (per target)", font: { color: "#e2e8f0", size: 14 } },
              xaxis: { title: "Predicted", color: "#94a3b8" },
              yaxis: { title: "Residual (true \u2212 predicted)", color: "#94a3b8" },
              showlegend: true,
            },
          };
        }

        // Legacy single-target path.
        const pairs = (vizObj.data as number[][]) || [];
        if (!pairs.length) return { data: [], layout: BASE_PLOT_LAYOUT };
        const predicted = pairs.map((p: number[]) => p[1]);
        const residuals = pairs.map((p: number[]) => p[0] - p[1]);
        const minP = Math.min(...predicted);
        const maxP = Math.max(...predicted);
        return {
          data: [
            {
              x: predicted,
              y: residuals,
              mode: "markers",
              type: "scatter",
              name: "Residuals",
              marker: { color: "#3b82f6", size: 6 },
              hovertemplate: "Predicted: %{x:.15g}<br>Residual: %{y:.15g}<extra></extra>",
            },
            {
              x: [minP, maxP],
              y: [0, 0],
              mode: "lines",
              type: "scatter",
              name: "Zero",
              line: { dash: "dash", color: "#94a3b8" },
              hoverinfo: "skip",
            },
          ],
          layout: {
            ...BASE_PLOT_LAYOUT,
            title: { text: "Residuals vs Predicted", font: { color: "#e2e8f0", size: 14 } },
            xaxis: { title: "Predicted", color: "#94a3b8" },
            yaxis: { title: "Residual (true \u2212 predicted)", color: "#94a3b8" },
            showlegend: false,
          },
        };
      }

      case "holdout_metrics_table": {
        // Plotly table of the metric keys and values from the metrics port.
        const metrics = getHoldoutMetricsDict(output);
        if (!metrics) return { data: [], layout: BASE_PLOT_LAYOUT };
        const taskType = String(metrics.task_type ?? "");
        const displayKeys: Array<{ key: string; legacyKey?: string; label: string }> = taskType === "classification"
          ? [
              { key: "test_accuracy", legacyKey: "accuracy", label: "Accuracy" },
              { key: "test_balanced_accuracy", label: "Balanced Accuracy" },
              { key: "test_f1_macro", label: "F1 Macro" },
              { key: "test_precision_macro", label: "Precision Macro" },
              { key: "test_recall_macro", label: "Recall Macro" },
              { key: "test_sensitivity_macro", label: "Sensitivity Macro" },
              { key: "test_specificity_macro", label: "Specificity Macro" },
              { key: "n_classes", label: "Number of Classes" },
              { key: "n_samples", label: "Number of Samples" },
            ]
          : [
              { key: "rmse_test", legacyKey: "RMSEP", label: "RMSEP" },
              { key: "r2_test", legacyKey: "R2", label: "R²" },
              { key: "mae", legacyKey: "MAE", label: "MAE" },
              { key: "bias", label: "Bias" },
              { key: "sep", legacyKey: "SEP", label: "SEP" },
              { key: "rer", legacyKey: "RER", label: "RER" },
              { key: "n_samples", label: "Number of Samples" },
              { key: "n_valid_samples", label: "Valid Samples" },
              { key: "n_invalid_predictions", label: "Invalid Predictions" },
              { key: "status", label: "Status" },
            ];
        const names: string[] = [];
        const values: string[] = [];
        for (const { key, legacyKey, label } of displayKeys) {
          const v = metrics[key] ?? (legacyKey ? metrics[legacyKey] : undefined);
          if (v === undefined || v === null) continue;
          names.push(label);
          values.push(typeof v === "number" ? formatMetricValue(v) : String(v));
        }
        return {
          data: [{
            type: "table",
            header: {
              values: ["<b>Metric</b>", "<b>Value</b>"],
              align: ["left", "left"],
              fill: { color: "#1e293b" },
              font: { color: "#e2e8f0", size: 13 },
              line: { color: "#334155", width: 1 },
            },
            cells: {
              values: [names, values],
              align: ["left", "left"],
              fill: { color: "#0f172a" },
              font: { color: "#e2e8f0", size: 12 },
              line: { color: "#334155", width: 1 },
              height: 28,
            },
          }],
          layout: {
            ...BASE_PLOT_LAYOUT,
            title: { text: "Evaluation Metrics", font: { color: "#e2e8f0", size: 14 } },
          },
        };
      }

      // Stats
      case "stats_mean_std":
        return { data: buildStatsMeanStdTraces(output), layout: statsMeanStdLayout() };
      case "stats_distribution":
        return { data: buildStatsDistributionTraces(output), layout: statsDistributionLayout() };

      // Data/Preprocess: Spectra overlay
      case "spectra_overlay":
        return buildSpectraOverlayPlot(plotOutput);

      // Data/Preprocess: Heatmap
      case "spectra_heatmap":
        return { data: buildHeatmapTraces(output), layout: heatmapLayout(metadata) };

      // Generic dataset
      case "generic_boxplot":
        return { data: buildBoxPlotTraces(plotOutput), layout: boxPlotLayout(metadata) };
      case "generic_scatter":
        return {
          data: buildFeatureScatterTraces(plotOutput, featureXAxis.value, featureYAxis.value),
          layout: featureScatterLayout(metadata, featureXAxis.value, featureYAxis.value),
        };

      default:
        return { data: [], layout: BASE_PLOT_LAYOUT };
    }
  });

  const plotResult = computed<{data:any[];layout:Record<string,any>}>(() => {
    if (isPreprocessNode.value && ["spectra_overlay", "spectra_heatmap"].includes(selectedPlotKey.value)) {
      return preprocessingComparison(primaryInput.value, retainedNodeOutput.value, selectedPlotKey.value === "spectra_heatmap");
    }
    if (cohort.value.error) return refusedScientificPlot(cohort.value.error, BASE_PLOT_LAYOUT);
    let plot = rawPlotResult.value;
    if (selectedPlotKey.value === "scientific_spectral_heatmap" || selectedPlotKey.value === "spectra_heatmap") {
      const color = matrixColorEncoding(nodeOutput.value?.data, nodeOutput.value?.metadata?.value_semantics);
      if (color.error) return refusedScientificPlot(color.error, BASE_PLOT_LAYOUT);
      plot = {...plot,layout:{...plot.layout,annotations:[...(plot.layout.annotations ?? []),encodingAnnotation(color.notice)],margin:{...plot.layout.margin,t:95}}};
    }
    const population = cohort.value.population;
    if (!population) return plot;
    const overlay = selectedPlotKey.value === "scientific_spectral_overlay";
    const shown = overlay ? Math.min(50, population.total) : population.total;
    const declared = {...population, shown, source_row_indices: population.source_row_indices.slice(0, shown), sample_labels: nodeOutput.value?.metadata?.sample_labels?.slice(0, shown), method: overlay && shown < population.total ? "first_rows" : "all_active"};
    const data = overlay ? plot.data.map((trace:any) => ({...trace,meta:{...trace.meta,source_row_index: population.source_row_indices[trace.meta?.source_row_index]}})) : plot.data;
    return {data,layout:{...plot.layout,meta:{...plot.layout.meta,display_population:declared},
      title:{text:`Active cohort: ${shown} of ${population.total} rows; ${population.excluded} excluded of ${population.available} retained<br><sup>${population.shown_features} of ${population.available_features} features; ${population.excluded_features} excluded</sup>`},
      margin:{...plot.layout.margin,t:85}}};
  });

  const plotData = computed(() => plotResult.value.data);
  const plotLayout = computed(() => plotResult.value.layout);

  // ---- Data shape summary ----

  const dataShape = computed(() => {
    const output = nodeOutput.value;
    if (nodeType.value === "output.data_table" && output?.metadata?.type === "salient_features") {
      return { rows: output.metadata.n_rows, cols: output.metadata.n_cols, range: null,
        rowLabel: output.metadata.method === "peak_finding" ? "consensus groups" : "selected features",
        colLabel: "columns" };
    }
    const defaultRowLabel = isSpectra.value ? "spectra" : "rows";
    const defaultColLabel = isSpectra.value ? "points" : "features";
    const defaultShape = { rows: 0, cols: 0, range: null as [number, number] | null, rowLabel: defaultRowLabel, colLabel: defaultColLabel };
    const evidenceShape = scientificEvidenceShape(output);
    if (evidenceShape) {
      return { ...evidenceShape, range: null };
    }
    if (isProjectedScientificKind(output, "t2_q_diagnostics")) {
      const rows = t2QDiagnosticRows(output.presentation_value, output.metadata || {});
      return {
        rows: rows.length,
        cols: rows.length > 0 ? 2 : 0,
        range: null,
        rowLabel: rows.length === 1 ? "sample" : "samples",
        colLabel: "statistics",
      };
    }
    if (isProjectedScientificKind(output, "confusion_matrix") && Array.isArray(output?.data)) {
      return {
        rows: output.data.length,
        cols: Array.isArray(output.data[0]) ? output.data[0].length : 0,
        range: null,
        rowLabel: "actual-class rows",
        colLabel: "prediction-class columns",
      };
    }
    if (isProjectedScientificKind(output, "classification_responses") && Array.isArray(output?.data)) {
      return {
        rows: output.data.length,
        cols: Array.isArray(output.data[0]) ? output.data[0].length : 0,
        range: null,
        rowLabel: "calibration samples",
        colLabel: "response classes",
      };
    }
    if (isProjectedScientificKind(output, "variable_profile") && Array.isArray(output?.data)) {
      const values = output.data.filter((value: unknown): value is number =>
        typeof value === "number" && Number.isFinite(value),
      );
      return {
        rows: output.data.length,
        cols: 0,
        range: values.length > 0 ? [Math.min(...values), Math.max(...values)] as [number, number] : null,
        rowLabel: "features",
        colLabel: "",
      };
    }
    if (
      isProjectedScientificKind(output, "pca_explained_variance") &&
      Array.isArray(output?.data)
    ) {
      const values = output.data.filter((value: unknown): value is number =>
        typeof value === "number" && Number.isFinite(value),
      );
      return {
        rows: output.data.length,
        cols: 0,
        range: values.length > 0 ? [Math.min(...values), Math.max(...values)] as [number, number] : null,
        rowLabel: "components",
        colLabel: "",
      };
    }
    if (
      isProjectedScientificKind(output, "spectral_dataset") &&
      output?.metadata?.scientific_matrix_role === "component_concentrations" &&
      Array.isArray(output?.data)
    ) {
      const declaredShape =
        output.descriptor?.shape_valid === true && Array.isArray(output.descriptor.shape)
          ? output.descriptor.shape
          : null;
      return {
        rows: declaredShape?.[0] ?? output.data.length,
        cols: declaredShape?.[1] ?? (Array.isArray(output.data[0]) ? output.data[0].length : 0),
        range: null,
        rowLabel: "samples",
        colLabel: "components",
      };
    }
    if (
      isProjectedScientificKind(output, "spectral_dataset") &&
      output?.metadata?.scientific_matrix_role === "component_spectra" &&
      Array.isArray(output?.data)
    ) {
      const declaredShape =
        output.descriptor?.shape_valid === true && Array.isArray(output.descriptor.shape)
          ? output.descriptor.shape
          : null;
      return {
        rows: declaredShape?.[0] ?? output.data.length,
        cols: declaredShape?.[1] ?? (Array.isArray(output.data[0]) ? output.data[0].length : 0),
        range: null,
        rowLabel: "components",
        colLabel: "spectral variables",
      };
    }
    if (
      isProjectedScientificKind(output, "spectral_dataset") &&
      isFeatureRole(output?.metadata || {}) &&
      Array.isArray(output?.data)
    ) {
      return {
        rows: output.data.length,
        cols: Array.isArray(output.data[0]) ? output.data[0].length : 0,
        range: null,
        rowLabel: "samples",
        colLabel: "features",
      };
    }
    if (!output?.data) return defaultShape;

    const data = output.data;
    if (!Array.isArray(data)) return defaultShape;

    const descriptor = output.descriptor;
    const declaredShape =
      descriptor?.shape_valid === true &&
      Array.isArray(descriptor.shape) &&
      descriptor.shape.length > 0 &&
      descriptor.shape.every((size: unknown) => Number.isInteger(size) && Number(size) >= 0)
        ? descriptor.shape.map(Number)
        : null;
    const declaredDimensions = Array.isArray(descriptor?.dimensions) ? descriptor.dimensions : [];

    if (
      !declaredShape &&
      data.length > 0 &&
      data.every((trace: unknown) =>
        !!trace && typeof trace === "object" && !Array.isArray(trace) &&
        (Array.isArray((trace as Record<string, unknown>).x) ||
          Array.isArray((trace as Record<string, unknown>).y) ||
          Array.isArray((trace as Record<string, unknown>).z)),
      )
    ) {
      const traces = data as Array<Record<string, unknown>>;
      const pointCounts = traces.map((trace) => {
        if (Array.isArray(trace.z)) return trace.z.length;
        if (Array.isArray(trace.x)) return trace.x.length;
        return Array.isArray(trace.y) ? trace.y.length : 0;
      });
      const coordinateKeys = traces.map((trace) => JSON.stringify(trace.x ?? trace.y ?? []));
      const shareCoordinates = coordinateKeys.every((value) => value === coordinateKeys[0]);
      const points = shareCoordinates
        ? Math.max(0, ...pointCounts)
        : pointCounts.reduce((total, count) => total + count, 0);
      return {
        rows: traces.length,
        cols: points,
        range: null,
        rowLabel: "series",
        colLabel: points === 1 ? "point" : "points",
      };
    }

    let rowLabel = declaredShape
      ? scientificDimensionLabel(declaredDimensions[0]?.role, defaultRowLabel)
      : defaultRowLabel;
    let colLabel = declaredShape
      ? scientificDimensionLabel(declaredDimensions[1]?.role, defaultColLabel)
      : defaultColLabel;
    if (!declaredShape) {
      if (isMCR.value) { rowLabel = "samples"; colLabel = "components"; }
      else if (isPCA.value) { rowLabel = "observations"; colLabel = "components"; }
      else if (isPLS.value) { rowLabel = "samples"; colLabel = "latent variables"; }
    }

    const metadata = output.metadata || {};
    const rows = declaredShape?.[0] ?? (typeof metadata.n_samples === "number" ? metadata.n_samples : data.length);
    const cols = declaredShape?.[1] ?? (typeof metadata.n_features === "number" ? metadata.n_features : (Array.isArray(data[0]) ? data[0].length : 1));

    let min = Infinity;
    let max = -Infinity;
    for (const row of data) {
      if (Array.isArray(row)) {
        for (const val of row) {
          if (typeof val === "number" && !isNaN(val)) { min = Math.min(min, val); max = Math.max(max, val); }
        }
      } else if (typeof row === "number" && !isNaN(row)) { min = Math.min(min, row); max = Math.max(max, row); }
    }

    return { rows, cols, range: min !== Infinity ? [min, max] as [number, number] : null, rowLabel, colLabel };
  });

  return {
    // Type detection
    isPCA, isMCR, isPLS, isPLSDA, isHCA, isClassification, isGenericDataset,
    isSpectra, hasOutput,

    // Available plots and selection
    availablePlots,
    selectedPlotKey,

    // Interactive state
    xAxis, yAxis,
    featureXAxis, featureYAxis,
    regressionTargetIdx,

    // Axis options
    axisOptions,
    featureAxisOptions,
    regressionTargetOptions,

    // Control visibility
    showAxisControls,
    showFeatureControls,
    showRegressionTargetControl,
    metadataGroupingError: coreMetadataGroupingError,

    // Plot output
    plotData,
    plotLayout,

    // Data shape
    dataShape,
  };
}
