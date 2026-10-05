import { encodingAnnotation, scientificNumber } from "@/utils/scientificEncoding";
/**
 * Renderer-neutral scientific plot projections shared by every workbench
 * surface. Node adapters supply typed scientific values; these builders own
 * the visual grammar so equivalent evidence is presented consistently across
 * model, evaluator, and application nodes.
 */

import { refusedScientificPlot, scientificPlotRefusal } from "@/utils/scientificPlotState";
import { normalizeSampleLabel } from "@/utils/sampleLabels";

// Plotly accepts a broad, renderer-defined payload. Keep scientific inputs
// validated above this boundary while allowing the renderer record itself to
// remain open.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type PlotRecord = Record<string, any>;

export interface ScientificPlot {
  data: PlotRecord[];
  layout: PlotRecord;
}

export function scientificLabelSequence(raw: unknown): unknown[] {
  if (Array.isArray(raw)) return raw;
  if (
    raw && typeof raw === "object" && !Array.isArray(raw)
    && (raw as Record<string, unknown>)._truncated_sequence === true
    && Array.isArray((raw as Record<string, unknown>).preview)
  ) {
    return (raw as Record<string, unknown>).preview as unknown[];
  }
  return [];
}

export function definedScientificMetadata(metadata: unknown): PlotRecord {
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) return {};
  return Object.fromEntries(
    Object.entries(metadata).filter(([, value]) => {
      if (value === null || value === undefined) return false;
      if (typeof value === "string" && value.trim().length === 0) return false;
      if (Array.isArray(value) && value.length === 0) return false;
      return true;
    }),
  );
}

export function scientificPortMetadata(port: unknown): PlotRecord {
  if (!port || typeof port !== "object" || Array.isArray(port)) return {};
  const record = port as PlotRecord;
  const payload = record.value && typeof record.value === "object" && !Array.isArray(record.value)
    ? record.value as PlotRecord
    : record;
  const wrapperMetadata = definedScientificMetadata(record.metadata);
  const payloadMetadata = definedScientificMetadata(payload.metadata);
  const axis = payload.x_axis || payload.feature_axis || {};
  return {
    ...definedScientificMetadata(wrapperMetadata.diagnostics),
    ...wrapperMetadata,
    ...definedScientificMetadata(payloadMetadata.diagnostics),
    ...payloadMetadata,
    ...definedScientificMetadata({
      x_title: axis.title,
      x_units: axis.units,
      x_quantity: axis.quantity,
      x_axis_type: axis.axis_type,
      wavenumbers: axis.data || axis.values,
    }),
  };
}

export function exactScientificFeatureLabels(
  metadata: unknown,
  expectedLength: number,
): string[] | null {
  const labels = definedScientificMetadata(metadata).feature_names;
  if (!Array.isArray(labels) || labels.length !== expectedLength) return null;
  const normalized = labels.map((label) => normalizeSampleLabel(label));
  return normalized.every((label) => label.length > 0) ? normalized : null;
}

export function scientificFeatureCoordinates(metadata: PlotRecord, count: number, payload: PlotRecord = {}): unknown[] | null {
  const axis = payload.x_axis || payload.feature_axis || {};
  const coordinates = axis.data || axis.values || metadata.spectral_wavenumbers || metadata.wavenumbers;
  const role = metadata["sherpa.data_role"] || metadata.data_role || payload.data_role;
  const validCoordinates = Array.isArray(coordinates) && coordinates.length === count;
  if (role !== "X_features" && validCoordinates) return coordinates;
  return exactScientificFeatureLabels(metadata, count) || (validCoordinates ? coordinates : null);
}

export const SCIENTIFIC_PLOT_LAYOUT: PlotRecord = {
  autosize: true,
  paper_bgcolor: "#1e293b",
  plot_bgcolor: "#0f172a",
  font: { color: "#f8fafc", size: 12 },
  margin: { t: 40, r: 20, b: 50, l: 60 },
  xaxis: { gridcolor: "#334155", zerolinecolor: "#475569" },
  yaxis: { gridcolor: "#334155", zerolinecolor: "#475569" },
};

function presentationReadyLayout(layout: PlotRecord, normalizeXAxisTitle = true): PlotRecord {
  const title = layout.title;
  const titleRecord =
    typeof title === "string"
      ? { text: title, x: 0.02, xanchor: "left" }
      : title && typeof title === "object"
        ? { x: 0.02, xanchor: "left", ...title }
        : title;
  const legend =
    layout.legend && typeof layout.legend === "object" ? (layout.legend as PlotRecord) : {};
  const horizontalLegend = legend.orientation === "h";
  const declaredMargin =
    layout.margin && typeof layout.margin === "object" ? (layout.margin as PlotRecord) : {};
  const margin = {
    t: Math.max(Number(declaredMargin.t) || 0, titleRecord ? 58 : 40),
    r: Math.max(Number(declaredMargin.r) || 0, 24),
    b: Math.max(Number(declaredMargin.b) || 0, horizontalLegend ? 124 : 50),
    l: Math.max(Number(declaredMargin.l) || 0, 60),
  };
  const xaxis =
    layout.xaxis && typeof layout.xaxis === "object" ? (layout.xaxis as PlotRecord) : {};
  const xaxisTitle = xaxis.title;

  return {
    ...layout,
    margin,
    ...(titleRecord ? { title: titleRecord } : {}),
    ...(normalizeXAxisTitle
      ? {
          xaxis: {
            ...xaxis,
            ...(typeof xaxisTitle === "string"
              ? { title: { text: xaxisTitle, standoff: 12 } }
              : {}),
          },
        }
      : {}),
    ...(horizontalLegend
      ? {
          legend: {
            x: 0.5,
            xanchor: "center",
            y: -0.46,
            yanchor: "top",
            ...legend,
          },
        }
      : {}),
  };
}

export function numericMatrix(value: unknown): number[][] | null {
  const raw =
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as { data?: unknown }).data
      : value;
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const rows = raw.map((item) => (Array.isArray(item) ? item : [item]));
  if (
    rows.some(
      (row) =>
        row.length === 0 || row.some((item) => typeof item !== "number" || !Number.isFinite(item)),
    )
  ) {
    return null;
  }
  const width = rows[0].length;
  if (rows.some((row) => row.length !== width)) return null;
  return rows as number[][];
}

