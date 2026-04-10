/* eslint-disable @typescript-eslint/no-explicit-any -- plot payloads from backend nodes are intentionally heterogeneous in this translation layer. */
/**
 * usePlotData — shared composable for building Plotly plots from node output.
 *
 * Used by both QuickPlotModal (single-plot view) and NodeDetailView (multi-plot view).
 * All plot trace/layout building lives here so there is exactly one implementation.
 */
import { ref, computed, watch, type Ref, type ComputedRef } from "vue";
import { createCategoryColorMap } from "@/utils/colors";
import { getYAxisLabel } from "@/utils/plotLabels";
import {
  normalizeSampleLabel,
} from "@/utils/sampleLabels";

// ============================================================================
// Constants
// ============================================================================

export const BASE_PLOT_LAYOUT: Record<string, any> = {
  autosize: true,
  paper_bgcolor: "#1e293b",
  plot_bgcolor: "#0f172a",
  font: { color: "#f8fafc", size: 12 },
  margin: { t: 40, r: 20, b: 50, l: 60 },
  xaxis: { gridcolor: "#334155", zerolinecolor: "#475569" },
  yaxis: { gridcolor: "#334155", zerolinecolor: "#475569" },
};

export const PLOT_CONFIG = {
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ["lasso2d", "select2d"],
  displaylogo: false,
};

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

// ============================================================================
// Label helpers
// ============================================================================

function getLabelArray(raw: unknown, fallbackCount: number, prefix = "Sample"): string[] {
  if (Array.isArray(raw) && raw.length > 0) {
    return raw.map((item, idx) => {
      const n = normalizeSampleLabel(item);
      return n.length > 0 ? n : `${prefix} ${idx + 1}`;
    });
  }
  return Array.from({ length: fallbackCount }, (_, i) => `${prefix} ${i + 1}`);
}

function getCategoryArray(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const normalized = raw
    .map((item) => normalizeSampleLabel(item))
    .filter((item) => item.length > 0);
  return Array.from(new Set(normalized));
}

function resolvePortPayload(port: any): any {
  if (!port || typeof port !== "object") return port;
  return "value" in port ? port.value : port;
}

// ============================================================================
// Axis helpers
// ============================================================================

function resolveXValues(
  metadata: any,
  expectedLength: number,
  portPayload?: any,
): any[] | null {
  const featureNames = metadata.feature_names;
  if (featureNames && featureNames.length === expectedLength) return featureNames;
  const wn = portPayload?.x_axis?.data || metadata.spectral_wavenumbers || metadata.wavenumbers;
  if (wn && Array.isArray(wn) && wn.length === expectedLength) return wn;
  return null;
}

function shouldReverseX(metadata: any, portPayload?: any): boolean {
  const portTitle = portPayload?.x_axis?.title;
  if (portTitle) return portTitle.toLowerCase().includes("wavenumber");
  const xTitle = (metadata.x_title || "").toLowerCase();
  const xUnits = (metadata.x_units || "").toLowerCase();
  return xUnits.includes("cm") || xTitle.includes("wavenumber") || xTitle.includes("raman");
}

function xAxisLabel(metadata: any, portPayload?: any): string {
  const portTitle = portPayload?.x_axis?.title;
  const portUnits = portPayload?.x_axis?.units;
  if (portTitle) return portUnits ? `${portTitle} (${portUnits})` : portTitle;
  const xTitle = metadata.x_title || "Feature";
  const xUnits = metadata.x_units || "";
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
  const labelCategories = getCategoryArray(metadata.label_categories);
  const useCategorical = labelCategories.length > 1 && labelCategories.length < 50
    && labelCategories.length < sampleLabels.length;

  const xLabel = pcLabels[xAxis] || `${componentPrefix}${xAxis + 1}`;
  const yLabel = pcLabels[yAxis] || `${componentPrefix}${yAxis + 1}`;
  const hoverSuffix = `<br>${xLabel}: %{x:.3f}<br>${yLabel}: %{y:.3f}<extra></extra>`;

  if (useCategorical) {
    const colorMap = createCategoryColorMap(sampleLabels, labelCategories);
    const groups = new Map<string | number, { x: number[]; y: number[]; labels: string[] }>();
    labelCategories.forEach((cat) => groups.set(cat, { x: [], y: [], labels: [] }));

    scores.forEach((row, idx) => {
      const cat = sampleLabels[idx];
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
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: pcLabels[xAxis] || `${componentPrefix}${xAxis + 1}` },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: pcLabels[yAxis] || `${componentPrefix}${yAxis + 1}` },
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
  return {
    ...BASE_PLOT_LAYOUT,
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
    xaxis: {
      ...BASE_PLOT_LAYOUT.xaxis,
      title: xAxisLabel(metadata, portPayload),
      autorange: shouldReverseX(metadata, portPayload) ? "reversed" : true,
    },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: "Loading" },
  };
}

// ============================================================================
// Scree plot builder
// ============================================================================

function buildScreeTraces(metadata: any): any[] {
  const variance = metadata.explained_variance_ratio || [];
  if (!variance.length) return [];

  const maxVal = Math.max(...variance);
  const isPercentage = maxVal > 1;
  const variancePercent = isPercentage ? variance : variance.map((v: number) => v * 100);
  const xLabels = Array.from({ length: variance.length }, (_, i) => `PC${i + 1}`);

  let cumulative = 0;
  const cumulativeY = variancePercent.map((v: number) => {
    cumulative += v;
    return cumulative;
  });

  return [
    {
      type: "bar",
      x: xLabels,
      y: variancePercent,
      name: "Individual %",
      marker: { color: "#3b82f6" },
      hovertemplate: "%{x}: %{y:.1f}%<extra></extra>",
    },
    {
      type: "scatter",
      mode: "lines+markers",
      x: xLabels,
      y: cumulativeY,
      name: "Cumulative %",
      line: { color: "#f97316", width: 3 },
      marker: { size: 10, color: "#f97316" },
      hovertemplate: "%{x}: %{y:.1f}% cumulative<extra></extra>",
    },
  ];
}

function screeLayout(): Record<string, any> {
  return {
    ...BASE_PLOT_LAYOUT,
    showlegend: true,
    legend: {
      x: 0.5, xanchor: "center", y: 1.15, orientation: "h",
      bgcolor: "rgba(0,0,0,0)", font: { color: "#f8fafc" },
    },
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: { text: "Principal Component", font: { color: "#f8fafc" } } },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: { text: "Variance (%)", font: { color: "#f8fafc" } }, rangemode: "tozero", range: [0, 105] },
  };
}

// ============================================================================
// Diagnostics plot builder (T² + SPE)
// ============================================================================

