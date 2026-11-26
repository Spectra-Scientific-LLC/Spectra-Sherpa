import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { PACKAGE_VIEW_RELATIONS, combinedViewsExplanation } from "@/utils/packageViewRelations";

describe("reference package view relations", () => {
  it("matches the relations the package registry declares", () => {
    const registry = JSON.parse(readFileSync(
      resolve(__dirname, "../../../../src/spectra_sherpa/data/reference_dataset_packages_v1.json"), "utf8"));
    const packages: Array<{ relations?: Array<{ relation_type: string; view_ids: string[] }> }> =
      Array.isArray(registry) ? registry : registry.packages;
    const declared = Object.fromEntries(packages.flatMap((pkg) => (pkg.relations ?? [])
      .flatMap((relation) => relation.view_ids.map((view) => [view, relation.relation_type]))));
    expect(PACKAGE_VIEW_RELATIONS).toEqual(declared);
  });

  it("explains that same-specimen instrument views would leak between calibration and test", () => {
    const text = combinedViewsExplanation(["corn-m5", "corn-mp5"], ["M5", "MP5"]);
    expect(text).toContain("M5 and MP5 measure the same specimens on different instruments");
    expect(text).toContain("both calibration and test");
    expect(text).toContain("calibration-transfer");
    expect(text).not.toContain("feature spaces");
  });
});