export function buildComponentConcentrationHeatmap(value: unknown): ScientificPlot {
  const output = value && typeof value === "object" && !Array.isArray(value)
    ? value as PlotRecord
    : {};
  const matrix = numericMatrix(output);
  if (!matrix) return refusedScientificPlot("Component concentrations require a nonempty rectangular finite matrix.", SCIENTIFIC_PLOT_LAYOUT);
  const metadata = definedScientificMetadata(output.metadata);
  const presentation = output.presentation_value
    && typeof output.presentation_value === "object"
    && !Array.isArray(output.presentation_value)
    ? output.presentation_value as PlotRecord
    : output;
  const sampleAxis = presentation.y_axis ?? presentation.sample_axis ?? {};
  const componentAxis = presentation.x_axis ?? presentation.feature_axis ?? {};
  const sampleCount = matrix.length;
  const componentCount = matrix[0].length;
  const componentLabels = scientificLabelSequence(componentAxis.labels ?? metadata.feature_names);
  const sampleLabels = scientificLabelSequence(
    sampleAxis.labels ?? metadata.sample_labels ?? metadata.labels,
  );
  const x = componentLabels.length === componentCount
    ? componentLabels.map(String)
    : Array.from({ length: componentCount }, (_, index) => `Component ${index + 1}`);
  const y = sampleLabels.length === sampleCount
    ? sampleLabels.map(String)
    : Array.from({ length: sampleCount }, (_, index) => index + 1);
  const units = presentation.units || metadata.value_units || "Relative concentration";

  return {
    data: [{
      type: "heatmap",
      z: matrix,
      x,
      y,
      colorscale: "Viridis",
      colorbar: { title: units },
      hovertemplate: `Component: %{x}<br>Sample: %{y}<br>${units}: %{z:.15g}<extra></extra>`,
    }],
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      margin: { ...(SCIENTIFIC_PLOT_LAYOUT.margin as PlotRecord), b: 100, l: 160 },
      xaxis: {
        ...(SCIENTIFIC_PLOT_LAYOUT.xaxis as PlotRecord),
        title: { text: componentAxis.title || "Component", standoff: 20 },
        automargin: true,
      },
      yaxis: {
        ...(SCIENTIFIC_PLOT_LAYOUT.yaxis as PlotRecord),
        title: sampleAxis.title || "Sample",
        automargin: true,
      },
    }, false),
  };
}

export function buildPredictedVsActualPlot(options: {
  actual: unknown;
  predicted: unknown;
  targetIndex?: number;
  targetName?: string;
  r2?: number | null;
  rmse?: number | null;
  height?: number;
}): ScientificPlot {
  const actual = numericMatrix(options.actual);
  const predicted = numericMatrix(options.predicted);
  const targetIndex = options.targetIndex ?? 0;
  if (
    !Number.isInteger(targetIndex) || targetIndex < 0 ||
    !actual ||
    !predicted ||
    actual.length !== predicted.length ||
    actual.some((row) => targetIndex >= row.length) ||
    predicted.some((row) => targetIndex >= row.length)
  ) {
    return refusedScientificPlot("Predicted versus reference requires matching finite rows and a valid target column.", SCIENTIFIC_PLOT_LAYOUT);
  }
  const actualValues = actual.map((row) => row[targetIndex]);
  const predictedValues = predicted.map((row) => row[targetIndex]);
  const values = [...actualValues, ...predictedValues];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.05 || 0.1;

  let title = "Predicted vs Actual";
  if (options.targetName) title += ` — ${options.targetName}`;
  const metrics: string[] = [];
  if (typeof options.r2 === "number" && Number.isFinite(options.r2)) {
    metrics.push(`R² = ${scientificNumber(options.r2, { decimalPlaces: 4 })}`);
  }
  if (typeof options.rmse === "number" && Number.isFinite(options.rmse)) {
    metrics.push(`RMSE = ${scientificNumber(options.rmse, { decimalPlaces: 4 })}`);
  }
  if (metrics.length > 0) {
    title += `<br><span style="font-size:11px;color:#94a3b8">${metrics.join("  |  ")}</span>`;
  }

  return {
    data: [
      {
        type: "scatter",
        mode: "markers",
        x: actualValues,
        y: predictedValues,
        marker: { color: "#3b82f6", size: 7, opacity: 0.7 },
        name: "Samples",
        hovertemplate: "Actual: %{x:.15g}<br>Predicted: %{y:.15g}<extra></extra>",
      },
      {
        type: "scatter",
        mode: "lines",
        x: [min - pad, max + pad],
        y: [min - pad, max + pad],
        line: { color: "#94a3b8", dash: "dash", width: 1.5 },
        name: "1:1 Line",
        showlegend: false,
        hoverinfo: "skip",
      },
    ],
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      annotations: [encodingAnnotation("Point estimates shown; prediction intervals are not displayed.")],
      margin: {...SCIENTIFIC_PLOT_LAYOUT.margin, t:95},
      height: options.height,
      title: { text: title, font: { size: 14, color: "#f8fafc" } },
      xaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.xaxis as PlotRecord), title: "Actual" },
      yaxis: {
        ...(SCIENTIFIC_PLOT_LAYOUT.yaxis as PlotRecord),
        title: "Predicted",
        scaleanchor: "x",
        scaleratio: 1,
      },
      showlegend: false,
    }, false),
  };
}

interface RegressionComparisonRow {
  sample: string;
  target: string;
  reference: number;
  predicted: number;
  residual: number;
  role: string;
}

const regressionComparisonRows = (value: unknown): RegressionComparisonRow[] => {
  const raw =
    value && typeof value === "object" && !Array.isArray(value)
      ? (value as { data?: unknown }).data
      : value;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const row = item as Record<string, unknown>;
    if (
      typeof row.sample !== "string" ||
      typeof row.target !== "string" ||
      typeof row.reference !== "number" ||
      !Number.isFinite(row.reference) ||
      typeof row.predicted !== "number" ||
      !Number.isFinite(row.predicted) ||
      typeof row.residual !== "number" ||
      !Number.isFinite(row.residual) ||
      typeof row.role !== "string"
    )
      return [];
    return [row as unknown as RegressionComparisonRow];
  });
};

