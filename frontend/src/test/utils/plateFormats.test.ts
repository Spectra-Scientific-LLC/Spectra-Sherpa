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
    expect(plateFormats).toHaveLength(1);
    expect(format).toMatchObject({ label: "96-well plate", columns: 12, capacity: 96 });
    expect(format.rows).toEqual(["A", "B", "C", "D", "E", "F", "G", "H"]);
    expect(formatWell(format, 0, 0)).toBe("A01");
    expect(formatWell(format, 7, 11)).toBe("H12");
  });

  it("rejects coordinates outside the selected format", () => {
    const format = getPlateFormat();
    expect(parsePlateWell("H12", format)).toEqual({ row: 7, column: 11 });
    expect(() => parsePlateWell("A13", format)).toThrow("outside 96-well plate");
    expect(() => getPlateFormat("plate-384")).toThrow("Unknown plate format");
  });
});
