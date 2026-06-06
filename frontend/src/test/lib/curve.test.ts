import { describe, expect, it } from "vitest";
import {
  resampleConcentrationShape,
  sampleCatmullRomAtIndices,
  seedConcentrationShape,
} from "@/utils/curve";

// These golden values are byte-shared with the backend parity test
// (packages/spectra-sherpa/tests/test_curves.py::_GOLDEN). The synthesis
// preview must equal the generated dataset, so the two evaluators are
// pinned to the same numbers in both languages.
const GOLDEN_POINTS = [
  { x: 0, y: 0 },
  { x: 3, y: 10 },
  { x: 6, y: 2 },
  { x: 9, y: 8 },
];
const GOLDEN = [
  0, 3.25925926, 7.62962963, 10, 8.14814815, 4.2962963, 2, 3.18518519,
  5.92592593, 8,
];

describe("sampleCatmullRomAtIndices", () => {
  it("matches the backend frozen golden", () => {
    const curve = sampleCatmullRomAtIndices(GOLDEN_POINTS, 10);
    curve.forEach((value, index) => {
      expect(value).toBeCloseTo(GOLDEN[index], 6);
    });
  });

  it("pads endpoints flat to the full sample grid", () => {
    expect(sampleCatmullRomAtIndices([{ x: 2, y: 5 }, { x: 4, y: 5 }], 8)).toEqual(
      new Array(8).fill(5),
    );
  });

  it("clips negatives but preserves absolute magnitude", () => {
    const curve = sampleCatmullRomAtIndices(
      [{ x: 0, y: 0 }, { x: 5, y: 100000 }, { x: 9, y: 0 }],
      10,
    );
    expect(Math.min(...curve)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...curve)).toBeGreaterThanOrEqual(100000 - 1e-6);
  });

  it("stays stable when points are unsorted or share an x mid-edit", () => {
    const curve = sampleCatmullRomAtIndices(
      [{ x: 6, y: 2 }, { x: 0, y: 0 }, { x: 6, y: 9 }, { x: 9, y: 8 }, { x: 3, y: 10 }],
      10,
    );
    expect(curve).toHaveLength(10);
    expect(curve.every((v) => Number.isFinite(v) && v >= 0)).toBe(true);
  });
});

describe("resampleConcentrationShape", () => {
  it("uses the current Catmull-Rom curve when point count changes", () => {
    const edited = [
      { x: 0, y: 0.2 },
      { x: 25, y: 0.8 },
      { x: 50, y: 0.1 },
      { x: 75, y: 0.9 },
      { x: 100, y: 0.3 },
    ];

    const resized = resampleConcentrationShape(edited, 9);
    const seeded = seedConcentrationShape(9);

    expect(resized).toHaveLength(9);
    expect(resized[0].y).toBeCloseTo(0.2, 6);
    expect(resized[2].y).toBeCloseTo(0.8, 6);
    expect(resized[4].y).toBeCloseTo(0.1, 6);
    expect(resized[6].y).toBeCloseTo(0.9, 6);
    expect(resized[8].y).toBeCloseTo(0.3, 6);
    expect(resized.map((p) => p.y)).not.toEqual(seeded.map((p) => p.y));
  });

  it("falls back to the default seed when no usable curve exists", () => {
    expect(resampleConcentrationShape([], 5)).toEqual(seedConcentrationShape(5));
  });
});