export function buildRegressionComparisonPlot(value: unknown): ScientificPlot {
  const rows = regressionComparisonRows(value);
  const retained = value && typeof value === "object" && !Array.isArray(value) ? (value as {data?:unknown}).data : value;
  if (Array.isArray(retained) && rows.length !== retained.length)
    return refusedScientificPlot(`Regression comparison refused: ${retained.length - rows.length} of ${retained.length} records are invalid or missing; no partial-exclusion policy is declared.`, SCIENTIFIC_PLOT_LAYOUT);
  if (rows.length === 0) return refusedScientificPlot("Regression comparison has no valid sample, target, role and finite response rows.", SCIENTIFIC_PLOT_LAYOUT);
  const targets = Array.from(new Set(rows.map((row) => row.target)));
  const roles = Array.from(new Set(rows.map((row) => row.role)));
  // A calibration row must never inherit a held-out claim from the first row.
  const groups = targets.flatMap((target) => roles
    .filter((role) => rows.some((row) => row.target === target && row.role === role))
    .map((role) => ({ target, role })));
  const traces: PlotRecord[] = groups.map(({ target, role }, index) => {
    const selected = rows.filter((row) => row.target === target && row.role === role);
    return {
      type: "scatter",
      mode: "markers",
      x: selected.map((row) => row.reference),
      y: selected.map((row) => row.predicted),
      text: selected.map((row) => row.sample),
      customdata: selected.map((row) => [row.residual, row.role]),
      marker: { size: 8, opacity: 0.75 },
      name: roles.length > 1 ? `${target} · ${role.replace(/_/g, " ")}` : target,
      hovertemplate:
        "Sample %{text}<br>Reference: %{x:.15g}<br>Predicted: %{y:.15g}<br>Residual: %{customdata[0]:.15g}<br>Role: %{customdata[1]}<extra>%{fullData.name}</extra>",
      legendgroup: String(index),
    };
  });
  const values = rows.flatMap((row) => [row.reference, row.predicted]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.05 || 0.1;
  traces.push({
    type: "scatter",
    mode: "lines",
    x: [min - pad, max + pad],
    y: [min - pad, max + pad],
    line: { color: "#94a3b8", dash: "dash", width: 1.5 },
    name: "1:1 Line",
    showlegend: false,
    hoverinfo: "skip",
  });
  const role = roles.length === 1 ? roles[0].replace(/_/g, " ") : "multiple populations";
  const targetContext = targets.length === 1 ? `${targets[0]} · ${role}` : role;
  const axisRange = [min - pad, max + pad];
  const responseLabel = targets.length === 1 ? targets[0] : "Response";
  return {
    data: traces,
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      annotations: [encodingAnnotation("Point estimates shown; prediction intervals are not displayed.")],
      margin: {...SCIENTIFIC_PLOT_LAYOUT.margin, t:95},
      title: {
        text: `Predicted vs Reference — ${targetContext}`,
        font: { size: 14, color: "#f8fafc" },
      },
      xaxis: {
        ...(SCIENTIFIC_PLOT_LAYOUT.xaxis as PlotRecord),
        title: `Reference — ${responseLabel}`,
        range: axisRange,
        constrain: "domain",
      },
      yaxis: {
        ...(SCIENTIFIC_PLOT_LAYOUT.yaxis as PlotRecord),
        title: `Predicted — ${responseLabel}`,
        range: axisRange,
        scaleanchor: "x",
        scaleratio: 1,
        constrain: "domain",
      },
      showlegend: groups.length > 1,
    }, false),
  };
}

export function buildScientificMatrixPlot(options: {
  value: unknown;
  seriesBy: "columns" | "rows";
  xTitle: string;
  yTitle: string;
  seriesPrefix: string;
  pointLabels?: unknown;
  pointHoverLabels?: unknown;
  seriesLabels?: unknown;
  reverseX?: boolean;
}): ScientificPlot {
  const matrix = numericMatrix(options.value);
  if (!matrix) return refusedScientificPlot("Matrix projection requires a nonempty rectangular finite matrix.", SCIENTIFIC_PLOT_LAYOUT);
  const seriesCount = options.seriesBy === "columns" ? matrix[0].length : matrix.length;
  const pointCount = options.seriesBy === "columns" ? matrix.length : matrix[0].length;
  const pointLabels =
    Array.isArray(options.pointLabels) && options.pointLabels.length === pointCount
      ? options.pointLabels
      : Array.from({ length: pointCount }, (_, index) => index + 1);
  const seriesLabels =
    Array.isArray(options.seriesLabels) && options.seriesLabels.length === seriesCount
      ? options.seriesLabels.map(String)
      : Array.from({ length: seriesCount }, (_, index) => `${options.seriesPrefix} ${index + 1}`);
  const pointHoverLabels =
    Array.isArray(options.pointHoverLabels) && options.pointHoverLabels.length === pointCount
      ? options.pointHoverLabels.map(String)
      : null;
  const categoricalPointAxis = pointLabels.some((label) => typeof label === "string");
  const data = Array.from({ length: seriesCount }, (_, seriesIndex) => {
    const seriesLabel = seriesLabels[seriesIndex];
    return {
      type: "scatter",
      mode: "lines+markers",
      x: pointLabels,
      y: options.seriesBy === "columns" ? matrix.map((row) => row[seriesIndex]) : matrix[seriesIndex],
      name: seriesLabel,
      ...(pointHoverLabels ? { customdata: pointHoverLabels } : {}),
      hovertemplate: pointHoverLabels
        ? `%{customdata}<br>%{y:.6g}<extra>${seriesLabel}</extra>`
        : `%{x}<br>%{y:.6g}<extra>${seriesLabel}</extra>`,
    };
  });
  return {
    data,
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      ...(categoricalPointAxis
        ? { margin: { ...(SCIENTIFIC_PLOT_LAYOUT.margin as PlotRecord), t:95, b: 150 } }
        : {}),
      xaxis: {
        ...(SCIENTIFIC_PLOT_LAYOUT.xaxis as PlotRecord),
        title: categoricalPointAxis
          ? { text: options.xTitle, standoff: 24 }
          : options.xTitle,
        ...(categoricalPointAxis ? { automargin: true, tickangle: -45 } : {}),
        ...(options.reverseX ? { autorange: "reversed" } : {}),
      },
      yaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.yaxis as PlotRecord), title: options.yTitle },
      showlegend: seriesCount > 1,
    }, false),
  };
}

