import { describe, expect, it } from "vitest";
import { metricPreference } from "@/utils/comparisonPresentation";

describe("metricPreference", () => {
  it("treats floating-point noise as equal", () => {
    expect(metricPreference("bias", 4.42445e-15, -2.22748e-14)).toBe("equal");
    expect(metricPreference("rmse", 1, 1 + 1e-14)).toBe("equal");
  });

  it("keeps real differences directional", () => {
    expect(metricPreference("rmse", 0.9183, 2.69)).toBe("worse");
    expect(metricPreference("bias", -16.2, 1.5)).toBe("better");
    expect(metricPreference("r2", 0.9, 0.95)).toBe("better");
  });
});
