import { describe, expect, it } from "vitest";
import { portfolioDetail } from "@/utils/dataPortfolio";
describe("Data Portfolio summary", () => {
  it("reports exact membership without claiming an explicit list is a subset", () => {
    expect(portfolioDetail(33, "claimed_botanical_group", null)).toBe("33 selected files · Target: Claimed Botanical Group · No grouping");
    expect(portfolioDetail(30, "claimed_botanical_group", null)).toContain("30 selected files");
    expect(portfolioDetail(null, null, null)).toContain("All source files");
  });
});
