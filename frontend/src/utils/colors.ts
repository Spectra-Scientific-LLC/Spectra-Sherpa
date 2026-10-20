import { useDisplayPreferences } from "@/composables/useDisplayPreferences";
import { categoricalPalette } from "@/theme/plotTheme";
export { PLOTLY_COLORS, EXTENDED_COLORS } from "@/theme/plotTheme";

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
  const palette = categoricalPalette(useDisplayPreferences().palette, uniqueCategories.length);

  const colorMap = new Map<string | number, string>();
  uniqueCategories.forEach((category, index) => {
    // Cycle through palette if more categories than colors
    colorMap.set(category, palette[index % palette.length]);
  });

  return colorMap;
}
