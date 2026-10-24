import { describe, expect, it } from "vitest";

import {
  defaultPlateFormatId,
  formatWell,
  getPlateFormat,
  parsePlateWell,
  plateFormats,
} from "@/utils/plateFormats";

describe("plate format registry", () => {
  it("publishes one explicit 96-well authoring contract", () => {
    const format = getPlateFormat();
    expect(defaultPlateFormatId).toBe("plate-96");
    expect(plateFormats).toHaveLength(7);
    expect(format).toMatchObject({ label: "96-well plate", columns: 12, capacity: 96 });
    expect(format.rows).toEqual(["A", "B", "C", "D", "E", "F", "G", "H"]);
    expect(formatWell(format, 0, 0)).toBe("A01");
    expect(formatWell(format, 7, 11)).toBe("H12");
  });

  it("rejects coordinates outside the selected format", () => {
    const format = getPlateFormat();
    expect(parsePlateWell("H12", format)).toEqual({ row: 7, column: 11 });
    expect(() => parsePlateWell("A13", format)).toThrow("outside 96-well plate");
    expect(() => getPlateFormat("plate-72")).toThrow("Unknown plate format");
  });

  it.each([
    [6, 2, 3, "B03"],
    [12, 3, 4, "C04"],
    [24, 4, 6, "D06"],
    [48, 6, 8, "F08"],
    [96, 8, 12, "H12"],
    [384, 16, 24, "P24"],
    [1536, 32, 48, "AF48"],
  ])("uses the declared %s-well geometry", (capacity, rows, columns, last) => {
    const format = getPlateFormat(`plate-${capacity}`);
    expect(format.rows).toHaveLength(Number(rows));
    expect(format.columns).toBe(columns);
    expect(format.capacity).toBe(capacity);
    expect(formatWell(format, Number(rows) - 1, Number(columns) - 1)).toBe(last);
    expect(parsePlateWell(String(last), format)).toEqual({
      row: Number(rows) - 1,
      column: Number(columns) - 1,
    });
  });
});