export function buildVipPlot(options: {
  scores: unknown;
  featureLabels?: unknown;
  xTitle?: string;
  reverseX?: boolean;
  height?: number;
}): ScientificPlot {
  if (
    !Array.isArray(options.scores) ||
    options.scores.length === 0 ||
    options.scores.some((value) => typeof value !== "number" || !Number.isFinite(value))
  ) {
    return refusedScientificPlot("VIP projection requires a nonempty finite score vector.", SCIENTIFIC_PLOT_LAYOUT);
  }
  const scores = options.scores as number[];
  const labels =
    Array.isArray(options.featureLabels) && options.featureLabels.length === scores.length
      ? options.featureLabels
      : scores.map((_, index) => index + 1);
  const denseProfile = scores.length > 256;
  const categoricalFeatureAxis = labels.some((label) => typeof label === "string");
  return {
    data: [
      denseProfile
        ? {
            type: "scatter",
            mode: "lines",
            x: labels,
            y: scores,
            name: "VIP",
            line: { color: "#3b82f6", width: 1.25 },
            hovertemplate: "%{x}<br>VIP: %{y:.15g}<extra></extra>",
          }
        : {
            type: "bar",
            x: labels,
            y: scores,
            name: "VIP",
            marker: { color: scores.map((value) => (value >= 1 ? "#f59e0b" : "#3b82f6")) },
            hovertemplate: "Feature %{x}<br>VIP: %{y:.15g}<extra></extra>",
          },
    ],
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      annotations: [encodingAnnotation("VIP point estimates; fold-to-fold stability is not displayed.")],
      margin: {...SCIENTIFIC_PLOT_LAYOUT.margin, t:95},
      height: options.height ?? 360,
      ...(categoricalFeatureAxis
        ? { margin: { ...(SCIENTIFIC_PLOT_LAYOUT.margin as PlotRecord), t:95, b: 150 } }
        : {}),
      title: { text: "Variable Importance in Projection", font: { size: 14, color: "#f8fafc" } },
      xaxis: {
        ...(SCIENTIFIC_PLOT_LAYOUT.xaxis as PlotRecord),
        title: categoricalFeatureAxis
          ? { text: options.xTitle || "Feature", standoff: 24 }
          : options.xTitle || "Feature",
        ...(categoricalFeatureAxis ? { automargin: true, tickangle: -45 } : {}),
        autorange: options.reverseX ? "reversed" : true,
      },
      yaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.yaxis as PlotRecord), title: "VIP score" },
      shapes: [
        {
          type: "line",
          xref: "paper",
          x0: 0,
          x1: 1,
          y0: 1,
          y1: 1,
          line: { color: "#94a3b8", dash: "dash", width: 1.5 },
        },
      ],
      showlegend: false,
    }, false),
  };
}

export function buildClassificationResponsesPlot(
  value: unknown,
  metadata: Record<string, unknown> = {},
): ScientificPlot {
  const matrix = numericMatrix(projectedValue(value));
  if (!matrix) return refusedScientificPlot("Classification responses require a nonempty rectangular finite response matrix.", SCIENTIFIC_PLOT_LAYOUT);
  const width = matrix[0].length;
  const rawClasses = metadata.label_categories ?? metadata.classes;
  const classes = Array.isArray(rawClasses) && rawClasses.length === width
    ? rawClasses.map(String)
    : Array.from({ length: width }, (_, index) => `Class ${index + 1}`);
  const rawSamples = metadata.sample_labels;
  const rawActual = metadata.sample_classes;
  const samples = matrix.map((_, index) =>
    Array.isArray(rawSamples) && rawSamples.length === matrix.length
      ? String(rawSamples[index])
      : `Sample ${index + 1}`,
  );
  const actual = matrix.map((_, index) =>
    Array.isArray(rawActual) && rawActual.length === matrix.length
      ? String(rawActual[index])
      : "unlabeled",
  );
  const y = samples.map((_, index) => index + 1);
  return {
    data: [{
      type: "heatmap",
      x: classes,
      y,
      z: matrix,
      colorscale: "RdBu",
      reversescale: true,
      zmid: 0,
      customdata: actual.map((label, index) => classes.map(() => [samples[index], label])),
      hovertemplate:
        "Sample: %{customdata[0]}<br>Index: %{y}<br>Response class: %{x}<br>Known class: %{customdata[1]}<br>Response score: %{z:.15g}<extra></extra>",
      colorbar: { title: "Score" },
    }],
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      margin: { t: 72, r: 70, b: 72, l: 76 },
      title: {
        text: "Calibration Class Responses<br><span style=\"font-size:11px;color:#94a3b8\">PLS dummy-response scores, not probabilities</span>",
        font: { size: 14, color: "#f8fafc" },
      },
      xaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.xaxis as PlotRecord), title: "Response class" },
      yaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.yaxis as PlotRecord), title: "Calibration sample index" },
    }, false),
  };
}

/**
 * Ranked VIP view retained for classifiers and selection readouts where the
 * scientist's question is "which variables rank highest?" rather than
 * "where do all variables lie along the measured feature axis?".  Keeping
 * this as a separate shared profile prevents standardization from erasing the
 * pre-existing Inspector computation (descending rank, capped at 50).
 */
