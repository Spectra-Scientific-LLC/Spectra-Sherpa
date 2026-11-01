import { describe, expect, it, vi } from "vitest";
import { compactObservationRef, traceObservationRefs, traceObservationIncluded, displayObservationTraces } from "@/utils/workflowPopulationTrace";
import { displayPlot } from "@/utils/displayPlot";
import { DEFAULT_DISPLAY_PREFERENCES } from "@/composables/useDisplayPreferences";
import spectrumFixture from "@/test/fixtures/observation-spectrum-plot.json";

describe("compact whole-observation trace navigation", () => {
  it("marks an excluded spectrum with one dotted line without adding wavelength markers", () => {
    const trace = structuredClone(spectrumFixture.data[1]);
    const before = JSON.stringify(trace);
    const reference = trace.meta.workflow_observation_ref;
    expect(traceObservationRefs(trace)).toEqual([reference, reference]);
    expect(traceObservationIncluded(trace, 1)).toBe(false);
    const displayed = displayObservationTraces([trace])[0];
    expect(displayed.mode).toBe("lines");
    expect(displayed.line).toMatchObject({ dash: "dot" });
    expect(displayed.marker).toBeUndefined();
    expect(displayed.x).toEqual(trace.x);
    expect(displayed.y).toEqual(trace.y);
    expect(displayed.meta).toEqual({ workflow_observation_ref: reference, workflow_included: false });
    expect(JSON.stringify(trace)).toBe(before);
  });

  it("styles 50 long spectra once per observation without per-wavelength style arrays", () => {
    const x = Array.from({ length: 3000 }, (_, i) => i);
    const traces = Array.from({ length: 50 }, (_, i) => ({ type: "scatter", mode: "lines",
      x, y: x.map(value => value + i), line: { width: 1 },
      meta: { workflow_observation_ref: `row:${i}`, workflow_included: true } }));
    const resolve = vi.fn((ref: string) => ({ excluded: Number(ref.split(":")[1]) % 2 === 0, restorable: true }));
    const result = displayObservationTraces(traces, { resolve, change: vi.fn() }, new Set(["row:0"]));
    expect(resolve).toHaveBeenCalledTimes(50);
    traces.forEach((trace, i) => {
      expect(result[i].x).toBe(trace.x);
      expect(result[i].y).toBe(trace.y);
      expect(result[i].meta).toBe(trace.meta);
      expect(result[i].mode).toBe("lines");
      expect(result[i].marker).toBeUndefined();
      expect(result[i].selectedpoints).toBeUndefined();
      expect(result[i].opacity).toBe(i === 0 ? 1 : .35);
      expect(result[i].line).toMatchObject(i % 2 === 0 ? { width: 1, dash: "dot" } : { width: 1 });
    });
    expect(result[50]).toMatchObject({ mode: "lines", line: { dash: "dot" } });
  });

  it("keeps legacy point-aligned arrays, but refuses mixed authority and invalid scalars", () => {
    const trace = { type: "scatter", x: [1, 2], y: [3, 4], meta: {
      workflow_observation_refs: ["one", "two"], workflow_included: [true, false],
    } };
    expect(traceObservationRefs(trace)).toEqual(["one", "two"]);
    expect(traceObservationIncluded(trace, 1)).toBe(false);
    expect(traceObservationRefs({ ...trace, meta: { ...trace.meta, workflow_observation_ref: "one" } })).toEqual([]);
    expect(traceObservationRefs({ ...trace, meta: { workflow_observation_ref: "one", workflow_included: [false] } })).toEqual([]);
    expect(traceObservationRefs({ ...trace, y: [3], meta: { workflow_observation_ref: "one", workflow_included: false } })).toEqual([]);
  });

  it("reserves active curves within display limits after compact excluded curves receive markers", () => {
    const curves = spectrumFixture.data.map(trace => structuredClone(trace));
    const before = JSON.stringify(curves);
    const plotted = displayPlot(displayObservationTraces(curves), {}, { ...DEFAULT_DISPLAY_PREFERENCES, maxRows: 2 });
    const observations = plotted.data.filter(trace => compactObservationRef(trace) !== null);
    expect(observations).toHaveLength(2);
    expect(observations.filter(trace => traceObservationIncluded(trace, 0))).toHaveLength(1);
    expect(observations.filter(trace => !traceObservationIncluded(trace, 0))).toHaveLength(1);
    expect(observations.every(trace => !Array.isArray((trace.meta as Record<string, unknown>).workflow_included))).toBe(true);
    expect(JSON.stringify(curves)).toBe(before);
  });

  it("preserves the same scalar identity when marker points are display-sampled", () => {
    const trace = { type: "scatter", mode: "markers", x: [1, 2, 3], y: [4, 5, 6],
      meta: { workflow_observation_ref: "one", workflow_included: false } };
    const sampled = displayPlot([trace], {}, { ...DEFAULT_DISPLAY_PREFERENCES, maxRows: 2 }).data[0];
    expect(sampled.meta).toEqual(trace.meta);
    expect(traceObservationRefs(sampled)).toEqual(["one", "one"]);
    expect(sampled.x).toEqual([1, 3]);
    expect(sampled.y).toEqual([4, 6]);
  });
});
