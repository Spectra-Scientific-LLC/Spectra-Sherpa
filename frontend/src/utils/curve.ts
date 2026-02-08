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