export function buildRankedVipPlot(options: {
  scores: unknown;
  featureLabels?: unknown;
  maxFeatures?: number;
  xAxisTitle?: string;
  reverseXAxis?: boolean;
  height?: number;
}): ScientificPlot {
  if (
    !Array.isArray(options.scores) ||
    options.scores.length === 0 ||
    options.scores.some((value) => typeof value !== "number" || !Number.isFinite(value))
  ) {
    return refusedScientificPlot("Ranked VIP projection requires a nonempty finite score vector.", SCIENTIFIC_PLOT_LAYOUT);
  }
  const scores = options.scores as number[];
  const labels =
    Array.isArray(options.featureLabels) && options.featureLabels.length === scores.length
      ? options.featureLabels
      : scores.map((_, index) => index);
  const maxFeatures = Math.max(1, Math.floor(options.maxFeatures ?? 50));
  const rankedIndices = scores
    .map((_, index) => index)
    .sort((left, right) => scores[right] - scores[left])
    .slice(0, maxFeatures);
  const rankedScores = rankedIndices.map((index) => scores[index]);
  const rankedLabels = rankedIndices.map((index) => labels[index]);

  return {
    data: [
      {
        type: "bar",
        x: rankedLabels,
        y: rankedScores,
        name: "VIP Scores",
        marker: {
          color: rankedScores,
          colorscale: "Viridis",
          showscale: true,
          colorbar: { title: "VIP" },
        },
        hovertemplate: "Feature %{x}<br>VIP: %{y:.15g}<extra></extra>",
      },
    ],
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      annotations: [encodingAnnotation("VIP point estimates; fold-to-fold stability is not displayed.")],
      margin: {...SCIENTIFIC_PLOT_LAYOUT.margin, t:95},
      height: options.height ?? 350,
      xaxis: {
        ...(SCIENTIFIC_PLOT_LAYOUT.xaxis as PlotRecord),
        title: options.xAxisTitle ?? "Feature Index",
        autorange: options.reverseXAxis ? "reversed" : true,
      },
      yaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.yaxis as PlotRecord), title: "VIP Score" },
      shapes: [
        {
          type: "line",
          xref: "paper",
          x0: 0,
          x1: 1,
          y0: 1,
          y1: 1,
          line: { color: "#ef4444", width: 2, dash: "dash" },
        },
      ],
      showlegend: false,
    }, false),
  };
}

export function buildExplainedVariancePlot(options: {
  xVariance: unknown;
  yVariance: unknown;
  height?: number;
}): ScientificPlot {
  if (
    !Array.isArray(options.xVariance) ||
    !Array.isArray(options.yVariance) ||
    options.xVariance.length === 0 ||
    options.xVariance.length !== options.yVariance.length ||
    [...options.xVariance, ...options.yVariance].some(
      (value) => typeof value !== "number" || !Number.isFinite(value),
    )
  ) {
    return refusedScientificPlot("Explained variance requires matching nonempty finite component vectors.", SCIENTIFIC_PLOT_LAYOUT);
  }
  const xVariance = options.xVariance as number[];
  const yVariance = options.yVariance as number[];
  const components = xVariance.map((_, index) => `LV ${index + 1}`);
  return {
    data: [
      { type: "bar", x: components, y: xVariance.map((value) => value * 100), name: "X" },
      { type: "bar", x: components, y: yVariance.map((value) => value * 100), name: "Y" },
    ],
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      height: options.height ?? 360,
      barmode: "group",
      title: {
        text: "Explained Variance by Latent Variable",
        font: { size: 14, color: "#f8fafc" },
      },
      xaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.xaxis as PlotRecord), title: "Latent variable" },
      yaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.yaxis as PlotRecord), title: "Explained variance (%)" },
      showlegend: true,
    }, false),
  };
}

export function buildComponentExplainedVariancePlot(value: unknown): ScientificPlot {
  const matrix = numericMatrix(value);
  if (!matrix || matrix[0].length !== 1) {
    return refusedScientificPlot("Component explained variance requires a nonempty finite single-column vector.", SCIENTIFIC_PLOT_LAYOUT);
  }
  const fractions = matrix.map((row) => row[0]);
  if (fractions.some((fraction) => fraction < 0)) {
    return refusedScientificPlot("Component explained variance cannot contain negative values.", SCIENTIFIC_PLOT_LAYOUT);
  }
  const percentages =
    Math.max(...fractions) <= 1 ? fractions.map((fraction) => fraction * 100) : fractions;
  let cumulative = 0;
  const cumulativePercentages = percentages.map((percentage) => {
    cumulative += percentage;
    return cumulative;
  });
  const components = percentages.map((_, index) => `PC${index + 1}`);
  return {
    data: [
      {
        type: "bar",
        x: components,
        y: percentages,
        name: "Individual variance",
        marker: { color: "#3b82f6" },
        hovertemplate: "%{x}: %{y:.15g}%<extra></extra>",
      },
      {
        type: "scatter",
        mode: "lines+markers",
        x: components,
        y: cumulativePercentages,
        name: "Cumulative variance",
        line: { color: "#f97316", width: 2 },
        marker: { color: "#f97316", size: 7 },
        hovertemplate: "%{x}: %{y:.15g}% cumulative<extra></extra>",
      },
    ],
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      margin: { l: 70 },
      title: {
        text: "PCA Explained Variance",
        font: { size: 14, color: "#f8fafc" },
      },
      xaxis: {
        ...(SCIENTIFIC_PLOT_LAYOUT.xaxis as PlotRecord),
        title: "Principal component",
      },
      yaxis: {
        ...(SCIENTIFIC_PLOT_LAYOUT.yaxis as PlotRecord),
        title: "Explained variance (%)",
        range: [0, Math.max(100, Math.ceil(Math.max(...cumulativePercentages)))],
      },
      showlegend: true,
      legend: { orientation: "h" },
    }),
  };
}

const numericVector = (value: unknown): number[] | null => {
  const matrix = numericMatrix(value);
  if (!matrix || matrix[0].length !== 1) return null;
  return matrix.map((row) => row[0]);
};

const recordValue = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const diagnosticField = (value: Record<string, unknown>, ...keys: string[]): unknown => {
  for (const key of keys) {
    if (key in value) return value[key];
  }
  return undefined;
};

const diagnosticLabels = (value: unknown, count: number): string[] => {
  const compacted = recordValue(value);
  const sequence = Array.isArray(value)
    ? value
    : compacted?._truncated_sequence === true && Array.isArray(compacted.preview)
      ? compacted.preview
      : [];
  const originalLength = Number(compacted?.length);

  return Array.from({ length: count }, (_, index) => {
    const raw = index < sequence.length
      ? sequence[index]
      : index === count - 1 && originalLength === count
        ? compacted?.last
        : undefined;
    const label = raw === null || raw === undefined ? "" : String(raw).trim();
    return label || `Sample ${index + 1}`;
  });
};

export interface T2QDiagnosticRow {
  sample: string;
  t2: number;
  q: number;
  outlier: boolean;
}

