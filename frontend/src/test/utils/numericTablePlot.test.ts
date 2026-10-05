import { describe, expect, it } from "vitest";
import { numericTableColumns, numericTableColumnPlot } from "@/utils/numericTablePlot";

describe("numeric table presentation", () => {
  it("plots consensus record measurements without treating membership as measurements", () => {
    const value = { data: [
      { consensus_peak_id: "peak_1", median_pos: 1200, median_height: null, members: [{ sample: 1 }] },
      { consensus_peak_id: "peak_2", median_pos: 1400, median_height: 2, members: [] },
    ] };
    expect(numericTableColumns(value)).toEqual(["consensus_peak_id", "median_pos", "median_height", "members"]);
    expect(numericTableColumnPlot(value, 2)?.data[0].y).toEqual([null, 2]);
    expect(numericTableColumnPlot(value, 2)?.layout.xaxis.title).toBe("Row index");
    expect(numericTableColumnPlot(value, 0)?.layout.yaxis.type).toBe("category");
    expect(numericTableColumnPlot(value, 3)?.layout.annotations?.[0].text).toContain("nested");
  });
  it("keeps missing peak measurements as gaps and retains units and labels", () => {
    const value = { data: [[1202, 3], [null, null]], metadata: {
      column_names: ["peak_position_1", "magnitude_at_peak_1"],
      sample_labels: ["a", "b"], column_units: { peak_position_1: "nm" },
    } };
    const plot = numericTableColumnPlot(value, 0)!;
    expect(plot.data[0].y).toEqual([1202, null]);
    expect(plot.data[0].text).toEqual(["a", "b"]);
    expect(plot.layout.yaxis.title).toBe("peak_position_1 (nm)");
    expect(numericTableColumnPlot(value, 2)).toBeNull();
  });
  it("refuses ragged or nested object tables instead of inventing measurements", () => {
    expect(numericTableColumns({ data: [[1], [2, 3]] })).toEqual([]);
    expect(numericTableColumnPlot({ data: [[{ position: 1200 }]] }, 0)?.data[0].y).toEqual([null]);
  });
  it("offers sparse and entirely null columns without imputing or shifting row indices", () => {
    const value = { data: [{ a: 2, empty: null }, { empty: null }, { a: 4, empty: null }] };
    expect(numericTableColumns(value)).toEqual(["a", "empty"]);
    expect(numericTableColumnPlot(value, 0)?.data[0]).toMatchObject({ x: [1, 2, 3], y: [2, null, 4] });
    expect(numericTableColumnPlot(value, 1)?.layout.annotations?.[0].text).toContain("all values are missing");
  });
});
