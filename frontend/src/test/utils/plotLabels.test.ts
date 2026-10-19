import { describe, expect, it } from "vitest";
import { getYAxisLabel } from "@/utils/plotLabels";

describe("spectral ordinate labels", () => {
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
