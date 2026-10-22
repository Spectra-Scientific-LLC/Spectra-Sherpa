import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
// JS is shared with the CLI so the CI assertion cannot drift from the scanner.
// @ts-expect-error -- small build-tool module intentionally has no browser type declarations.
import { inventoryColors, colorRegressions } from "../../../scripts/theme-colors.mjs";
import { computed } from "vue";
import { mount } from "@vue/test-utils";
import PrimeVue from "primevue/config";
import Checkbox from "primevue/checkbox";
import RadioButton from "primevue/radiobutton";
import { createCategoryColorMap, seriesPalette } from "@/utils/colors";
import { themeToken, standaloneThemeCss } from "@/theme/interfaceTheme";
import { useDisplayPreferences } from "@/composables/useDisplayPreferences";
import { categoricalPalette, themedPlotLayout, PRINT_PLOT_THEME, SERIES_PALETTES } from "@/theme/plotTheme";

const root = resolve(process.cwd(), "src");
describe("semantic theme authority", () => {
  it("does not add raw colors outside the declared token and palette owners", () => {
    const baseline = JSON.parse(readFileSync(resolve(root, "../theme-color-baseline.json"), "utf8"));
    expect(colorRegressions(inventoryColors(root), baseline.files)).toEqual([]);
    expect(inventoryColors(root)).toEqual({});
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
    expect(rendered.xaxis).toMatchObject(layout.xaxis);
    expect(rendered.shapes).toEqual(layout.shapes);
    expect(layout).not.toHaveProperty("colorway");
    expect(layout.xaxis).toEqual({ title: "Wavenumber", autorange: "reversed" });
    expect(themedPlotLayout(layout, "default")).not.toHaveProperty("colorway");
  });

  it("provides standalone print colors without changing the chosen categorical policy", () => {
    const printed = themedPlotLayout({ font: { size: 15 }, paper_bgcolor: "transparent" }, "high-contrast", "print");
    expect(printed.font).toEqual({ size: 15, color: PRINT_PLOT_THEME.text });
    expect(printed.paper_bgcolor).toBe(PRINT_PLOT_THEME.paper);
    expect(printed.colorway).toEqual(categoricalPalette("high-contrast"));
  });

  it("resolves every public CSS alias and fails closed on unknown tokens", () => {
    for (const match of standaloneThemeCss.matchAll(/var\((--ss-[\w-]+)\)/g))
      expect(themeToken(match[1])).not.toContain("var(");
    expect(() => themeToken("not-a-token")).toThrow("Unknown theme token");
    for (const path of readdirSync(root, { recursive: true }) as string[]) {
      if (!/\.(css|vue|ts)$/.test(path) || /(?:^|[/\\])test[/\\]/.test(path)) continue;
      const source = readFileSync(resolve(root, path), "utf8");
      for (const match of source.matchAll(/var\((--ss-[\w-]+)\)/g))
        expect(themeToken(match[1]), `${path}: ${match[1]}`).not.toContain("var(");
    }
  });

  it("all declared categorical families update existing projections and preserve their defaults", () => {
    const prefs = useDisplayPreferences();
    const before = prefs.palette;
    try {
      for (const family of Object.keys(SERIES_PALETTES) as (keyof typeof SERIES_PALETTES)[]) {
        prefs.palette = "default";
        const projection = computed(() => seriesPalette(family));
        expect(projection.value).toEqual(SERIES_PALETTES[family]);
        for (const preference of ["colorblind", "high-contrast"] as const) {
          prefs.palette = preference;
          expect(projection.value).toEqual(categoricalPalette(preference));
          expect(seriesPalette(family)).toEqual(projection.value);
        }
      }
    } finally { prefs.palette = before; }
  });

  it("supports normal text contrast on the declared light, dark, status and node surfaces", () => {
    const luminance = (color: string) => {
      const channels = color.slice(1).match(/../g)!.map(c => parseInt(c, 16) / 255)
        .map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4);
      return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
    };
    const contrast = (foreground: string, background: string) => {
      const a = luminance(themeToken(foreground)), b = luminance(themeToken(background));
      return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
    };
    for (const background of ["surface", "surface-subtle", "surface-page", "surface-workspace", "workspace-paper"])
      for (const foreground of ["text-strong", "text-body", "text-secondary", "text-muted", "action", "accent"])
        expect(contrast(foreground, background), `${foreground} on ${background}`).toBeGreaterThanOrEqual(4.5);
    for (const background of ["panel", "panel-inset", "panel-raised"])
      for (const foreground of ["panel-text", "panel-secondary", "panel-muted", "panel-action", "panel-success", "panel-warning", "panel-danger", "panel-accent", "panel-info"])
        expect(contrast(foreground, background), `${foreground} on ${background}`).toBeGreaterThanOrEqual(4.5);
    for (const role of ["success", "warning", "danger", "info"])
      expect(contrast(`${role}-strong`, `${role}-surface`), role).toBeGreaterThanOrEqual(4.5);
    for (const match of standaloneThemeCss.matchAll(/(--ss-node-[\w-]+)\s*:/g))
      expect(contrast("on-action", match[1]), match[1]).toBeGreaterThanOrEqual(4.5);
    expect(contrast("control-primary-text", "control-primary")).toBeGreaterThanOrEqual(4.5);
    for (const background of ["surface", "surface-subtle", "surface-workspace"])
      for (const foreground of ["border-input", "focus"])
        expect(contrast(foreground, background), `${foreground} on ${background}`).toBeGreaterThanOrEqual(3);
  });

  it("styles checked checkboxes and radios on the root PrimeVue actually marks", () => {
    // White-on-white icons otherwise make checked and unchecked identical.
    for (const [component, props] of [[Checkbox, { modelValue: true, binary: true }], [RadioButton, { modelValue: "a", value: "a" }]] as const) {
      const wrapper = mount(component as never, { props, global: { plugins: [PrimeVue] } });
      expect(wrapper.classes()).toContain("p-highlight");
      expect(wrapper.find("[class$='-box']").classes()).not.toContain("p-highlight");
    }
    const controls = readFileSync(resolve(root, "assets/controls.css"), "utf8");
    expect(controls).toContain(".p-checkbox.p-highlight .p-checkbox-box");
    expect(controls).toContain(".p-radiobutton.p-highlight .p-radiobutton-box");
    const stale: string[] = [];
    const scan = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = resolve(dir, entry.name);
        if (entry.isDirectory()) { if (entry.name !== "test") scan(path); }
        else if (/\.(css|vue)$/.test(entry.name) && /(checkbox|radiobutton)-box\.p-highlight/.test(readFileSync(path, "utf8"))) stale.push(path);
      }
    };
    scan(root);
    expect(stale).toEqual([]);
  });
});
