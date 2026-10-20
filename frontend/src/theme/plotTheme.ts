import type { DisplayPreferences } from "@/composables/useDisplayPreferences";

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
  "high-contrast": ["#002B7F", "#B62020", "#006B45", "#671094", "#A05500", "#006D83"],
};
export type PlotPalette = DisplayPreferences["palette"];

export function categoricalPalette(preference: PlotPalette, categoryCount = 10): readonly string[] {
  return preference === "default"
    ? categoryCount <= 10 ? PLOTLY_COLORS : EXTENDED_COLORS
    : ACCESSIBLE_PALETTES[preference];
}

/** Static exports do not depend on browser CSS variables or an online theme. */
export const PRINT_PLOT_THEME = {
  paper: "#ffffff",
  text: "#222222",
  axis: "#444444",
  observation: "#2563eb",
} as const;

/** Layout defaults cannot override explicit scientific scales or reference
 * styling. Producers with categorical colors use categoricalPalette too. */
export function themedPlotLayout(
  layout: Record<string, unknown>,
  preference: PlotPalette,
  target: "screen" | "print" = "screen",
): Record<string, unknown> {
  return {
    ...layout,
    ...(preference === "default" ? {} : { colorway: [...categoricalPalette(preference)] }),
    ...(target === "print" ? {
      paper_bgcolor: PRINT_PLOT_THEME.paper,
      plot_bgcolor: PRINT_PLOT_THEME.paper,
      font: { ...(layout.font as Record<string, unknown> | undefined), color: PRINT_PLOT_THEME.text },
    } : {}),
  };
}