function buildDiagnosticsTraces(metadata: any, sampleLabelsOverride?: string[]): any[] {
  const t2 = Array.isArray(metadata.t2) ? metadata.t2 : [];
  const spe = Array.isArray(metadata.spe) ? metadata.spe : [];
  const nSamples = Math.max(t2.length, spe.length);
  if (nSamples === 0) return [];

  const sampleLabels = sampleLabelsOverride || getLabelArray(metadata.sample_labels, nSamples, "Sample");
  const labelCategories = getCategoryArray(metadata.label_categories);
  const useCategorical = labelCategories.length > 1 && labelCategories.length < 50
    && labelCategories.length < sampleLabels.length;
  const x = Array.from({ length: nSamples }, (_, i) => i + 1);
  const traces: any[] = [];

  if (useCategorical) {
    const colorMap = createCategoryColorMap(sampleLabels, labelCategories);
    const groups = new Map<string | number, { indices: number[]; t2: number[]; spe: number[]; labels: string[] }>();
    labelCategories.forEach((cat) => groups.set(cat, { indices: [], t2: [], spe: [], labels: [] }));

    x.forEach((idx, i) => {
      const cat = sampleLabels[i];
      const g = groups.get(cat);
      if (g) {
        g.indices.push(idx);
        if (t2.length > i) g.t2.push(t2[i]);
        if (spe.length > i) g.spe.push(spe[i]);
        g.labels.push(String(sampleLabels[i]));
      }
    });

    if (t2.length > 0) {
      labelCategories.forEach((cat) => {
        const g = groups.get(cat);
        if (g && g.t2.length > 0) {
          traces.push({
            type: "scatter", mode: "markers",
            x: g.indices, y: g.t2,
            name: `T²: ${String(cat)}`, text: g.labels,
            marker: { size: 8, color: colorMap.get(cat), symbol: "circle" },
            hovertemplate: "%{text}<br>T²: %{y:.4f}<extra></extra>",
            legendgroup: String(cat),
          });
        }
      });
      if (typeof metadata.t2_p95 === "number") {
        traces.push({
          type: "scatter", mode: "lines",
          x: [x[0], x[x.length - 1]], y: [metadata.t2_p95, metadata.t2_p95],
          name: "T² Limit (95%)",
          line: { color: "#64748b", dash: "dash", width: 2 },
          showlegend: true, hoverinfo: "skip", legendgroup: "limits",
        });
      }
    }

    if (spe.length > 0) {
      labelCategories.forEach((cat) => {
        const g = groups.get(cat);
        if (g && g.spe.length > 0) {
          traces.push({
            type: "scatter", mode: "markers",
            x: g.indices, y: g.spe,
            name: `SPE: ${String(cat)}`, text: g.labels,
            yaxis: "y2",
            marker: { size: 8, color: colorMap.get(cat), symbol: "square" },
            hovertemplate: "%{text}<br>SPE: %{y:.6f}<extra></extra>",
            legendgroup: String(cat),
          });
        }
      });
      if (typeof metadata.spe_p95 === "number") {
        traces.push({
          type: "scatter", mode: "lines",
          x: [x[0], x[x.length - 1]], y: [metadata.spe_p95, metadata.spe_p95],
          name: "SPE Limit (95%)", yaxis: "y2",
          line: { color: "#64748b", dash: "dash", width: 2 },
          showlegend: true, hoverinfo: "skip", legendgroup: "limits",
        });
      }
    }
  } else {
    if (t2.length > 0) {
      traces.push({
        type: "scatter", mode: "markers",
        x, y: t2, name: "Hotelling T²", text: sampleLabels,
        marker: { size: 8, color: "#3b82f6", symbol: "circle" },
        hovertemplate: "%{text}<br>T²: %{y:.4f}<extra></extra>",
      });
      if (typeof metadata.t2_p95 === "number") {
        traces.push({
          type: "scatter", mode: "lines",
          x: [x[0], x[x.length - 1]], y: [metadata.t2_p95, metadata.t2_p95],
          name: "T² Limit (95%)",
          line: { color: "#3b82f6", dash: "dash", width: 2 },
          showlegend: true, hoverinfo: "skip",
        });
      }
    }
    if (spe.length > 0) {
      traces.push({
        type: "scatter", mode: "markers",
        x, y: spe, name: "SPE (Q)", text: sampleLabels,
        yaxis: "y2",
        marker: { size: 8, color: "#ef4444", symbol: "square" },
        hovertemplate: "%{text}<br>SPE: %{y:.6f}<extra></extra>",
      });
      if (typeof metadata.spe_p95 === "number") {
        traces.push({
          type: "scatter", mode: "lines",
          x: [x[0], x[x.length - 1]], y: [metadata.spe_p95, metadata.spe_p95],
          name: "SPE Limit (95%)", yaxis: "y2",
          line: { color: "#ef4444", dash: "dash", width: 2 },
          showlegend: true, hoverinfo: "skip",
        });
      }
    }
  }
  return traces;
}

function diagnosticsLayout(): Record<string, any> {
  return {
    ...BASE_PLOT_LAYOUT,
    margin: { t: 40, r: 80, b: 50, l: 60 },
    showlegend: true,
    legend: {
      x: 0.5, xanchor: "center", y: 1.15, orientation: "h",
      bgcolor: "rgba(0,0,0,0)", font: { color: "#f8fafc" },
    },
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: "Sample" },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: "T²" },
    yaxis2: {
      overlaying: "y", side: "right",
      title: { text: "SPE (Q)", standoff: 20 },
      gridcolor: "rgba(0,0,0,0)", zerolinecolor: "#475569",
    },
  };
}

// ============================================================================
// Biplot builder
// ============================================================================

