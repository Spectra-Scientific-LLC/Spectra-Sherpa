import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
// JS is shared with the CLI so the CI assertion cannot drift from the scanner.
// @ts-expect-error -- small build-tool module intentionally has no browser type declarations.
import { inventoryColors, colorRegressions } from "../../../scripts/theme-colors.mjs";
import { computed } from "vue";
import { createCategoryColorMap } from "@/utils/colors";
import { useDisplayPreferences } from "@/composables/useDisplayPreferences";
import { categoricalPalette, themedPlotLayout, PRINT_PLOT_THEME } from "@/theme/plotTheme";

const root = resolve(process.cwd(), "src");
describe("semantic theme authority", () => {
  it("does not add raw colors outside the declared token and palette owners", () => {
    const baseline = JSON.parse(readFileSync(resolve(root, "../theme-color-baseline.json"), "utf8"));
    expect(colorRegressions(inventoryColors(root), baseline.files)).toEqual([]);
  });

  it("cannot pay for a new color/file by removing old occurrences", () => {
    expect(colorRegressions({ "view.vue": { "#222": 1 }, "new.vue": { "#111": 1 } },
      { "view.vue": { "#111": 100 } })).toHaveLength(2);
    expect(colorRegressions({ "view.vue": { "#111": 99 } }, { "view.vue": { "#111": 100 } })).toEqual([]);
  });

  it("keeps the shared shell free of raw colors and loads tokens after PrimeVue", () => {
    const css = readFileSync(resolve(root, "assets/main.css"), "utf8");
    expect(css).not.toMatch(/#[\da-f]{3,8}\b|rgba?\(/i);
    const main = readFileSync(resolve(root, "main.ts"), "utf8");
    expect(main.indexOf('"./assets/tokens.css"')).toBeGreaterThan(main.indexOf('"primevue/resources/themes/lara-light-blue/theme.css"'));
    expect(main.indexOf('"./assets/tokens.css"')).toBeLessThan(main.indexOf('"./assets/main.css"'));
  });

  it("updates already-computed categorical colors when the accessibility preference changes", () => {
    const prefs = useDisplayPreferences();
    const before = prefs.palette;
    try {
      prefs.palette = "default";
      const colors = computed(() => createCategoryColorMap(["A", "B", "A"]));
      expect(colors.value.get("A")).toBe(categoricalPalette("default")[0]);
      prefs.palette = "colorblind";
      expect(colors.value.get("A")).toBe(categoricalPalette("colorblind")[0]);
      expect(createCategoryColorMap(["A", "B"]).get("A")).toBe(colors.value.get("A"));
      prefs.palette = "high-contrast";
      expect(colors.value.get("B")).toBe(categoricalPalette("high-contrast")[1]);
    } finally { prefs.palette = before; }
  });

  it("preserves continuous scales, reference geometry, coordinates and retained layout", () => {
    const layout = { coloraxis: { colorscale: "RdBu", cmin: -2, cmax: 2 },
      xaxis: { title: "Wavenumber", autorange: "reversed" }, shapes: [{ line: { color: "red" } }] };
    const rendered = themedPlotLayout(layout, "colorblind");
    expect(rendered.coloraxis).toEqual(layout.coloraxis);
    expect(rendered.xaxis).toEqual(layout.xaxis);
    expect(rendered.shapes).toEqual(layout.shapes);
    expect(layout).not.toHaveProperty("colorway");
    expect(themedPlotLayout(layout, "default")).toEqual(layout);
  });

  it("provides standalone print colors without changing the chosen categorical policy", () => {
    const printed = themedPlotLayout({ font: { size: 15 }, paper_bgcolor: "transparent" }, "high-contrast", "print");
    expect(printed.font).toEqual({ size: 15, color: PRINT_PLOT_THEME.text });
    expect(printed.paper_bgcolor).toBe(PRINT_PLOT_THEME.paper);
    expect(printed.colorway).toEqual(categoricalPalette("high-contrast"));
  });
});
