import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { combinedViewsExplanation, registeredViewRelation, type PackageViewEntry } from "@/utils/packageViewRelations";

// The catalog serves one entry per package view, carrying that view's declared relations.
function catalogFromRegistry(): PackageViewEntry[] {
  const registry = JSON.parse(readFileSync(
    resolve(__dirname, "../../../../src/spectra_sherpa/data/reference_dataset_packages_v1.json"), "utf8"));
  const packages: Array<{ package_id: string; views: Array<{ view_id: string }>; relations: PackageViewEntry["relations"] }> =
    Array.isArray(registry) ? registry : registry.packages;
  return packages.flatMap((pkg) => pkg.views.map((view) => ({
    package_id: pkg.package_id, view_id: view.view_id,
    relations: pkg.relations.filter((relation) => relation.view_ids.includes(view.view_id)),
  })));
}

describe("registered package view relations", () => {
  const catalog = catalogFromRegistry();

  it("reads the relation each registered package declares, for its own views only", () => {
    expect(registeredViewRelation("eigenvector-corn-v1", ["corn-m5", "corn-mp5"], catalog)).toBe("same_specimens_aligned");
    expect(registeredViewRelation("eigenvector-nir-shootout-v1", ["nir-calibration-1", "nir-test-1"], catalog))
      .toBe("calibration_application_cohorts");
  });

  it("gives familiar file names no relation outside their registered package", () => {
    // An ordinary upload (no registered package) or another package's experiment.
    expect(registeredViewRelation(undefined, ["corn-m5", "corn-mp5"], catalog)).toBeNull();
    expect(registeredViewRelation("eigenvector-diesel-d4052-v1", ["corn-m5", "corn-mp5"], catalog)).toBeNull();
    // A view the package does not declare.
    expect(registeredViewRelation("eigenvector-corn-v1", ["corn-m5", "corn-extra"], catalog)).toBeNull();
    // An unloaded catalog says nothing either.
    expect(registeredViewRelation("eigenvector-corn-v1", ["corn-m5", "corn-mp5"], [])).toBeNull();
  });

  it("explains that same-specimen instrument views would leak between calibration and test", () => {
    const text = combinedViewsExplanation("same_specimens_aligned", ["M5", "MP5"]);
    expect(text).toContain("M5 and MP5 measure the same specimens on different instruments");
    expect(text).toContain("both calibration and test");
    expect(text).toContain("calibration-transfer");
    expect(text).not.toContain("feature spaces");
  });

  it("claims no shared specimens without a declared relation", () => {
    const text = combinedViewsExplanation(null, ["M5", "MP5"]);
    expect(text).toContain("not verified to share specimens");
    expect(text).not.toContain("measure the same specimens");
  });
});