function buildBiplotTraces(
  scores: number[][],
  loadings: number[][],
  metadata: any,
  xAxis: number,
  yAxis: number,
): any[] {
  if (!scores || !scores.length) return [];
  if (!loadings || !loadings.length) {
    // Fallback to plain scores plot
    return buildScoresTraces(scores, metadata, xAxis, yAxis, "PC");
  }

  const pcLabels = metadata.pc_labels || [];
  const sampleLabels = getLabelArray(metadata.sample_labels, scores.length, "Sample");
  const labelCategories = getCategoryArray(metadata.label_categories);
  const useCategorical = labelCategories.length > 1 && labelCategories.length < 50
    && labelCategories.length < sampleLabels.length;

  const maxPcIdx = loadings.length - 1;
  const pcX = Math.max(0, Math.min(xAxis, maxPcIdx));
  const pcY = Math.max(0, Math.min(yAxis, maxPcIdx));
  const loadingXRaw = Array.isArray(loadings[pcX]) ? loadings[pcX] : [];
  const loadingYRaw = Array.isArray(loadings[pcY]) ? loadings[pcY] : [];
  if (!loadingXRaw.length || !loadingYRaw.length) {
    return buildScoresTraces(scores, metadata, xAxis, yAxis, "PC");
  }

  const nFeatures = Math.min(loadingXRaw.length, loadingYRaw.length);
  const pcXLabel = pcLabels[pcX] || `PC${pcX + 1}`;
  const pcYLabel = pcLabels[pcY] || `PC${pcY + 1}`;
  const hoverSuffix = `<br>${pcXLabel}: %{x:.3f}<br>${pcYLabel}: %{y:.3f}<extra></extra>`;

  // Build sample traces
  const sampleTraces: any[] = [];
  if (useCategorical) {
    const colorMap = createCategoryColorMap(sampleLabels, labelCategories);
    const groups = new Map<string | number, { x: number[]; y: number[]; labels: string[] }>();
    labelCategories.forEach((cat) => groups.set(cat, { x: [], y: [], labels: [] }));
    scores.forEach((row, idx) => {
      const cat = sampleLabels[idx];
      const g = groups.get(cat);
      if (g && Array.isArray(row) && row.length > Math.max(pcX, pcY)) {
        g.x.push(Number(row[pcX]));
        g.y.push(Number(row[pcY]));
        g.labels.push(String(sampleLabels[idx]));
      }
    });
    labelCategories.forEach((cat) => {
      const g = groups.get(cat);
      if (!g || g.x.length === 0) return;
      sampleTraces.push({
        type: "scatter", mode: "markers",
        x: g.x, y: g.y, text: g.labels,
        name: String(cat),
        marker: { size: 9, color: colorMap.get(cat), opacity: 0.78, line: { width: 1, color: "rgba(15,23,42,0.55)" } },
        hovertemplate: `%{text}${hoverSuffix}`,
      });
    });
  } else {
    const pts = scores
      .map((row, idx) => ({ x: Number(row?.[pcX]), y: Number(row?.[pcY]), label: sampleLabels[idx] }))
      .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
    sampleTraces.push({
      type: "scatter", mode: "markers",
      x: pts.map((p) => p.x), y: pts.map((p) => p.y), text: pts.map((p) => p.label),
      name: "Samples",
      marker: { size: 9, color: "#60a5fa", opacity: 0.8, line: { width: 1, color: "#1d4ed8" } },
      hovertemplate: `%{text}${hoverSuffix}`,
    });
  }

  // Build feature labels
  const featureNames = metadata.feature_names;
  const wavenumbers = metadata.wavenumbers;
  const featureLabels = Array.from({ length: nFeatures }, (_, idx) => {
    if (Array.isArray(featureNames) && featureNames.length === nFeatures) return String(featureNames[idx]);
    if (Array.isArray(wavenumbers) && wavenumbers.length === nFeatures) {
      const w = Number(wavenumbers[idx]);
      return Number.isFinite(w) ? `${w.toFixed(0)}` : String(wavenumbers[idx]);
    }
    return `F${idx + 1}`;
  });

  // Select strongest vectors
  const vectors = Array.from({ length: nFeatures }, (_, idx) => {
    const lx = Number(loadingXRaw[idx]);
    const ly = Number(loadingYRaw[idx]);
    return { idx, lx, ly, label: featureLabels[idx], norm: Math.hypot(lx, ly) };
  }).filter((r) => Number.isFinite(r.lx) && Number.isFinite(r.ly));

  if (vectors.length === 0) return sampleTraces;

  vectors.sort((a, b) => b.norm - a.norm);
  const maxVectors = Math.min(80, vectors.length);
  const selected = vectors.slice(0, maxVectors);
  const labeledCount = Math.min(24, selected.length);
  const labeledSet = new Set(selected.slice(0, labeledCount).map((r) => r.idx));

  // Scale loading vectors to score space
  const scoreXVals = scores.map((r) => Number(r?.[pcX])).filter(Number.isFinite);
  const scoreYVals = scores.map((r) => Number(r?.[pcY])).filter(Number.isFinite);
  const maxSX = Math.max(1e-12, ...scoreXVals.map(Math.abs));
  const maxSY = Math.max(1e-12, ...scoreYVals.map(Math.abs));
  const maxLX = Math.max(1e-12, ...selected.map((r) => Math.abs(r.lx)));
  const maxLY = Math.max(1e-12, ...selected.map((r) => Math.abs(r.ly)));
  const scale = 0.82 * Math.min(maxSX / maxLX, maxSY / maxLY);

  const lineX: Array<number | null> = [];
  const lineY: Array<number | null> = [];
  const endX: number[] = [];
  const endY: number[] = [];
  const textArr: string[] = [];
  const customdata: Array<[string, number, number, number]> = [];

  selected.forEach((r) => {
    const sx = r.lx * scale;
    const sy = r.ly * scale;
    lineX.push(0, sx, null);
    lineY.push(0, sy, null);
    endX.push(sx);
    endY.push(sy);
    textArr.push(labeledSet.has(r.idx) ? r.label : "");
    customdata.push([r.label, r.lx, r.ly, r.norm]);
  });

  const lineTrace = {
    type: "scatter", mode: "lines",
    x: lineX, y: lineY, name: "Loadings vectors",
    line: { color: "#f59e0b", width: 1.6 },
    hoverinfo: "skip", showlegend: true,
  };

  const markerTrace = {
    type: "scatter", mode: "markers+text",
    x: endX, y: endY, text: textArr,
    textposition: "top center",
    textfont: { size: 10, color: "#fde68a" },
    customdata,
    marker: { size: 6, color: "#f97316", opacity: 0.92, line: { width: 1, color: "#7c2d12" } },
    name: "Variables", showlegend: false,
    hovertemplate:
      `<b>%{customdata[0]}</b><br>${pcXLabel} loading: %{customdata[1]:.3f}` +
      `<br>${pcYLabel} loading: %{customdata[2]:.3f}` +
      `<br>Vector norm: %{customdata[3]:.3f}<extra></extra>`,
  };

  return [...sampleTraces, lineTrace, markerTrace];
}

function biplotLayout(metadata: any, xAxis: number, yAxis: number): Record<string, any> {
  const pcLabels = metadata.pc_labels || [];
  const pcXLabel = pcLabels[xAxis] || `PC${xAxis + 1}`;
  const pcYLabel = pcLabels[yAxis] || `PC${yAxis + 1}`;
  const labelCategories = getCategoryArray(metadata.label_categories);
  const hasCat = labelCategories.length > 1 && labelCategories.length < 50;

  return {
    ...BASE_PLOT_LAYOUT,
    showlegend: true,
    legend: {
      bgcolor: "rgba(30,41,59,0.82)", bordercolor: "#334155", borderwidth: 1,
      x: 1, y: 1, xanchor: "right", yanchor: "top",
      orientation: hasCat ? "v" : "h",
    },
    xaxis: {
      ...BASE_PLOT_LAYOUT.xaxis,
      title: `${pcXLabel} (scores)`,
      zeroline: true, zerolinecolor: "#64748b", zerolinewidth: 1.2,
    },
    yaxis: {
      ...BASE_PLOT_LAYOUT.yaxis,
      title: `${pcYLabel} (scores)`,
      zeroline: true, zerolinecolor: "#64748b", zerolinewidth: 1.2,
    },
    annotations: [{
      xref: "paper", yref: "paper", x: 0, y: 1.08, showarrow: false,
      text: "Loading vectors are scaled to score-space for interpretation.",
      font: { size: 11, color: "#cbd5e1" },
    }],
    hovermode: "closest",
  };
}

// ============================================================================
// MCR-ALS / Decomposition builders
// ============================================================================

