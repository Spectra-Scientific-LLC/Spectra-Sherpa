import { describe, expect, it } from "vitest";
import { plotMatrixSlices } from "@/utils/plotMatrixSlices";

describe("displayed matrix slices", () => {
  const trace = { type: "heatmap", x: [1200, 1100, 1000], y: ["sample 7", "sample 2"], z: [[7, null, 9], [2, 3, 4]] };
  it("keeps displayed row order, spectral coordinates and missing values", () => {
    const slice = plotMatrixSlices(trace, { pointNumber: [0, 1] })!;
    expect(slice.horizontal).toMatchObject({ x: trace.x, y: [7, null, 9], connectgaps: false });
    expect(slice.vertical).toMatchObject({ x: trace.y, y: [null, 3] });
    expect(slice.rowLabel).toBe("sample 7");
  });
  it("supports contour coordinate events but refuses ambiguous coordinates", () => {
    expect(plotMatrixSlices({ ...trace, type: "contour" }, { x: 1100, y: "sample 2" })?.horizontal.y).toEqual([2, 3, 4]);
    expect(plotMatrixSlices({ ...trace, x: [1100, 1100, 1000] }, { x: 1100, y: "sample 2" })).toBeNull();
  });
  it("refuses nonmatrix traces, malformed shapes and out-of-range cells", () => {
    expect(plotMatrixSlices({ ...trace, type: "scatter" }, { pointNumber: [0, 0] })).toBeNull();
    expect(plotMatrixSlices({ ...trace, z: [[1]] }, { pointNumber: [0, 0] })).toBeNull();
    expect(plotMatrixSlices(trace, { pointNumber: [2, 0] })).toBeNull();
  });
});
