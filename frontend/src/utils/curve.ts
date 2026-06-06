import type { CurvePoint, CurveSegment } from "@/types";

const catmullRomCoefficients = (
  p0: number,
  p1: number,
  p2: number,
  p3: number
): number[] => [
  0.5 * (2 * p1),
  0.5 * (-p0 + p2),
  0.5 * (2 * p0 - 5 * p1 + 4 * p2 - p3),
  0.5 * (-p0 + 3 * p1 - 3 * p2 + p3),
];

/**
 * Evenly spaced sine seed shape over x∈[0,100], y∈[0,1].
 *
 * Parity with the backend `app.lib.curves.initial_curve_points`, so a freshly
 * added species starts from the same recognizable trace on both sides.
 */
export const seedConcentrationShape = (
  count: number,
  minPoints = 4,
  maxPoints = 60
): CurvePoint[] => {
  const n = Math.min(Math.max(Math.round(count), minPoints), maxPoints);
  return Array.from({ length: n }, (_, i) => {
    const x = (i / (n - 1)) * 100;
    const y = Math.min(
      Math.max(0.5 + 0.35 * Math.sin((x / 100) * Math.PI - Math.PI / 2), 0),
      1
    );
    return { x, y };
  });
};

export const buildSegments = (points: CurvePoint[]): CurveSegment[] => {
  if (points.length < 2) {
    return [];
  }
  const segments: CurveSegment[] = [];
  for (let idx = 0; idx < points.length - 1; idx += 1) {
    const p0 = points[Math.max(0, idx - 1)];
    const p1 = points[idx];
    const p2 = points[idx + 1];
    const p3 = points[Math.min(points.length - 1, idx + 2)];
    segments.push({
      startX: p1.x,
      endX: p2.x,
      xCoeffs: catmullRomCoefficients(p0.x, p1.x, p2.x, p3.x),
      yCoeffs: catmullRomCoefficients(p0.y, p1.y, p2.y, p3.y),
    });
  }
  return segments;
};

const evaluateCubic = (coeffs: number[], t: number): number => {
  const [a, b, c, d] = coeffs;
  return ((d * t + c) * t + b) * t + a;
};

const clamp01 = (v: number) => Math.min(Math.max(v, 0), 1);

const normalizedShapePoints = (points: CurvePoint[]): CurvePoint[] =>
  [...points]
    .map((p) => ({ x: Number(p.x), y: Number(p.y) }))
    .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y))
    .sort((a, b) => a.x - b.x)
    .filter((p, idx, all) => idx === 0 || p.x > all[idx - 1].x);

const evaluateShapeAtX = (points: CurvePoint[], x: number): number => {
  let sorted = normalizedShapePoints(points);
  if (sorted.length === 0) return 0;
  if (sorted.length === 1) return clamp01(sorted[0].y);
  if (sorted[0].x > 0) {
    sorted = [{ x: 0, y: sorted[0].y }, ...sorted];
  }
  if (sorted[sorted.length - 1].x < 100) {
    sorted = [...sorted, { x: 100, y: sorted[sorted.length - 1].y }];
  }

  const clampedX = Math.min(Math.max(x, 0), 100);
  let seg = sorted.findIndex((point) => point.x >= clampedX) - 1;
  if (seg < 0) seg = 0;
  seg = Math.min(seg, sorted.length - 2);
  const p1 = sorted[seg];
  const p2 = sorted[seg + 1];
  const span = p2.x - p1.x;
  if (span <= 0) return clamp01(p1.y);

  const p0 = sorted[Math.max(0, seg - 1)];
  const p3 = sorted[Math.min(sorted.length - 1, seg + 2)];
  const t = (clampedX - p1.x) / span;
  const value =
    0.5 *
    (2 * p1.y +
      (-p0.y + p2.y) * t +
      (2 * p0.y - 5 * p1.y + 4 * p2.y - p3.y) * t ** 2 +
      (-p0.y + 3 * p1.y - 3 * p2.y + p3.y) * t ** 3);
  return clamp01(value);
};

