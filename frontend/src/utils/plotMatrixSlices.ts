// Slice the displayed matrix, not the original dataset: it may be filtered,
// reordered, or expressed in a different coordinate scale.
export function plotMatrixSlices(
  trace: { type?: string; x?: unknown[]; y?: unknown[]; z?: unknown[][] },
  point: { pointNumber?: unknown; x?: unknown; y?: unknown },
) {
  if (!["heatmap", "contour"].includes(trace.type ?? "")) return null;
  const { x, y, z } = trace;
  if (!Array.isArray(x) || !Array.isArray(y) || !Array.isArray(z) || z.length !== y.length ||
      !z.every(row => Array.isArray(row) && row.length === x.length)) return null;
  const uniqueIndex = (values: unknown[], value: unknown) => {
    const index = values.indexOf(value);
    return index >= 0 && values.lastIndexOf(value) === index ? index : -1;
  };
  const indices = Array.isArray(point.pointNumber) ? point.pointNumber : null;
  const row = indices ? indices[0] : uniqueIndex(y, point.y);
  const column = indices ? indices[1] : uniqueIndex(x, point.x);
  if (!Number.isInteger(row) || !Number.isInteger(column) || row < 0 || row >= y.length || column < 0 || column >= x.length) return null;
  return {
    rowLabel: String(y[row]), columnLabel: String(x[column]),
    horizontal: { type: "scatter", mode: "lines", x: [...x], y: [...z[row]], connectgaps: false },
    vertical: { type: "scatter", mode: "lines", x: [...y], y: z.map(values => values[column]), connectgaps: false },
  };
}
