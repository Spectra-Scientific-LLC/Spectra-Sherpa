import { describe, expect, it } from "vitest";
import { componentPercent, scientificNumber } from "@/utils/scientificEncoding";
import { buildPredictedVsActualPlot } from "@/utils/scientificPlots";

describe("scientific precision declaration and magnitude handling", () => {
  it("preserves declared significant digits, including trailing zeros", () => {
    expect(scientificNumber(0.94, { significantDigits: 3 })).toBe("0.940");
    expect(scientificNumber(20, { significantDigits: 3 })).toBe("20.0");
    expect(scientificNumber(1e-8, { significantDigits: 3 })).toBe("1.00e-8");
    expect(scientificNumber(12000, { significantDigits: 3 })).toBe("1.20e+4");
  });
  it("preserves decimal policy at ordinary magnitude and its mantissa precision for tiny values", () => {
    expect(scientificNumber(0.94, { decimalPlaces: 3 })).toBe("0.940");
    expect(scientificNumber(0, { decimalPlaces: 3 })).toBe("0.000");
    expect(scientificNumber(1e-6, { decimalPlaces: 3 })).toBe("1.000e-6");
    expect(scientificNumber(-1e-6, { decimalPlaces: 3 })).toBe("-1.000e-6");
    expect(scientificNumber(0.00099, { decimalPlaces: 3 })).toBe("9.900e-4");
    expect(scientificNumber(1e21, { decimalPlaces: 3 })).toBe("1.000e+21");
  });
  it("keeps round-trip coordinate text when precision is not declared", () => {
    expect(scientificNumber(1000.0000000001)).toBe("1000.0000000001");
    expect(scientificNumber(1000.0000000002)).toBe("1000.0000000002");
    expect(scientificNumber(0.94)).toBe("0.94");
    expect(scientificNumber(Number.NaN, { decimalPlaces: 3 })).toBe("Unavailable");
  });
  it("retains the percentage convention without collapsing small component contributions", () => {
    expect(componentPercent(0.2)).toBe("20.0");
    expect(componentPercent(0.0004)).toBe("4.0e-2");
    expect(componentPercent(0.0002)).toBe("2.0e-2");
  });
  it("rejects invalid precision instead of silently changing its declaration", () => {
    expect(() => scientificNumber(1, { significantDigits: 0 })).toThrow(RangeError);
    expect(() => scientificNumber(1, { decimalPlaces: -1 })).toThrow(RangeError);
  });
  it("retains metric zeros and exposes a nonzero micro RMSE together", () => {
    const plot = buildPredictedVsActualPlot({actual: [1,2], predicted: [1.000001,2.000001], r2: 0.94, rmse: 1e-6 });
    expect(JSON.stringify(plot.layout)).toContain("0.9400");
    expect(JSON.stringify(plot.layout)).toContain("1.0000e-6");
  });
});
