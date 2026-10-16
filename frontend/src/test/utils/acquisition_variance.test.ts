import { describe, expect, it } from "vitest";
import { acquisitionVarianceWarning } from "@/utils/acquisitionVariance";

const member = (scanCount: number, acquiredAt: string) => ({
  metadata: { "omnic.acquisition": { scan_count: scanCount, acquired_at: acquiredAt } },
});

describe("acquisition differences", () => {
  it("names the setting that varies across files", () => {
    expect(acquisitionVarianceWarning([member(32, "10:00"), member(64, "11:00")]))
      .toContain("sample scans");
  });

  it("does not warn for timestamps alone or unknown settings", () => {
    expect(acquisitionVarianceWarning([member(32, "10:00"), member(32, "11:00")])).toBeNull();
    expect(acquisitionVarianceWarning([{ metadata: {} }, { metadata: {} }])).toBeNull();
  });
});