/**
 * Resize the editable concentration-shape control points without resetting
 * the user's current curve.
 *
 * The new handles are spaced on the same 0..100 editor domain, with y sampled
 * from the existing Catmull-Rom curve. This keeps point-count +/- operations
 * as a refinement step instead of returning the species to the default seed.
 */
export const resampleConcentrationShape = (
  points: CurvePoint[],
  count: number,
  minPoints = 4,
  maxPoints = 60
): CurvePoint[] => {
  const n = Math.min(Math.max(Math.round(count), minPoints), maxPoints);
  if (normalizedShapePoints(points).length < 2) {
    return seedConcentrationShape(n, minPoints, maxPoints);
  }
  return Array.from({ length: n }, (_, i) => {
    const x = (i / (n - 1)) * 100;
    return { x, y: evaluateShapeAtX(points, x) };
  });
};

/**
 * Evaluate a Catmull-Rom trace on the integer sample-index grid.
 *
 * Mirrors the backend `app.lib.curves.evaluate_catmull_rom_samples` exactly
 * (sample-index x domain, flat endpoint padding, clipped only at zero so
 * absolute ppm magnitude is preserved). Keeping this in lockstep with the
 * backend means the concentration preview matches the generated dataset.
 *
 * Non-strictly-increasing x are dropped rather than throwing, so the live
 * editor preview stays stable mid-drag; the backend still validates on submit.
 */
export const sampleCatmullRomAtIndices = (
  points: CurvePoint[],
  nSamples: number
): number[] => {
  const n = Math.max(2, Math.floor(nSamples));
  const sorted = [...points]
    .map((p) => ({ x: Number(p.x), y: Number(p.y) }))
    .sort((a, b) => a.x - b.x)
    .filter((p, idx, all) => idx === 0 || p.x > all[idx - 1].x);
  if (sorted.length < 2) {
    return Array.from({ length: n }, () => Math.max(0, sorted[0]?.y ?? 0));
  }
  let xs = sorted.map((p) => p.x);
  let ys = sorted.map((p) => p.y);
  if (xs[0] > 0 || xs[xs.length - 1] < n - 1) {
    xs = [0, ...xs, n - 1];
    ys = [ys[0], ...ys, ys[ys.length - 1]];
  }
  const out: number[] = new Array(n);
  for (let i = 0; i < n; i += 1) {
    // searchsorted(side="right") - 1, clamped to a valid segment
    let seg = xs.findIndex((xv) => xv > i);
    seg = (seg < 0 ? xs.length - 1 : seg) - 1;
    seg = Math.max(0, Math.min(seg, xs.length - 2));
    const x1 = xs[seg];
    const x2 = xs[seg + 1];
    if (x2 <= x1) {
      out[i] = Math.max(0, ys[seg]);
      continue;
    }
    const p0 = ys[Math.max(0, seg - 1)];
    const p1 = ys[seg];
    const p2 = ys[seg + 1];
    const p3 = ys[Math.min(ys.length - 1, seg + 2)];
    const t = (i - x1) / (x2 - x1);
    const value =
      0.5 *
      (2 * p1 +
        (-p0 + p2) * t +
        (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2 +
        (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3);
    out[i] = Math.max(0, value);
  }
  return out;
};

export const sampleSegments = (
  segments: CurveSegment[],
  samplesPerSegment: number
): CurvePoint[] => {
  const samples: CurvePoint[] = [];
  const steps = Math.max(2, Math.floor(samplesPerSegment));
  segments.forEach((segment, index) => {
    for (let i = 0; i < steps; i += 1) {
      if (index > 0 && i === 0) {
        continue;
      }
      const t = i / (steps - 1);
      samples.push({
        x: evaluateCubic(segment.xCoeffs, t),
        y: evaluateCubic(segment.yCoeffs, t),
      });
    }
  });
  return samples;
};
