import type { DisplayPreferences } from "@/composables/useDisplayPreferences";
import type { InjectionKey } from "vue";
import { themeToken } from "./interfaceTheme";

export type PlotSurface = "screen" | "panel" | "print";
export const PLOT_SURFACE: InjectionKey<PlotSurface> = Symbol("scientific-plot-surface");

/** Categorical series only. Never use these as sequential/diverging scales or
 * infer scientific/status meaning from a trace's existing color. */
export const PLOTLY_COLORS = [
  "#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A",
  "#19D3F3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52",
];
export const EXTENDED_COLORS = [
  ...PLOTLY_COLORS,
  "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
  "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
];
const ACCESSIBLE_PALETTES = {
  colorblind: ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"],
  // The same category keeps its color in dark panels and light exports.
  // Each color has >=3:1 contrast against both declared plot papers.
  "high-contrast": ["#2677C9", "#C94646", "#21835A", "#9266B6", "#A66B00", "#078487"],
};
export type PlotPalette = DisplayPreferences["palette"];

/** Existing categorical defaults are intentionally preserved, not a rebrand.
 * These families encode series identity, never thresholds or evaluation roles. */
export const SERIES_PALETTES = {
  classes: ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316"],
  clusters: ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316", "#6366f1", "#14b8a6"],
  components: ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#6366f1"],
  diagnostics: ["#0072B2", "#009E73", "#D55E00", "#CC79A7", "#E69F00", "#56B4E9", "#222222"],
  classification: ["#0072B2", "#009E73", "#D55E00", "#CC79A7", "#E69F00", "#56B4E9"],
  library: ["#38bdf8", "#f59e0b", "#22c55e", "#e879f9", "#fb7185", "#a78bfa", "#14b8a6", "#f97316", "#84cc16", "#60a5fa", "#f472b6", "#c084fc"],
  populations: ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#a855f7", "#06b6d4"],
  overlay: ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#db2777", "#0891b2", "#ea580c", "#0f766e", "#4f46e5", "#be123c", "#65a30d", "#0284c7", "#c026d3", "#4d7c0f", "#0d9488", "#c2410c", "#6366f1", "#e11d48", "#059669"],
  dataset: ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#6366f1", "#e11d48", "#84cc16", "#0ea5e9", "#d946ef", "#a3e635", "#2dd4bf", "#fb923c", "#818cf8", "#f472b6", "#34d399"],
  source: ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#db2777", "#0891b2", "#ea580c", "#0d9488", "#4f46e5"],
  features: ["#2563eb", "#dc2626", "#059669", "#9333ea", "#d97706", "#0891b2"],
  species: ["#2563eb", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b", "#17becf", "#e377c2"],
  metrics: ["#3b82f6", "#22c55e", "#f59e0b", "#a855f7"],
} as const;
export type SeriesPalette = keyof typeof SERIES_PALETTES;

/** Non-categorical scientific encodings. A user palette must never turn a
 * refusal, threshold, excluded row, or signed contribution into a class. */
export const SCIENTIFIC_COLORS = {
  observation: "#3b82f6", observationStrong: "#2563eb", observationOutline: "#bfdbfe",
  reference: "#94a3b8", referenceStrong: "#64748b", referenceLine: "#555", zeroLine: "#808080",
  excluded: "#6b7280", alert: "#ef4444", alertOutline: "#fecaca", boundary: "#e11d48",
  threshold: "#f59e0b", peak: "#f97316", thresholdText: "#b45309", thresholdNote: "#7c2d12",
  component: "#14b8a6", statistic: "#38bdf8", positive: "#0072b2", negative: "#d55e00",
  accepted: "#22c55e", selected: "#10b981", importance: "#8b5cf6", unqualified: "#7c3aed",
  calibration: "#94a3b8", crossValidation: "#d97706", heldOut: "#2563eb",
  selection: "#1d4ed8", selectionStrong: "#1e40af", preview: "#60a5fa",
  ink: themeToken("action-text"), secondary: themeToken("text-secondary"),
  grid: themeToken("border"), border: themeToken("border-strong"),
  paper: themeToken("surface"), plotPaper: themeToken("surface-subtle"),
  inverse: themeToken("panel-text"), inverseSecondary: themeToken("panel-secondary"),
  panel: themeToken("panel"), panelInset: themeToken("panel-inset"),
  annotation: themeToken("panel-warning"),
  pointOutline: "rgba(15,23,42,0.3)", pointOutlineStrong: "rgba(15,23,42,0.55)",
  hoverPaper: "rgba(30,41,59,0.82)", legendPaper: "rgba(255, 255, 255, 0.95)",
  selectionFill: "rgba(59,130,246,0.15)",
} as const;

export function categoricalPalette(preference: PlotPalette, categoryCount = 10): readonly string[] {
  return preference === "default"
    ? categoryCount <= 10 ? PLOTLY_COLORS : EXTENDED_COLORS
    : ACCESSIBLE_PALETTES[preference];
}

/** Stable selection colors extend a categorical palette without wrapping to an
 * already assigned color. Selection identities retain their index on toggle. */
export function selectionSeriesColor(palette: readonly string[], index: number): string {
  const base = palette[index % palette.length];
  const cycle = Math.floor(index / palette.length);
  if (!cycle) return base;
  const amount = 1 / (1 + cycle * 0.24);
  return '#' + [1, 3, 5].map(start => Math.round(parseInt(base.slice(start, start + 2), 16) * amount).toString(16).padStart(2, '0')).join('');
}

/** Static exports do not depend on browser CSS variables or an online theme. */
export const PRINT_PLOT_THEME = {
  paper: themeToken("surface"),
  text: themeToken("text-strong"),
  axis: themeToken("text-secondary"),
  observation: themeToken("action"),
} as const;

/** Dark result panels share the interface tokens; print remains light. */
export const PANEL_PLOT_THEME = {
  paper: themeToken("panel-inset"),
  text: themeToken("panel-text"),
  axis: themeToken("panel-secondary"),
  grid: themeToken("panel-raised"),
} as const;

/** Labels/colorbars must follow dark paper; numeric colors and data stay intact. */
export function themedPlotTrace(trace: Record<string, unknown>, surface: PlotSurface): Record<string, unknown> {
  if (surface !== "panel") return trace;
  const font = (value: unknown) => ({ ...(value && typeof value === "object" ? value : {}), color: PANEL_PLOT_THEME.text });
  const colorbar = (value: unknown) => {
    if (!value || typeof value !== "object") return value;
    const bar = value as Record<string, unknown>;
    return { ...bar, tickfont: font(bar.tickfont), ...(bar.title && typeof bar.title === "object"
      ? { title: { ...bar.title, font: font((bar.title as Record<string, unknown>).font) } } : {}) };
  };
  const marker = trace.marker as Record<string, unknown> | undefined;
  return { ...trace,
    ...(trace.textfont ? { textfont: font(trace.textfont) } : {}),
    ...(trace.colorbar ? { colorbar: colorbar(trace.colorbar) } : {}),
    ...(marker?.colorbar ? { marker: { ...marker, colorbar: colorbar(marker.colorbar) } } : {}),
  };
}

/** Layout defaults cannot override explicit scientific scales or reference
 * styling. Producers with categorical colors use categoricalPalette too. */
export function themedPlotLayout(
  layout: Record<string, unknown>,
  preference: PlotPalette,
  target: PlotSurface = "screen",
): Record<string, unknown> {
  const theme = target === "panel" ? PANEL_PLOT_THEME : PRINT_PLOT_THEME;
  const textColor = theme.text;
  const font = (value: unknown) => ({ ...(value && typeof value === "object" ? value : {}), color: textColor });
  const titled = (value: unknown) => value && typeof value === "object"
    ? { ...value, font: font((value as Record<string, unknown>).font) } : value;
  // Surface typography is presentation, never a change to scientific encoding.
  const axes = Object.fromEntries(Object.entries(layout).filter(([key, value]) =>
    /^[xy]axis\d*$/.test(key) && value && typeof value === "object").map(([key, value]) => {
      const axis = value as Record<string, unknown>;
      return [key, { ...axis, color: theme.axis, tickfont: font(axis.tickfont),
        ...(target === "panel" ? { gridcolor: PANEL_PLOT_THEME.grid, linecolor: theme.axis } : {}),
        ...(axis.title !== undefined ? { title: titled(axis.title) } : {}) }];
    }));
  const colorAxes = target === "panel" ? Object.fromEntries(Object.entries(layout)
    .filter(([key, value]) => /^coloraxis\d*$/.test(key) && value && typeof value === "object")
    .map(([key, value]) => [key, themedPlotTrace(value as Record<string, unknown>, target)])) : {};
  return {
    ...layout,
    ...axes,
    ...colorAxes,
    paper_bgcolor: theme.paper,
    plot_bgcolor: theme.paper,
    font: font(layout.font),
    ...(layout.title !== undefined ? { title: titled(layout.title) } : {}),
    ...(layout.legend ? { legend: { ...(layout.legend as Record<string, unknown>), bgcolor: theme.paper, font: font((layout.legend as Record<string, unknown>).font) } } : {}),
    ...(target === "panel" ? {
      modebar: { ...(layout.modebar as Record<string, unknown>), bgcolor: theme.paper, color: theme.axis, activecolor: theme.text },
      annotations: Array.isArray(layout.annotations) ? layout.annotations.map((item) => ({ ...item, font: font(item.font) })) : layout.annotations,
    } : {}),
    ...(preference === "default" ? {} : { colorway: [...categoricalPalette(preference)] }),
  };
}
