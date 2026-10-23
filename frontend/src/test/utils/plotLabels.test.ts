import { describe, expect, it } from "vitest";
import { getYAxisLabel } from "@/utils/plotLabels";

describe("spectral ordinate labels", () => {
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
