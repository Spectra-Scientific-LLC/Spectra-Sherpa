import { describe, expect, it } from "vitest";

import { shouldReverseFeatureAxis } from "@/utils/plotLabels";

describe("shouldReverseFeatureAxis", () => {
  it("distinguishes wavenumber from Raman shift despite shared units", () => {
    expect(
      shouldReverseFeatureAxis({ title: "Wavenumber", units: "cm-1", quantity: "wavenumber" }),
    ).toBe(true);
    expect(
      shouldReverseFeatureAxis({ title: "Raman Shift", units: "cm-1", quantity: "raman_shift" }),
    ).toBe(false);
  });

  it("does not infer direction from inverse-centimetre units alone", () => {
    expect(shouldReverseFeatureAxis({ units: "cm^-1" })).toBe(false);
    expect(shouldReverseFeatureAxis({ title: "Wavelength", units: "nm" })).toBe(false);
    expect(shouldReverseFeatureAxis({ title: "Wave number", units: "cm-1" })).toBe(true);
  });
});