function buildMCRConcentrationTraces(output: any): any[] {
  const data = output.data;
  const metadata = output.metadata || {};
  if (!data || !data.length || !Array.isArray(data[0])) return [];

  const nComponents = data[0].length;
  const xRaw = metadata.x_axis;
  const x = (Array.isArray(xRaw) && xRaw.length === data.length) ? xRaw : Array.from({ length: data.length }, (_, i) => i);
  const labels = Array.isArray(metadata.labels)
    ? metadata.labels.map((item: any) => normalizeSampleLabel(item)).filter((s: string) => s.length > 0)
    : [];
  const sampleLabels = getLabelArray(metadata.sample_labels, data.length, "Sample");

  return Array.from({ length: nComponents }, (_, comp) => ({
    type: "scatter",
    mode: "lines+markers",
    x,
    y: data.map((row: number[]) => row[comp]),
    name: labels[comp] || `Component ${comp + 1}`,
    line: { width: 2 },
    marker: { size: 6 },
    text: sampleLabels,
    hovertemplate: "%{text}<br>X: %{x}<br>Y: %{y:.3f}<extra></extra>",
  }));
}

function mcrConcentrationLayout(metadata: any): Record<string, any> {
  return {
    ...BASE_PLOT_LAYOUT,
    showlegend: true,
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: metadata.y_title || "Sample Index" },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: metadata.value_units_label || metadata.value_units || "Relative Concentration" },
  };
}

function buildMCRSpectraTraces(metadata: any): any[] {
  const St = metadata.St || [];
  if (!St.length) return [];

  const nFeatures = St[0]?.length || 0;
  const featureNames = metadata.feature_names;
  const wn = metadata.spectral_wavenumbers || metadata.wavenumbers;
  let xValues;
  if (featureNames && featureNames.length === nFeatures) {
    xValues = featureNames;
  } else if (wn && Array.isArray(wn) && wn.length === nFeatures) {
    xValues = wn;
  } else {
    xValues = Array.from({ length: nFeatures }, (_, i) => i);
  }

  const labels = Array.isArray(metadata.St_labels)
    ? metadata.St_labels.map((item: any) => normalizeSampleLabel(item)).filter((s: string) => s.length > 0)
    : [];

  return St.map((spectrum: number[], i: number) => ({
    type: "scatter",
    mode: "lines",
    x: xValues,
    y: spectrum,
    name: labels[i] || `Pure Spectrum ${i + 1}`,
    line: { width: 2 },
  }));
}

function mcrSpectraLayout(metadata: any): Record<string, any> {
  const St = metadata.St || [];
  const nFeatures = St[0]?.length || 0;
  const candidates = metadata.spectral_wavenumbers || metadata.wavenumbers;
  const hasRealWn = candidates && Array.isArray(candidates) && candidates.length === nFeatures;
  const xTitle = hasRealWn ? (metadata.spectral_x_title || metadata.x_title || "") : "";
  const xUnits = hasRealWn ? (metadata.spectral_x_units || metadata.x_units || "") : "";
  const xLabel = xUnits ? `${xTitle} (${xUnits})` : (xTitle || "Feature Index");
  const yLabel = getYAxisLabel(metadata) || "Response";
  const reverse = hasRealWn && (xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber"));

  return {
    ...BASE_PLOT_LAYOUT,
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: xLabel, autorange: reverse ? "reversed" : true },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: yLabel },
  };
}

// ============================================================================
// Pre-built plot helpers (PLS-DA, HCA, Peak Finding, Plot nodes)
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

// ============================================================================
// Regression: Predicted vs Actual
// ============================================================================

function buildRegressionTraces(metadata: any, targetIdx: number): any[] {
  const yTrue = metadata.y_true;
  const yPred = metadata.y_pred;
  if (!Array.isArray(yTrue) || !Array.isArray(yPred) || yTrue.length === 0) return [];

  try {
    const trueVals = yTrue.map((row: number[]) => (Array.isArray(row) ? row[targetIdx] : row));
    const predVals = yPred.map((row: number[]) => (Array.isArray(row) ? row[targetIdx] : row));
    const allVals = [...trueVals, ...predVals];
    const minVal = Math.min(...allVals);
    const maxVal = Math.max(...allVals);
    const pad = (maxVal - minVal) * 0.05 || 0.1;

    return [
      {
        type: "scatter", mode: "markers",
        x: trueVals, y: predVals,
        marker: { color: "#3b82f6", size: 7, opacity: 0.7 },
        name: "Samples",
        hovertemplate: "Actual: %{x:.3f}<br>Predicted: %{y:.3f}<extra></extra>",
      },
      {
        type: "scatter", mode: "lines",
        x: [minVal - pad, maxVal + pad], y: [minVal - pad, maxVal + pad],
        line: { color: "#94a3b8", dash: "dash", width: 1.5 },
        name: "1:1 Line", showlegend: false, hoverinfo: "skip",
      },
    ];
  } catch {
    return [];
  }
}

function regressionLayout(metadata: any, targetIdx: number): Record<string, any> {
  const targetNames = metadata.target_names || [];
  const targetName = targetNames[targetIdx] || "";
  const r2List = metadata.r2_per_target;
  const rmseList = metadata.rmse_per_target;
  const r2 = Array.isArray(r2List) && typeof r2List[targetIdx] === "number" ? r2List[targetIdx] : null;
  const rmse = Array.isArray(rmseList) && typeof rmseList[targetIdx] === "number" ? rmseList[targetIdx] : null;

  let title = "Predicted vs Actual";
  if (targetName) title += ` — ${targetName}`;
  const metrics: string[] = [];
  if (r2 != null) metrics.push(`R² = ${r2.toFixed(4)}`);
  if (rmse != null) metrics.push(`RMSE = ${rmse.toFixed(4)}`);
  if (metrics.length) title += `<br><span style="font-size:11px;color:#94a3b8">${metrics.join("  |  ")}</span>`;

  return {
    ...BASE_PLOT_LAYOUT,
    title: { text: title, font: { size: 14, color: "#f8fafc" } },
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: "Actual" },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: "Predicted", scaleanchor: "x", scaleratio: 1 },
    showlegend: false,
  };
}

// ============================================================================
// Classification accuracy builder
// ============================================================================

function buildClassificationAccuracyTraces(metadata: any): any[] {
  const yTrue = metadata.y_true;
  const yPred = metadata.y_pred;
  const categories = metadata.label_categories;
  if (!Array.isArray(yTrue) || !Array.isArray(yPred) || !Array.isArray(categories)) return [];

  const correct: Record<string, number> = {};
  const total: Record<string, number> = {};
  for (const c of categories) { correct[c] = 0; total[c] = 0; }
  for (let i = 0; i < yTrue.length; i++) {
    const t = String(yTrue[i]);
    const p = String(yPred[i]);
    if (total[t] !== undefined) {
      total[t]++;
      if (t === p) correct[t]++;
    }
  }

  const accuracies = categories.map((c: string) => total[c] > 0 ? correct[c] / total[c] : 0);
  const overall = yTrue.length > 0
    ? yTrue.filter((t: string, i: number) => String(t) === String(yPred[i])).length / yTrue.length
    : 0;

  return [
    {
      type: "bar",
      x: categories, y: accuracies.map((a: number) => a * 100),
      marker: { color: "#3b82f6" }, name: "Per-class",
      hovertemplate: "%{x}: %{y:.1f}%<extra></extra>",
    },
    {
      type: "scatter", mode: "lines",
      x: [categories[0], categories[categories.length - 1]],
      y: [overall * 100, overall * 100],
      line: { color: "#f59e0b", dash: "dash", width: 2 },
      name: `Overall (${(overall * 100).toFixed(1)}%)`,
    },
  ];
}