export function t2QDiagnosticRows(
  value: unknown,
  metadata: Record<string, unknown> = {},
): T2QDiagnosticRow[] {
  const record = recordValue(value);
  if (!record) return [];
  const t2 = numericVector(diagnosticField(record, "T2", "t2"));
  const q = numericVector(diagnosticField(record, "Q", "q", "spe"));
  if (!t2 || !q || t2.length !== q.length) return [];
  const rawFlags = diagnosticField(record, "flags", "outliers");
  const flags =
    Array.isArray(rawFlags) && rawFlags.length === t2.length
      ? rawFlags.map(Boolean)
      : Array.from({ length: t2.length }, () => false);
  const diagnostics = recordValue(metadata.diagnostics) ?? {};
  const rawLabels = diagnosticField(record, "sample_labels") ?? diagnostics.sample_labels;
  const labels = diagnosticLabels(rawLabels, t2.length);
  return t2.map((t2Value, index) => ({
    sample: labels[index],
    t2: t2Value,
    q: q[index],
    outlier: flags[index],
  }));
}

export function buildT2QDiagnosticsPlot(
  value: unknown,
  metadata: Record<string, unknown> = {},
): ScientificPlot {
  const rows = t2QDiagnosticRows(value, metadata);
  if (rows.length === 0) return refusedScientificPlot("T²/Q diagnostics require matching nonempty finite diagnostic vectors.", SCIENTIFIC_PLOT_LAYOUT);
  const diagnostics = recordValue(metadata.diagnostics) ?? {};
  const t2Limit = Number(
    diagnosticField(metadata, "T2_limit", "t2_limit") ??
      diagnosticField(diagnostics, "T2_limit", "t2_limit"),
  );
  const qLimit = Number(
    diagnosticField(metadata, "Q_limit", "q_limit") ??
      diagnosticField(diagnostics, "Q_limit", "q_limit"),
  );
  const hasT2Limit = Number.isFinite(t2Limit);
  const hasQLimit = Number.isFinite(qLimit);
  const regular = rows.filter((row) => !row.outlier);
  const outliers = rows.filter((row) => row.outlier);
  const trace = (selected: T2QDiagnosticRow[], outlier: boolean): PlotRecord => ({
    type: "scatter",
    mode: "markers",
    x: selected.map((row) => row.t2),
    y: selected.map((row) => row.q),
    text: selected.map((row) => row.sample),
    name: outlier ? "Screened outlier" : "Calibration sample",
    marker: {
      color: outlier ? "#ef4444" : "#3b82f6",
      symbol: outlier ? "diamond" : "circle",
      size: outlier ? 10 : 8,
      opacity: 0.82,
      line: { color: outlier ? "#fecaca" : "#bfdbfe", width: 1 },
    },
    hovertemplate: "%{text}<br>T²: %{x:.4g}<br>Q: %{y:.4g}<extra></extra>",
  });
  const data = [trace(regular, false)];
  if (outliers.length > 0) data.push(trace(outliers, true));
  const shapes: PlotRecord[] = [];
  if (hasT2Limit) {
    shapes.push({
      type: "line",
      x0: t2Limit,
      x1: t2Limit,
      y0: 0,
      y1: 1,
      yref: "paper",
      line: { color: "#f59e0b", dash: "dash", width: 2 },
    });
  }
  if (hasQLimit) {
    shapes.push({
      type: "line",
      x0: 0,
      x1: 1,
      xref: "paper",
      y0: qLimit,
      y1: qLimit,
      line: { color: "#f59e0b", dash: "dash", width: 2 },
    });
  }
  const confidence = Number(diagnostics.confidence_level ?? metadata.confidence_level);
  const subtitle =
    hasT2Limit && hasQLimit
      ? `${Number.isFinite(confidence) ? `${(confidence * 100).toFixed(1)}% ` : ""}screening limits; ${outliers.length} of ${rows.length} flagged`
      : `${rows.length} fitted observations; limits are applied by the outlier-screening node`;
  return {
    data,
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      title: {
        text: `Hotelling T² vs Q Residuals<br><span style="font-size:11px;color:#94a3b8">${subtitle}</span>`,
        font: { size: 14, color: "#f8fafc" },
      },
      xaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.xaxis as PlotRecord), title: "Hotelling T²" },
      yaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.yaxis as PlotRecord), title: "Q residual (SPE)" },
      shapes,
      showlegend: outliers.length > 0,
      hovermode: "closest",
    }, false),
  };
}

const projectedValue = (value: unknown): unknown => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const record = value as Record<string, unknown>;
  return "presentation_value" in record ? record.presentation_value : value;
};

export function buildCategoryCountsPlot(value: unknown): ScientificPlot {
  const raw = projectedValue(value);
  const labels = Array.isArray(raw)
    ? raw.map((item) => (Array.isArray(item) && item.length === 1 ? item[0] : item))
    : [];
  if (labels.length === 0 || labels.some((item) => !["string", "number", "boolean"].includes(typeof item) || (typeof item === "number" && !Number.isFinite(item)))) {
    return refusedScientificPlot("Category counts require nonmissing finite scalar labels.", SCIENTIFIC_PLOT_LAYOUT);
  }
  const counts = new Map<string, number>();
  labels.forEach((label) => {
    const key = String(label);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  });
  return {
    data: [
      {
        type: "bar",
        x: [...counts.keys()],
        y: [...counts.values()],
        marker: { color: "#3b82f6" },
        hovertemplate: "%{x}<br>Samples: %{y}<extra></extra>",
      },
    ],
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      title: { text: "Class Assignment Counts", font: { size: 14, color: "#f8fafc" } },
      xaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.xaxis as PlotRecord), title: "Class" },
      yaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.yaxis as PlotRecord), title: "Samples" },
      showlegend: false,
    }, false),
  };
}

function wrappedCategoryLabel(label: string, maxLineLength = 18): string {
  const words = label.trim().split(/\s+/).filter(Boolean);
  if (words.length < 2) return label;
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (line && candidate.length > maxLineLength) {
      lines.push(line);
      line = word;
    } else {
      line = candidate;
    }
  }
  if (line) lines.push(line);
  return lines.join("<br>");
}

