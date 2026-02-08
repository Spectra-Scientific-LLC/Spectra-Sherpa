/**
 * Default Plotly categorical color palette (10 colors)
 */
export const PLOTLY_COLORS = [
  "#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A",
  "#19D3F3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52"
];

/**
 * Extended categorical palette for more categories (20 colors)
 */
export const EXTENDED_COLORS = [
  ...PLOTLY_COLORS,
  "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
  "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF"
];

/**
 * Maps categorical labels to colors
 * @param labels - Array of categorical labels
 * @param categories - Unique categories (if pre-computed)
 * @returns Map of label → color hex
 */
export function createCategoryColorMap(
  labels: (string | number)[],
  categories?: (string | number)[]
): Map<string | number, string> {
  const uniqueCategories = categories || Array.from(new Set(labels)).sort();
  const palette = uniqueCategories.length <= 10 ? PLOTLY_COLORS : EXTENDED_COLORS;

  const colorMap = new Map<string | number, string>();
  uniqueCategories.forEach((category, index) => {
    // Cycle through palette if more categories than colors
    colorMap.set(category, palette[index % palette.length]);
  });

  return colorMap;
}