function classificationAccuracyLayout(): Record<string, any> {
  return {
    ...BASE_PLOT_LAYOUT,
    title: { text: "Per-Class Accuracy", font: { size: 14, color: "#f8fafc" } },
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: "Class" },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: "Accuracy (%)", range: [0, 105] },
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
  };
}

// ============================================================================
// Holdout evaluation shared helpers
// ============================================================================

/**
 * Extract the flat metrics dictionary from a holdout evaluation node output.
 *
 * Handles both the current shape (metrics port carries the flat dict directly,
 * with scalar keys plus a data/metadata wrapper for inspector rendering) and
 * the legacy bundled shape (default port with nested metrics dict).
 */
function getHoldoutMetricsDict(output: any): Record<string, unknown> | null {
  const ports = output?.ports as Record<string, { value?: unknown }> | undefined;
  const metricsValue = ports?.metrics?.value;
  if (metricsValue && typeof metricsValue === "object") {
    // The metrics port value is the flat dict — scalar keys (accuracy,
    // RMSEP, R2, ...) sit at the top level alongside the table wrapper.
    return metricsValue as Record<string, unknown>;
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

/** Format a numeric metric for display in the metrics table. */
function formatMetricValue(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  if (Number.isInteger(v)) return String(v);
  const abs = Math.abs(v);
  if (abs >= 100) return v.toFixed(2);
  if (abs >= 1) return v.toFixed(3);
  if (abs >= 0.001) return v.toFixed(4);
  return v.toExponential(3);
}

// ============================================================================
// Spectra overlay / heatmap builders (data/preprocess nodes)
// ============================================================================

function buildSpectraOverlayTraces(output: any): any[] {
  const data = output.data || [];
  const metadata = output.metadata || {};
  if (!Array.isArray(data[0])) return [];

  const nFeatures = data[0].length;
  const wn = metadata.wavenumbers;
  const wavenumbers = (Array.isArray(wn) && wn.length === nFeatures) ? wn : Array.from({ length: nFeatures }, (_, i) => i);
  const labels = getLabelArray(metadata.labels || metadata.sample_labels, data.length, "Spectrum");

  const maxTraces = Math.min(data.length, 50);
  return data.slice(0, maxTraces).map((spectrum: number[], i: number) => ({
    type: "scatter", mode: "lines",
    x: wavenumbers, y: spectrum,
    name: labels[i],
    line: { width: 1.5 }, opacity: 0.8,
  }));
}

function spectraOverlayLayout(metadata: any): Record<string, any> {
  const xTitle = metadata.x_title || "Feature";
  const xUnits = metadata.x_units || "";
  const xLabel = xUnits ? `${xTitle} (${xUnits})` : xTitle;
  const reverse = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");
  const yLabel = getYAxisLabel(metadata) || "Response";

  return {
    ...BASE_PLOT_LAYOUT,
    showlegend: true,
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
  const xValues = (Array.isArray(wn) && wn.length === nFeatures) ? wn : Array.from({ length: nFeatures }, (_, i) => i);
  const sampleIndices = Array.from({ length: data.length }, (_, i) => i + 1);
  const xTitle = metadata.x_title || "Feature";

  return [{
    type: "heatmap",
    z: data, x: xValues, y: sampleIndices,
    colorscale: "Viridis",
    hovertemplate: `${xTitle}: %{x:.1f}<br>Sample: %{y}<br>Value: %{z:.4f}<extra></extra>`,
  }];
}

function heatmapLayout(metadata: any): Record<string, any> {
  const xTitle = metadata.x_title || "Feature";
  const xUnits = metadata.x_units || "";
  const xLabel = xUnits ? `${xTitle} (${xUnits})` : xTitle;
  const reverse = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");

  return {
    ...BASE_PLOT_LAYOUT,
    xaxis: { ...BASE_PLOT_LAYOUT.xaxis, title: xLabel, autorange: reverse ? "reversed" : true },
    yaxis: { ...BASE_PLOT_LAYOUT.yaxis, title: "Sample Index" },
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
  const sampleLabels = getLabelArray(metadata.labels, data.length, "Sample");
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
        hovertemplate: `${cat}<br>%{x}: %{y:.3f}<extra></extra>`,
      });
    });
  }
  return traces;
}

function boxPlotLayout(metadata: any): Record<string, any> {
  const sampleLabels = getLabelArray(metadata.labels, 0, "Sample");
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
  const sampleLabels = getLabelArray(metadata.labels, data.length, "Sample");
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
        hovertemplate: `%{text}<br>${xName}: %{x:.3f}<br>${yName}: %{y:.3f}<extra>${cat}</extra>`,
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
    hovertemplate: `%{text}<br>${xName}: %{x:.3f}<br>${yName}: %{y:.3f}<extra></extra>`,
  }];
}