export function buildConfusionMatrixPlot(
  value: unknown,
  metadata: Record<string, unknown> = {},
): ScientificPlot {
  const projected = projectedValue(value);
  const matrix = numericMatrix(projected);
  if (!matrix || matrix.length !== matrix[0].length) {
    return refusedScientificPlot("Confusion matrix requires a nonempty square finite matrix.", SCIENTIFIC_PLOT_LAYOUT);
  }
  const valueMetadata =
    projected && typeof projected === "object" && !Array.isArray(projected)
      ? (projected as { metadata?: Record<string, unknown> }).metadata ?? {}
      : {};
  const rawLabels =
    metadata.label_categories ?? metadata.classes ?? metadata.labels ??
    valueMetadata.label_categories ?? valueMetadata.classes ?? valueMetadata.labels;
  const labels = Array.isArray(rawLabels) && rawLabels.length === matrix.length
    ? rawLabels.map(String)
    : matrix.map((_, index) => `Class ${index + 1}`);
  const displayLabels = labels.map((label) => wrappedCategoryLabel(label));
  const maxDisplayLineLength = Math.max(
    ...displayLabels.flatMap((label) => label.split("<br>").map((line) => line.length)),
  );
  const maxDisplayLines = Math.max(
    ...displayLabels.map((label) => label.split("<br>").length),
  );
  const normalized = matrix.map((row) => {
    const total = row.reduce((sum, item) => sum + item, 0);
    return total > 0 ? row.map((item) => item / total) : row.map(() => 0);
  });
  return {
    data: [
      {
        type: "heatmap",
        x: labels,
        y: labels,
        z: normalized,
        text: matrix.map((row, rowIndex) =>
          row.map(
            (count, columnIndex) =>
              `${count}<br>${(normalized[rowIndex][columnIndex] * 100).toFixed(1)}%`,
          ),
        ),
        texttemplate: "%{text}",
        colorscale: "Blues",
        zmin: 0,
        zmax: 1,
        hovertemplate: "Actual: %{y}<br>Predicted: %{x}<br>Row fraction: %{z:.15g}<extra></extra>",
      },
    ],
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      margin: {
        t: 52,
        r: 24,
        b: Math.min(132, 64 + maxDisplayLines * 14),
        l: Math.min(190, Math.max(90, 38 + maxDisplayLineLength * 6)),
      },
      title: { text: "Confusion Matrix", font: { size: 14, color: "#f8fafc" } },
      xaxis: {
        ...(SCIENTIFIC_PLOT_LAYOUT.xaxis as PlotRecord),
        title: "Predicted class",
        tickmode: "array",
        tickvals: labels,
        ticktext: displayLabels,
        tickangle: 0,
        automargin: true,
      },
      yaxis: {
        ...(SCIENTIFIC_PLOT_LAYOUT.yaxis as PlotRecord),
        title: "Actual class",
        autorange: "reversed",
        tickmode: "array",
        tickvals: labels,
        ticktext: displayLabels,
        automargin: true,
      },
    }, false),
  };
}

const recordRows = (value: unknown): Record<string, unknown>[] => {
  const raw = projectedValue(value);
  const rows =
    raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as { data?: unknown }).data : raw;
  if (!Array.isArray(rows)) return [];
  return rows.filter(
    (row): row is Record<string, unknown> =>
      !!row && typeof row === "object" && !Array.isArray(row),
  );
};

export function buildPeakTablePlot(value: unknown): ScientificPlot {
  const rows = recordRows(value);
  const points = rows.flatMap((row) => {
    // PeakTable/1.0 is the consensus table emitted by analysis.peak_finding.
    // Do not guess alternate field names: a schema change must update the
    // presentation contract and this adapter together.
    const x = row.median_pos;
    const y = row.median_height;
    return typeof x === "number" &&
      Number.isFinite(x) &&
      typeof y === "number" &&
      Number.isFinite(y)
      ? [{ x, y }]
      : [];
  });
  const retained = projectedValue(value);
  const retainedRows = Array.isArray(retained) ? retained : (retained as {data?: unknown})?.data;
  const retainedCount = Array.isArray(retainedRows) ? retainedRows.length : rows.length;
  if (points.length !== retainedCount)
    return refusedScientificPlot(`Peak projection refused: ${retainedCount - points.length} of ${retainedCount} records are invalid or missing; no partial-exclusion policy is declared.`, SCIENTIFIC_PLOT_LAYOUT);
  if (points.length === 0) return refusedScientificPlot("Peak projection has no finite position and height pairs.", SCIENTIFIC_PLOT_LAYOUT);
  return {
    data: [
      {
        type: "scatter",
        mode: "markers",
        x: points.map((point) => point.x),
        y: points.map((point) => point.y),
        marker: { color: "#f59e0b", size: 8 },
        hovertemplate: "Position: %{x}<br>Height: %{y:.6g}<extra></extra>",
      },
    ],
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      title: { text: "Detected Peaks", font: { size: 14, color: "#f8fafc" } },
      xaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.xaxis as PlotRecord), title: "Spectral position" },
      yaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.yaxis as PlotRecord), title: "Peak height" },
      showlegend: false,
    }, false),
  };
}

export function buildSalientFeaturesPlot(value: unknown): ScientificPlot {
  const raw = projectedValue(value);
  const rows =
    raw && typeof raw === "object" && !Array.isArray(raw)
      ? (raw as { features?: unknown }).features
      : null;
  if (!Array.isArray(rows)) return refusedScientificPlot("Salient features require a retained feature list.", SCIENTIFIC_PLOT_LAYOUT);
  const features = rows.flatMap((row, index) => {
    if (!row || typeof row !== "object" || Array.isArray(row)) return [];
    const feature = row as Record<string, unknown>;
    const score = feature.importance;
    const label = feature.position ?? index + 1;
    return typeof score === "number" &&
      Number.isFinite(score) &&
      ((typeof label === "number" && Number.isFinite(label)) || typeof label === "string")
      ? [{ label, score }]
      : [];
  });
  if (features.length !== rows.length)
    return refusedScientificPlot(`Salient feature projection refused: ${rows.length - features.length} of ${rows.length} records are invalid or missing; no partial-exclusion policy is declared.`, SCIENTIFIC_PLOT_LAYOUT);
  if (features.length === 0) return refusedScientificPlot("Salient features have no finite position and importance pairs.", SCIENTIFIC_PLOT_LAYOUT);
  return {
    data: [
      {
        type: "bar",
        x: features.map((feature) => feature.label),
        y: features.map((feature) => feature.score),
        marker: { color: "#8b5cf6" },
        hovertemplate: "Feature %{x}<br>Score: %{y:.6g}<extra></extra>",
      },
    ],
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      title: { text: "Salient Features", font: { size: 14, color: "#f8fafc" } },
      xaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.xaxis as PlotRecord), title: "Feature" },
      yaxis: { ...(SCIENTIFIC_PLOT_LAYOUT.yaxis as PlotRecord), title: "Selection score" },
      showlegend: false,
    }, false),
  };
}

