import { describe, expect, it } from "vitest";
import { getYAxisLabel, isRowCoordinateTitle } from "@/utils/plotLabels";

describe("spectral ordinate labels", () => {
  it.each(["Specimen", "Sample index", "Acquisition ID"])("recognizes row-coordinate title %s", title => {
    expect(isRowCoordinateTitle(title)).toBe(true);
  });
  it.each(["Absorbance", "Component score", ""])("keeps non-row title %s outside the row guard", title => {
    expect(isRowCoordinateTitle(title)).toBe(false);
  });
  it("retains declared dimensionless and normalized signal context", () => {
    expect(getYAxisLabel({ y_title: "Samples", value_units: "dimensionless" })).toBe("Intensity (dimensionless)");
    expect(getYAxisLabel({ y_title: "Samples", value_units: "normalized" })).toBe("Normalized intensity");
    expect(getYAxisLabel({ value_units: "dimensionless" })).toBe("Response (dimensionless)");
    expect(getYAxisLabel({ value_units: "normalized" })).toBe("Normalized response");
  });
  it.each(["Sample", "Acquisition"])("does not use %s as the absorbance ordinate", title => {
    expect(getYAxisLabel({ y_title: title, value_units: "absorbance" })).toBe("Absorbance");
  });
  it("retains an explicit physical response title", () => {
    expect(getYAxisLabel({ y_title: "CO2", y_units: "ppm" })).toBe("CO2 (ppm)");
  });
  it.each(["Specimen", "Component", "Sample index"])("does not promote %s or its units to signal quantity", title => {
    expect(getYAxisLabel({ y_title: title, y_units: "seconds" })).toBe("Intensity");
    expect(getYAxisLabel({ y_title: title, value_units: "absorbance" })).toBe("Absorbance");
  });
});
