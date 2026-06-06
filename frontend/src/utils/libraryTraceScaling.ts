type NumericTrace = ReadonlyArray<number | null | undefined>;

type TracePoint = {
  x: number;
  y: number;
  index: number;
};

const EXACT_X_TOLERANCE = 1e-8;
const LIBRARY_PEAK_FLOOR_FRACTION = 0.03;
const SAMPLE_PEAK_FLOOR_FRACTION = 0.03;
const MIN_MATCHED_PEAK_RATIOS = 2;
const FALLBACK_PEAK_COUNT = 12;

function finiteTracePoints(xValues: NumericTrace, yValues: NumericTrace): TracePoint[] {
  const points: TracePoint[] = [];
  for (let index = 0; index < Math.min(xValues.length, yValues.length); index += 1) {
    const x = Number(xValues[index]);
    const y = Number(yValues[index]);
    if (Number.isFinite(x) && Number.isFinite(y)) points.push({ x, y, index });
  }
  return points;
}

function interpolateTraceY(xValues: NumericTrace, yValues: NumericTrace, targetX: number): number | null {
  const points = finiteTracePoints(xValues, yValues).sort((a, b) => a.x - b.x);
  if (points.length === 0 || targetX < points[0].x || targetX > points[points.length - 1].x) return null;
  for (const point of points) {
    if (Math.abs(point.x - targetX) < 1e-12) return point.y;
  }
  for (let index = 1; index < points.length; index += 1) {
    const left = points[index - 1];
    const right = points[index];
    if (targetX >= left.x && targetX <= right.x) {
      const span = right.x - left.x;
      if (span === 0) return left.y;
      const fraction = (targetX - left.x) / span;
      return left.y + fraction * (right.y - left.y);
    }
  }
  return null;
}

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

function isLocalFeature(points: TracePoint[], index: number, floor: number): boolean {
  const point = points[index];
  const absY = Math.abs(point.y);
  if (absY <= floor) return false;
  const leftAbs = index > 0 ? Math.abs(points[index - 1].y) : -Infinity;
  const rightAbs = index < points.length - 1 ? Math.abs(points[index + 1].y) : -Infinity;
  return absY >= leftAbs && absY >= rightAbs && (absY > leftAbs || absY > rightAbs);
}

function libraryPeakPoints(points: TracePoint[]): TracePoint[] {
  const maxLibraryAbs = Math.max(...points.map((point) => Math.abs(point.y)));
  if (!Number.isFinite(maxLibraryAbs) || maxLibraryAbs === 0) return [];
  const featureFloor = maxLibraryAbs * LIBRARY_PEAK_FLOOR_FRACTION;
  const peakCandidates = points.filter((_, index) => isLocalFeature(points, index, featureFloor));
  const candidates = peakCandidates.length > 0
    ? peakCandidates
    : points.filter((point) => Math.abs(point.y) > featureFloor);
  return [...candidates].sort((a, b) => a.x - b.x);
}

function pointIndexAtX(points: TracePoint[], targetX: number): number | null {
  for (let index = 0; index < points.length; index += 1) {
    if (Math.abs(points[index].x - targetX) <= EXACT_X_TOLERANCE) return index;
  }
  return null;
}

function matchedPeakRatios(libraryPeaks: TracePoint[], samplePoints: TracePoint[]): number[] {
  const maxSampleAbs = Math.max(...samplePoints.map((point) => Math.abs(point.y)));
  if (!Number.isFinite(maxSampleAbs) || maxSampleAbs === 0) return [];
  const sampleFeatureFloor = maxSampleAbs * SAMPLE_PEAK_FLOOR_FRACTION;

  return libraryPeaks
    .map((peak) => {
      const sampleIndex = pointIndexAtX(samplePoints, peak.x);
      if (sampleIndex === null) return null;
      const samplePoint = samplePoints[sampleIndex];
      if (!isLocalFeature(samplePoints, sampleIndex, sampleFeatureFloor)) return null;
      if (samplePoint.y * peak.y <= 0) return null;
      const ratio = samplePoint.y / peak.y;
      return Number.isFinite(ratio) && ratio > 0 ? ratio : null;
    })
    .filter((ratio): ratio is number => Number.isFinite(ratio));
}

function singleStrongPeakRatio(
  libraryPeaks: TracePoint[],
  sampleX: NumericTrace,
  sampleY: NumericTrace
): number | null {
  const strongestPeaks = [...libraryPeaks]
    .sort((a, b) => Math.abs(b.y) - Math.abs(a.y))
    .slice(0, FALLBACK_PEAK_COUNT);
  let bestRatio: number | null = null;
  let bestSampleAbs = -Infinity;

  for (const peak of strongestPeaks) {
    if (!Number.isFinite(peak.y) || peak.y === 0) continue;
    const sampleAtPeak = interpolateTraceY(sampleX, sampleY, peak.x);
    if (!Number.isFinite(Number(sampleAtPeak))) continue;
    if (Number(sampleAtPeak) * peak.y <= 0) continue;
    const ratio = Number(sampleAtPeak) / peak.y;
    if (!Number.isFinite(ratio) || ratio <= 0) continue;
    const sampleAbs = Math.abs(Number(sampleAtPeak));
    if (sampleAbs > bestSampleAbs) {
      bestSampleAbs = sampleAbs;
      bestRatio = ratio;
    }
  }

  return bestRatio;
}

function finiteOrGapTrace(yValues: NumericTrace): Array<number | null> {
  return yValues.map((value) => (Number.isFinite(Number(value)) ? Number(value) : null));
}

export function scaleLibraryTraceToSamplePeaks(
  libraryX: NumericTrace,
  libraryY: NumericTrace,
  sampleX: NumericTrace,
  sampleY: NumericTrace
): Array<number | null> {
  const points = finiteTracePoints(libraryX, libraryY);
  if (points.length === 0) return finiteOrGapTrace(libraryY);

  const peakPoints = libraryPeakPoints(points);
  if (peakPoints.length === 0) return finiteOrGapTrace(libraryY);

  const samplePoints = finiteTracePoints(sampleX, sampleY);
  const matchedRatios = matchedPeakRatios(peakPoints, samplePoints);

  const scale = matchedRatios.length >= MIN_MATCHED_PEAK_RATIOS
    ? median(matchedRatios)
    : singleStrongPeakRatio(peakPoints, sampleX, sampleY);
  if (!Number.isFinite(Number(scale))) {
    return finiteOrGapTrace(libraryY);
  }
  return libraryY.map((value) => (Number.isFinite(Number(value)) ? Number(value) * Number(scale) : null));
}
