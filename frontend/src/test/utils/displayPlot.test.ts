import { describe, expect, it } from "vitest";
import { DEFAULT_DISPLAY_PREFERENCES } from "@/composables/useDisplayPreferences";
import { displayPlot } from "@/utils/displayPlot";

describe("display plot preferences", () => {
  it("renders saved plot layouts with one title while preserving data annotations", () => {
    const savedLayout = {
      title: { text: "PCA Scores<br><sup>Equal axis units</sup>" },
      annotations: [
        { text: "Equal axis units", xref: "paper", yref: "paper", y: 1.14, showarrow: false },
        { text: "RMSEP 0.3975<br>n 10", xref: "paper", yref: "paper", y: .98, showarrow: false },
        { text: "Limit 0.8", xref: "paper", yref: "paper", y: 1.1, showarrow: false },
        { text: "Sample A", xref: "x", yref: "y", x: 1, y: 2, showarrow: false },
      ],
    };
    const rendered = displayPlot([{ type: "scatter", x: [1], y: [2] }], savedLayout, DEFAULT_DISPLAY_PREFERENCES);
    expect(rendered.layout.title).toEqual({ text: "PCA Scores" });
    expect(rendered.layout.annotations).toEqual(savedLayout.annotations.slice(2));
    expect(savedLayout.title.text).toContain("Equal axis units");
    expect(savedLayout.annotations).toHaveLength(4);
  });

  it("caps sample marker rows without changing the retained source or aligned identities", () => {
    const source = {
      type: "scatter", mode: "markers", x: Array.from({ length: 400 }, (_, i) => i),
      y: Array.from({ length: 400 }, (_, i) => i * 2),
      ids: Array.from({ length: 400 }, (_, i) => `sample-${i}`),
      marker: { size: 8, color: Array.from({ length: 400 }, (_, i) => i) },
    };
    const rendered = displayPlot([source], {}, DEFAULT_DISPLAY_PREFERENCES);
    expect(rendered.omitted).toBe(100);
    expect(rendered.layout.annotations).toBeUndefined();
    expect(rendered.data[0].x).toHaveLength(300);
    expect(rendered.data[0].ids).toHaveLength(300);
    expect((rendered.data[0].marker as { color: number[] }).color).toHaveLength(300);
    expect(source.x).toHaveLength(400);
  });

  it("never mistakes wavelength points in a spectrum for sample rows", () => {
    const spectrum = { type: "scatter", mode: "lines", x: Array.from({ length: 1800 }, (_, i) => i), y: Array(1800).fill(0.5) };
    const rendered = displayPlot([spectrum], {}, DEFAULT_DISPLAY_PREFERENCES);
    expect(rendered.omitted).toBe(0);
    expect(rendered.data[0].x).toHaveLength(1800);
  });

  it("shares the 300-row ceiling across grouped sample traces", () => {
    const group = (name: string) => ({
      type: "scatter", mode: "markers", name,
      x: Array.from({ length: 250 }, (_, i) => i),
      y: Array.from({ length: 250 }, (_, i) => i / 10),
      ids: Array.from({ length: 250 }, (_, i) => `${name}-${i}`),
    });
    const rendered = displayPlot([group("A"), group("B")], {}, DEFAULT_DISPLAY_PREFERENCES);
    expect(rendered.data.reduce((sum, trace) => sum + (trace.x as number[]).length, 0)).toBe(300);
    expect(rendered.omitted).toBe(200);
    expect((rendered.data[0].ids as string[]).at(-1)).toBe("A-249");
    expect((rendered.data[1].ids as string[]).at(-1)).toBe("B-249");
  });

  it("keeps a selected sample in the bounded marker preview without changing the source", () => {
    const source = {
      type: "scatter", mode: "markers",
      x: Array.from({ length: 400 }, (_, i) => i),
      y: Array.from({ length: 400 }, (_, i) => i),
      customdata: Array.from({ length: 400 }, (_, i) => `sample-${i}`),
    };
    const ordinary = displayPlot([source], {}, DEFAULT_DISPLAY_PREFERENCES);
    expect(ordinary.data[0].customdata).not.toContain("sample-3");
    const selected = displayPlot([source], {}, DEFAULT_DISPLAY_PREFERENCES, new Set(["sample-3"]));
    expect(selected.data[0].customdata).toContain("sample-3");
    expect(selected.data[0].x).toHaveLength(300);
    expect(selected.omitted).toBe(100);
    expect(source.customdata).toHaveLength(400);
  });

  it("uses custom palette and scales styling without mutating scientific values", () => {
    const source = { type: "scatter", mode: "lines+markers", x: [1, 2], y: [0.1, 0.2], line: { width: 2 }, marker: { size: 4 } };
    const rendered = displayPlot([source], { xaxis: { title: "Wavenumber" } }, {
      ...DEFAULT_DISPLAY_PREFERENCES, palette: "colorblind", lineScale: 1.5, markerScale: 1.5,
    });
    expect((rendered.data[0].line as { width: number }).width).toBe(3);
    expect((rendered.data[0].marker as { size: number }).size).toBe(6);
    expect(rendered.data[0].y).toEqual([0.1, 0.2]);
    expect(rendered.layout.xaxis).toEqual({ title: "Wavenumber" });
    expect(source.line.width).toBe(2);
  });
});