function featureScatterLayout(metadata: any, xIdx: number, yIdx: number): Record<string, any> {
  const featureNames = metadata.feature_names || [];
  const xName = featureNames[xIdx] || `Feature ${xIdx + 1}`;
  const yName = featureNames[yIdx] || `Feature ${yIdx + 1}`;
  const sampleLabels = getLabelArray(metadata.labels, 0, "Sample");
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
  const meanSpec = plots.mean_spectrum;
  const stdSpec = plots.std_spectrum;
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
    hovertemplate: "x: %{x:.1f}<br>Mean: %{y:.4f}<extra></extra>",
  });

  // Std line
  if (stds.length === x.length) {
    traces.push({
      x, y: stds,
      type: "scatter", mode: "lines",
      name: "Std Dev",
      line: { color: "#f59e0b", width: 1.5, dash: "dash" },
      yaxis: "y2",
      hovertemplate: "x: %{x:.1f}<br>Std: %{y:.4f}<extra></extra>",
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
// Before & After comparison builder (stacked subplots)
// ============================================================================

function buildBeforeAfterTraces(inputOutput: any, output: any): any[] {
  const inputData = inputOutput?.data;
  const outputData = output?.data;
  if (!inputData || !Array.isArray(inputData) || !Array.isArray(inputData[0])) return [];
  if (!outputData || !Array.isArray(outputData) || !Array.isArray(outputData[0])) return [];

  const inputMeta = inputOutput?.metadata || {};
  const outputMeta = output?.metadata || {};

  // Resolve x-axis values for each
  const nFeaturesIn = inputData[0].length;
  const nFeaturesOut = outputData[0].length;
  const wnIn = inputMeta.wavenumbers;
  const wnOut = outputMeta.wavenumbers;
  const xIn = (Array.isArray(wnIn) && wnIn.length === nFeaturesIn) ? wnIn : Array.from({ length: nFeaturesIn }, (_, i) => i);
  const xOut = (Array.isArray(wnOut) && wnOut.length === nFeaturesOut) ? wnOut : Array.from({ length: nFeaturesOut }, (_, i) => i);

  const labelsIn = getLabelArray(inputMeta.labels || inputMeta.sample_labels, inputData.length, "Spectrum");
  const labelsOut = getLabelArray(outputMeta.labels || outputMeta.sample_labels, outputData.length, "Spectrum");

  const traces: any[] = [];
  const maxTraces = Math.min(inputData.length, 50);

  // Top subplot: Original (xaxis, yaxis)
  for (let i = 0; i < maxTraces; i++) {
    traces.push({
      type: "scatter", mode: "lines",
      x: xIn, y: inputData[i],
      name: labelsIn[i],
      line: { width: 1.2 }, opacity: 0.7,
      xaxis: "x", yaxis: "y",
      showlegend: false,
    });
  }

  // Bottom subplot: Preprocessed (xaxis2, yaxis2)
  const maxTracesOut = Math.min(outputData.length, 50);
  for (let i = 0; i < maxTracesOut; i++) {
    traces.push({
      type: "scatter", mode: "lines",
      x: xOut, y: outputData[i],
      name: labelsOut[i],
      line: { width: 1.2 }, opacity: 0.7,
      xaxis: "x2", yaxis: "y2",
      showlegend: false,
    });
  }

  return traces;
}

function beforeAfterLayout(inputMeta: any, outputMeta: any): Record<string, any> {
  const meta = outputMeta || inputMeta || {};
  const xTitle = meta.x_title || "Feature";
  const xUnits = meta.x_units || "";
  const xLabel = xUnits ? `${xTitle} (${xUnits})` : xTitle;
  const reverse = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");
  const yLabel = getYAxisLabel(meta) || "Response";

  return {
    ...BASE_PLOT_LAYOUT,
    showlegend: false,
    // Top subplot: Original
    xaxis: {
      ...BASE_PLOT_LAYOUT.xaxis,
      domain: [0, 1],
      anchor: "y",
      autorange: reverse ? "reversed" : true,
      // Hide x-axis labels on top plot (shared with bottom)
      showticklabels: false,
    },
    yaxis: {
      ...BASE_PLOT_LAYOUT.yaxis,
      domain: [0.54, 1],
      title: yLabel,
    },
    // Bottom subplot: Preprocessed
    xaxis2: {
      ...BASE_PLOT_LAYOUT.xaxis,
      domain: [0, 1],
      anchor: "y2",
      title: xLabel,
      autorange: reverse ? "reversed" : true,
    },
    yaxis2: {
      ...BASE_PLOT_LAYOUT.yaxis,
      domain: [0, 0.46],
      title: yLabel,
    },
    annotations: [
      {
        text: "<b>Original</b>", showarrow: false,
        xref: "paper", yref: "paper",
        x: 0, y: 1.0, xanchor: "left", yanchor: "bottom",
        font: { size: 12, color: "#94a3b8" },
      },
      {
        text: "<b>Preprocessed</b>", showarrow: false,
        xref: "paper", yref: "paper",
        x: 0, y: 0.46, xanchor: "left", yanchor: "bottom",
        font: { size: 12, color: "#94a3b8" },
      },
    ],
  };
}

// ============================================================================
// Main composable
// ============================================================================

export function usePlotData(
  nodeOutput: Ref<any> | ComputedRef<any>,
  nodeType: Ref<string> | ComputedRef<string>,
  nodeInput?: Ref<any> | ComputedRef<any>,
) {
  // ---- Type detection ----

  const outputType = computed(() => {
    const metadata = nodeOutput.value?.metadata;
    return metadata?.type || null;
  });

  const isPCA = computed(() => {
    const metadata = nodeOutput.value?.metadata || {};
    return metadata.type === "PCA" || metadata.isPCA === true;
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
      nt.startsWith("normalize.") || nt.startsWith("smooth.");
  });

  const isRegressionNode = computed(() => {
    const nt = nodeType.value;
    return nt === "model.pls" || nt === "model.pcr" || nt === "model.svr";
  });

  const hasOutput = computed(() => {
    const o = nodeOutput.value;
    return o && (o.data || o.plots);
  });

  const isPreprocessNode = computed(() => {
    const nt = nodeType.value;
    return nt.startsWith("preprocess.") || nt.startsWith("baseline.") ||
      nt.startsWith("normalize.") || nt.startsWith("smooth.");
  });

  const hasInputData = computed(() => {
    if (!nodeInput) return false;
    const inp = nodeInput.value;
    return inp && inp.data && Array.isArray(inp.data) && inp.data.length > 0;
  });

  // ---- Interactive state ----

  const xAxis = ref(0);
  const yAxis = ref(1);
  const featureXAxis = ref(0);
  const featureYAxis = ref(1);
  const regressionTargetIdx = ref(0);

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
    const pcLabels = metadata.pc_labels || [];
    const n = pcLabels.length || metadata.n_components || 5;
    return Array.from({ length: n }, (_, i) => ({
      label: pcLabels[i] || `PC${i + 1}`,
      value: i,
    }));
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
    const yTrue = metadata.y_true;
    if (!Array.isArray(yTrue) || yTrue.length === 0) return [];
    const nTargets = Array.isArray(yTrue[0]) ? yTrue[0].length : 1;
    const names = metadata.target_names || [];
    return Array.from({ length: nTargets }, (_, i) => ({
      label: names[i] || `Target ${i + 1}`,
      value: i,
    }));
  });

  // ---- Available plots ----

  const availablePlots = computed<PlotOption[]>(() => {
    if (!hasOutput.value) return [];
    const plots: PlotOption[] = [];
    const nt = nodeType.value;

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
      plots.push(
        { key: "plsda_scores", label: "Scores Plot (with ellipses)" },
        { key: "plsda_loadings", label: "Loadings (Lines)" },
        { key: "plsda_loadings_biplot", label: "Loadings (Biplot)" },
        { key: "plsda_vip", label: "VIP Scores" },
        { key: "plsda_cm_train", label: "Confusion Matrix (Training)" },
        { key: "plsda_cm_cv", label: "Confusion Matrix (CV)" },
        { key: "classification_accuracy", label: "Class Accuracy" },
      );
      return plots;
    }

    if (isClassification.value && !isPLSDA.value) {
      // SIMCA, KNN
      plots.push(
        { key: "classification_scores", label: "Scores Plot" },
        { key: "classification_accuracy", label: "Class Accuracy" },
      );
      return plots;
    }

    if (isHCA.value) {
      plots.push({ key: "hca_dendrogram", label: "Dendrogram" });
      return plots;
    }

    if (nt === "model.pcr" || nt === "model.svr") {
      plots.push({ key: "regression", label: "Predicted vs Actual" });
      return plots;
    }

    if (nt === "stats.summary") {
      const statsPlots = (nodeOutput.value as any)?.plots;
      if (statsPlots?.mean_spectrum) {
        plots.push({ key: "stats_mean_std", label: "Mean & Std Spectrum" });
      } else {
        plots.push({ key: "stats_distribution", label: "Distribution Plot" });
      }
      return plots;
    }

    if (nt === "analysis.peak_finding") {
      plots.push({ key: "peak_finding", label: "Spectra with Peaks" });
      return plots;
    }

    if (nt === "output.plot" || nt === "output.contour") {
      plots.push({ key: "plot_visualization", label: "Visualization" });
      return plots;
    }

    if (nt === "diagnostics.holdout_evaluation" || nt === "diagnostics.cross_validation") {
      // HoldoutEvaluationNode declares its output ports with `visualization`
      // first (no `default`). Read the viz payload directly from that port.
      // Fall back to the legacy `default.visualization` path for cross-validation
      // and any older saved outputs that still used the bundled shape.
      const ports = nodeOutput.value?.ports;
      const vizObj =
        (ports?.visualization?.value as Record<string, unknown> | undefined) ??
        ((ports?.default?.value as Record<string, unknown> | undefined)?.visualization as
          | Record<string, unknown>
          | undefined);
      // Diagnostic: log once per invocation so we can see what the frontend
      // actually received. Safe to remove after the issue is resolved.
      // eslint-disable-next-line no-console
      console.log("[usePlotData] holdout availablePlots detection", {
        nodeType: nt,
        hasOutput: !!nodeOutput.value,
        topLevelKeys: nodeOutput.value ? Object.keys(nodeOutput.value) : null,
        portKeys: ports ? Object.keys(ports) : null,
        vizType: vizObj && typeof vizObj === "object" ? (vizObj as Record<string, unknown>).type : "no-vizObj",
        vizKeys: vizObj && typeof vizObj === "object" ? Object.keys(vizObj) : null,
      });
      if (vizObj?.type === "confusion_matrix") {
        // Classification: confusion matrix (normalized), per-class metrics,
        // predictions scatter, and metrics table.
        plots.push({ key: "holdout_confusion", label: "Confusion Matrix" });
        plots.push({ key: "holdout_per_class", label: "Per-Class Metrics" });
        plots.push({ key: "holdout_predictions", label: "Predictions Scatter" });
        plots.push({ key: "holdout_metrics_table", label: "Metrics Table" });
      } else {
        // Regression: predicted-vs-actual, residuals, and metrics table.
        plots.push({ key: "holdout_regression", label: "Predicted vs Actual" });
        plots.push({ key: "holdout_residuals", label: "Residuals" });
        plots.push({ key: "holdout_metrics_table", label: "Metrics Table" });
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
        // Before & After comparison is the default for preprocess nodes with input data
        if (isPreprocessNode.value && hasInputData.value) {
          plots.push({ key: "before_after", label: "Before & After" });
        }
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
      }
    },
    { immediate: true },
  );

  // ---- Controls visibility ----

  const showAxisControls = computed(() => {
    const key = selectedPlotKey.value;
    return key === "pca_scores" || key === "pca_biplot" || key === "pca_diagnostics" ||
      key === "pls_scores" || key === "classification_scores";
  });

  const showFeatureControls = computed(() => {
    return selectedPlotKey.value === "generic_scatter";
  });

  const showRegressionTargetControl = computed(() => {
    return selectedPlotKey.value === "regression" && regressionTargetOptions.value.length > 1;
  });

  // ---- Plot data and layout ----

  const plotResult = computed<{ data: any[]; layout: Record<string, any> }>(() => {
    const output = nodeOutput.value;
    if (!output) return { data: [], layout: BASE_PLOT_LAYOUT };
    const metadata = output.metadata || {};
    const key = selectedPlotKey.value;

    switch (key) {
      // PCA
      case "pca_scores":
        return {
          data: buildScoresTraces(output.data, metadata, xAxis.value, yAxis.value, "PC"),
          layout: scoresLayout(metadata, xAxis.value, yAxis.value, "PC"),
        };
      case "pca_biplot": {
        const loadingsPort = output.ports?.loadings;
        const loadings = loadingsPort?.data || metadata.loadings || [];
        return {
          data: buildBiplotTraces(output.data, loadings, metadata, xAxis.value, yAxis.value),
          layout: biplotLayout(metadata, xAxis.value, yAxis.value),
        };
      }
      case "pca_loadings": {
        const loadingsPort = output.ports?.loadings;
        const loadingsPayload = resolvePortPayload(loadingsPort);
        const loadings = loadingsPort?.data || metadata.loadings || [];
        return {
          data: buildLoadingsTraces(loadings, metadata, "PC", loadingsPayload),
          layout: loadingsLayout(metadata, loadingsPayload),
        };
      }
      case "pca_scree":
        return { data: buildScreeTraces(metadata), layout: screeLayout() };
      case "pca_diagnostics":
        return { data: buildDiagnosticsTraces(metadata), layout: diagnosticsLayout() };

      // MCR-ALS / Decomposition
      case "mcr_concentrations":
        return { data: buildMCRConcentrationTraces(output), layout: mcrConcentrationLayout(metadata) };
      case "mcr_spectra":
        return { data: buildMCRSpectraTraces(metadata), layout: mcrSpectraLayout(metadata) };

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
        return {
          data: buildRegressionTraces(metadata, regressionTargetIdx.value),
          layout: regressionLayout(metadata, regressionTargetIdx.value),
        };

      // PLS-DA (pre-built plots)
      case "plsda_scores":
        return prebuiltPlot(output, "scores");
      case "plsda_loadings":
        return prebuiltPlot(output, "loadings_lines") || prebuiltPlot(output, "loadings");
      case "plsda_loadings_biplot":
        return prebuiltPlot(output, "loadings_biplot");
      case "plsda_vip":
        return prebuiltPlot(output, "vip");
      case "plsda_cm_train":
        return prebuiltPlot(output, "confusion_matrix_train");
      case "plsda_cm_cv":
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
      case "classification_accuracy":
        return { data: buildClassificationAccuracyTraces(metadata), layout: classificationAccuracyLayout() };

      // HCA
      case "hca_dendrogram":
        return prebuiltPlot(output, "dendrogram");

      // Peak finding
      case "peak_finding":
        return prebuiltPlot(output, "peak_finding");

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

      // Holdout / Cross-Validation evaluation
      // HoldoutEvaluationNode declares `visualization` as a top-level output
      // port; the legacy shape bundled it under a `default` port with a
      // nested `visualization` dict. Support both.
      case "holdout_regression": {
        const ports = output.ports as Record<string, { value?: unknown }> | undefined;
        const vizObj =
          (ports?.visualization?.value as Record<string, unknown> | undefined) ??
          ((ports?.default?.value as Record<string, unknown> | undefined)?.visualization as
            | Record<string, unknown>
            | undefined);
        const pairs = (vizObj?.data as number[][]) || [];
        if (!pairs.length) return { data: [], layout: BASE_PLOT_LAYOUT };
        const actual = pairs.map((p: number[]) => p[0]);
        const predicted = pairs.map((p: number[]) => p[1]);
        const minVal = Math.min(...actual, ...predicted);
        const maxVal = Math.max(...actual, ...predicted);
        return {
          data: [
            { x: actual, y: predicted, mode: "markers", type: "scatter", name: "Samples", marker: { color: "#3b82f6" } },
            { x: [minVal, maxVal], y: [minVal, maxVal], mode: "lines", type: "scatter", name: "1:1 Line", line: { dash: "dash", color: "#94a3b8" } },
          ],
          layout: { ...BASE_PLOT_LAYOUT, title: { text: "Predicted vs Actual", font: { color: "#e2e8f0", size: 14 } }, xaxis: { title: "Actual", color: "#94a3b8" }, yaxis: { title: "Predicted", color: "#94a3b8" }, showlegend: false },
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
        // Diagnostic: log to help debug "No data to display" on staging.
        // Safe to remove once we confirm Quick Plot renders the heatmap.
        // eslint-disable-next-line no-console
        console.log("[usePlotData] holdout_confusion", {
          hasOutput: !!output,
          hasPorts: !!output?.ports,
          portKeys: output?.ports ? Object.keys(output.ports) : null,
          vizPortPresent: !!ports?.visualization,
          vizValueType: vizObj ? typeof vizObj : "undefined",
          vizValueKeys: vizObj && typeof vizObj === "object" ? Object.keys(vizObj) : null,
          vizType: (vizObj as Record<string, unknown> | undefined)?.type,
          cmLength: cm.length,
          cmShape: cm.length ? [cm.length, Array.isArray(cm[0]) ? cm[0].length : "n/a"] : null,
          topLevelDataLength: Array.isArray(output?.data) ? output.data.length : "n/a",
        });
        if (!cm.length) return { data: [], layout: BASE_PLOT_LAYOUT };
        const labels = ((vizObj?.metadata as Record<string, unknown>)?.classes as string[]) || cm.map((_: unknown, i: number) => `Class ${i}`);
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
            hovertemplate: "True: %{y}<br>Predicted: %{x}<br>Row fraction: %{z:.3f}<extra></extra>",
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
        const perClass = (metrics?.per_class as Array<Record<string, unknown>> | undefined) ?? [];
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
          hovertemplate: `%{x}: %{y:.3f}<extra>${m.label}</extra>`,
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
            hovertemplate: "Sample %{x}<br>Predicted: %{y:.4f}<extra></extra>",
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
        const ports = output.ports as Record<string, { value?: unknown }> | undefined;
        const vizObj =
          (ports?.visualization?.value as Record<string, unknown> | undefined) ??
          ((ports?.default?.value as Record<string, unknown> | undefined)?.visualization as
            | Record<string, unknown>
            | undefined);
        const pairs = (vizObj?.data as number[][]) || [];
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
              hovertemplate: "Predicted: %{x:.4f}<br>Residual: %{y:.4f}<extra></extra>",
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
            yaxis: { title: "Residual (true − predicted)", color: "#94a3b8" },
            showlegend: false,
          },
        };
      }

      case "holdout_metrics_table": {
        // Plotly table of the metric keys and values from the metrics port.
        const metrics = getHoldoutMetricsDict(output);
        if (!metrics) return { data: [], layout: BASE_PLOT_LAYOUT };
        const taskType = String(metrics.task_type ?? "");
        const displayKeys: Array<{ key: string; label: string }> = taskType === "classification"
          ? [
              { key: "accuracy", label: "Accuracy" },
              { key: "n_classes", label: "Number of Classes" },
              { key: "n_samples", label: "Number of Samples" },
            ]
          : [
              { key: "RMSEP", label: "RMSEP" },
              { key: "R2", label: "R²" },
              { key: "MAE", label: "MAE" },
              { key: "bias", label: "Bias" },
              { key: "SEP", label: "SEP" },
              { key: "RER", label: "RER" },
              { key: "n_samples", label: "Number of Samples" },
              { key: "n_valid_samples", label: "Valid Samples" },
              { key: "n_invalid_predictions", label: "Invalid Predictions" },
              { key: "status", label: "Status" },
            ];
        const names: string[] = [];
        const values: string[] = [];
        for (const { key, label } of displayKeys) {
          const v = metrics[key];
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
            title: { text: "Test Metrics", font: { color: "#e2e8f0", size: 14 } },
          },
        };
      }

      // Stats
      case "stats_mean_std":
        return { data: buildStatsMeanStdTraces(output), layout: statsMeanStdLayout() };
      case "stats_distribution":
        return { data: buildStatsDistributionTraces(output), layout: statsDistributionLayout() };

      // Data/Preprocess: Before & After comparison
      case "before_after":
        return {
          data: buildBeforeAfterTraces(nodeInput?.value, output),
          layout: beforeAfterLayout(nodeInput?.value?.metadata, metadata),
        };

      // Data/Preprocess: Spectra overlay
      case "spectra_overlay":
        return { data: buildSpectraOverlayTraces(output), layout: spectraOverlayLayout(metadata) };

      // Data/Preprocess: Heatmap
      case "spectra_heatmap":
        return { data: buildHeatmapTraces(output), layout: heatmapLayout(metadata) };

      // Generic dataset
      case "generic_boxplot":
        return { data: buildBoxPlotTraces(output), layout: boxPlotLayout(metadata) };
      case "generic_scatter":
        return {
          data: buildFeatureScatterTraces(output, featureXAxis.value, featureYAxis.value),
          layout: featureScatterLayout(metadata, featureXAxis.value, featureYAxis.value),
        };

      default:
        return { data: [], layout: BASE_PLOT_LAYOUT };
    }
  });

  const plotData = computed(() => plotResult.value.data);
  const plotLayout = computed(() => plotResult.value.layout);

  // ---- Data shape summary ----

  const dataShape = computed(() => {
    const output = nodeOutput.value;
    const defaultRowLabel = isSpectra.value ? "spectra" : "rows";
    const defaultColLabel = isSpectra.value ? "points" : "features";
    const defaultShape = { rows: 0, cols: 0, range: null as [number, number] | null, rowLabel: defaultRowLabel, colLabel: defaultColLabel };
    if (!output?.data) return defaultShape;

    const data = output.data;
    if (!Array.isArray(data)) return defaultShape;

    let rowLabel = defaultRowLabel;
    let colLabel = defaultColLabel;
    if (isMCR.value) { rowLabel = "samples"; colLabel = "components"; }
    else if (isPCA.value) { rowLabel = "observations"; colLabel = "components"; }

    const rows = data.length;
    const cols = Array.isArray(data[0]) ? data[0].length : 1;

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
    isSpectra, isRegressionNode, hasOutput,

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

    // Plot output
    plotData,
    plotLayout,

    // Data shape
    dataShape,
  };
}

// ============================================================================
// Export individual builders for use in NodeDetailView
// ============================================================================

export {
  buildScoresTraces,
  scoresLayout,
  buildLoadingsTraces,
  loadingsLayout,
  buildScreeTraces,
  screeLayout,
  buildDiagnosticsTraces,
  diagnosticsLayout,
  buildBiplotTraces,
  biplotLayout,
  buildMCRConcentrationTraces,
  mcrConcentrationLayout,
  buildMCRSpectraTraces,
  mcrSpectraLayout,
  buildRegressionTraces,
  regressionLayout,
  buildClassificationAccuracyTraces,
  classificationAccuracyLayout,
  buildSpectraOverlayTraces,
  spectraOverlayLayout,
  buildHeatmapTraces,
  heatmapLayout,
  buildBoxPlotTraces,
  boxPlotLayout,
  buildFeatureScatterTraces,
  featureScatterLayout,
  buildStatsDistributionTraces,
  statsDistributionLayout,
  buildStatsMeanStdTraces,
  statsMeanStdLayout,
  prebuiltPlot,
  getLabelArray,
  getCategoryArray,
  resolvePortPayload,
};
