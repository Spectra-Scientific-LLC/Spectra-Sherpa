/**
 * How the views of one reference package relate, as declared in
 * `reference_dataset_packages_v1.json` (a test keeps this map in step). The Data
 * page uses it to explain why ticked views can be previewed together but cannot
 * go to one workflow together.
 */
export type PackageViewRelation =
  | "same_specimens_aligned"
  | "calibration_application_cohorts"
  | "alignment_unverified";

export const PACKAGE_VIEW_RELATIONS: Record<string, PackageViewRelation> = {
  "corn-m5": "same_specimens_aligned",
  "corn-mp5": "same_specimens_aligned",
  "corn-mp6": "same_specimens_aligned",
  "nir-calibration-1": "calibration_application_cohorts",
  "nir-calibration-2": "calibration_application_cohorts",
  "nir-test-1": "calibration_application_cohorts",
  "nir-test-2": "calibration_application_cohorts",
  "nir-validation-1": "calibration_application_cohorts",
  "nir-validation-2": "calibration_application_cohorts",
  "diesel-high-level": "alignment_unverified",
  "diesel-low-level-a": "alignment_unverified",
  "diesel-low-level-b": "alignment_unverified",
  "metal-etch-machine": "alignment_unverified",
  "metal-etch-oes": "alignment_unverified",
  "metal-etch-rfm": "alignment_unverified",
};

/** Why several ticked views cannot form one workflow source, and what to do instead. */
export function combinedViewsExplanation(viewStems: string[], viewLabels: string[]): string {
  const relations = new Set(viewStems.map((stem) => PACKAGE_VIEW_RELATIONS[stem]));
  const names = viewLabels.length > 1
    ? `${viewLabels.slice(0, -1).join(", ")} and ${viewLabels[viewLabels.length - 1]}` : viewLabels.join("");
  if (relations.size === 1 && relations.has("same_specimens_aligned")) {
    return `${names} measure the same specimens on different instruments. A workflow that uses them together `
      + "would place one specimen in both calibration and test, so its error would look better than it is. "
      + "Compare them here; to model, choose Use only beside one instrument, then apply its model to another "
      + "or add a calibration-transfer step.";
  }
  if (relations.size === 1 && relations.has("calibration_application_cohorts")) {
    return `${names} are separate calibration, test and validation sets. Choose Use only beside the set to `
      + "model; evaluate or apply that model on another set afterwards.";
  }
  return `${names} may hold different variables (feature spaces) and are not verified to share specimens, `
    + "so they cannot form one workflow source. Compare them here; choose Use only beside one view to model it.";
}