export function buildOutOfFoldEvidencePlot(value: unknown): ScientificPlot {
  const raw = projectedValue(value);
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return refusedScientificPlot("Out-of-fold evidence requires a retained evidence record.", SCIENTIFIC_PLOT_LAYOUT);
  }
  const record = raw as Record<string, unknown>;
  const refuse = (reason: string): ScientificPlot => ({
    data: [],
    layout: {
      ...SCIENTIFIC_PLOT_LAYOUT,
      title: { text: `Out-of-fold evidence unavailable: ${reason}` },
      meta: { refusal_reason: reason },
    },
  });
  const producer = record.producer as Record<string, unknown> | undefined;
  const digest = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  if (
    record.schema_version !== "spectrasherpa-out-of-fold-evidence/1" ||
    record.task_type !== "regression" ||
    producer?.operation_id !== "selection.nested_cv" ||
    producer.implementation_id !== "spectrasherpa.selection.nested_cv" ||
    typeof producer.node_id !== "string" ||
    !producer.node_id.trim() ||
    !digest(producer.execution_contract_digest) ||
    !digest(record.evidence_sha256) ||
    !digest(record.split_plan_digest)
  ) {
    return refuse("missing or incompatible schema, producer or receipt identity");
  }
  const finiteVector = (value: unknown): value is number[] => Array.isArray(value) && value.length > 0 && value.every(item => typeof item === "number" && Number.isFinite(item));
  if (!finiteVector(record.observations) || !finiteVector(record.predictions) || record.observations.length !== record.predictions.length) {
    return refuse("observations and predictions must be aligned finite one-dimensional vectors");
  }
  const plot = buildPredictedVsActualPlot({
    actual: record.observations,
    predicted: record.predictions,
  });
  if (!plot.data.length)
    return refuse("observations and predictions must be aligned finite values");
  const folds = record.fold_assignments;
  const count = Array.isArray(record.observations) ? record.observations.length : 0;
  if (
    !Array.isArray(folds) ||
    folds.length !== count ||
    !folds.every((fold) => Number.isInteger(fold) && fold >= 0)
  ) {
    return refuse("missing or misaligned fold assignments");
  }
  const plan = record.split_plan as Record<string, any> | undefined;
  const indexVector = (value: unknown): value is number[] =>
    Array.isArray(value) &&
    value.length > 0 &&
    value.every((index) => Number.isInteger(index) && index >= 0 && index < count) &&
    new Set(value).size === value.length;
  if (
    plan?.schema_version !== "spectra-split-plan/1" ||
    plan.n_samples !== count ||
    plan.grouped !== false ||
    plan.method !== "kfold" ||
    !Array.isArray(plan.folds) ||
    plan.folds.length < 2
  ) {
    return refuse("missing or incompatible split plan");
  }
  const assigned = new Set<number>();
  for (const [foldIndex, fold] of plan.folds.entries()) {
    if (
      !indexVector(fold?.train) ||
      !indexVector(fold?.test) ||
      fold.train.some((index: number) => fold.test.includes(index)) ||
      fold.train.length + fold.test.length !== count
    ) {
      return refuse("split plan contains missing, duplicate or overlapping train/test indices");
    }
    for (const index of fold.test) {
      if (assigned.has(index) || folds[index] !== foldIndex)
        return refuse("fold assignments do not match the retained split plan");
      assigned.add(index);
    }
  }
  if (assigned.size !== count)
    return refuse("split plan does not hold out every plotted observation exactly once");
  plot.data[0] = {
    ...plot.data[0],
    customdata: folds.map((fold, index) => [index, fold]),
    hovertemplate:
      "Retained row (0-based): %{customdata[0]}<br>Validation fold (0-based): %{customdata[1]}<br>Actual: %{x:.15g}<br>OOF prediction: %{y:.15g}<extra></extra>",
  };
  const producerLabel = producer.node_id.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  plot.layout = {
    ...plot.layout,
    title: { text: `Out-of-fold Predicted vs Actual (${count} held-out predictions)<br><sup>${plan.folds.length} validation folds · selection.nested_cv / ${producerLabel}</sup>` },
    margin: { ...(plot.layout.margin as PlotRecord), t: 85 },
    meta: {
      claim_scope: "out_of_fold",
      producer: record.producer,
      evidence_sha256: record.evidence_sha256,
      split_plan_digest: record.split_plan_digest,
      fold_assignments: folds,
      integrity_verification: "retained_receipt_not_reverified_in_renderer",
    },
  };
  return plot;
}

export function buildDeclaredVisualizationPlot(value: unknown, plotKey?: string): ScientificPlot {
  const raw = projectedValue(value);
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return refusedScientificPlot("Declared visualization requires a retained visualization record.", SCIENTIFIC_PLOT_LAYOUT);
  }
  const record = raw as Record<string, unknown>;
  const selected = plotKey ? record[plotKey] : record;
  if (!selected || typeof selected !== "object" || Array.isArray(selected)) {
    return refusedScientificPlot("The selected declared visualization is unavailable.", SCIENTIFIC_PLOT_LAYOUT);
  }
  const plot = selected as Record<string, unknown>;
  if (!Array.isArray(plot.data)) return refusedScientificPlot("Declared visualization requires a retained trace array.", SCIENTIFIC_PLOT_LAYOUT);
  const declaredLayout =
    plot.layout && typeof plot.layout === "object" ? (plot.layout as PlotRecord) : {};
  if (plot.data.length === 0) {
    return refusedScientificPlot(scientificPlotRefusal(declaredLayout) ?? "Declared visualization has no retained traces.", { ...SCIENTIFIC_PLOT_LAYOUT, ...declaredLayout });
  }
  return {
    data: plot.data as PlotRecord[],
    layout: presentationReadyLayout({
      ...SCIENTIFIC_PLOT_LAYOUT,
      ...declaredLayout,
      paper_bgcolor: SCIENTIFIC_PLOT_LAYOUT.paper_bgcolor,
      plot_bgcolor: SCIENTIFIC_PLOT_LAYOUT.plot_bgcolor,
      font: SCIENTIFIC_PLOT_LAYOUT.font,
    }),
  };
}
