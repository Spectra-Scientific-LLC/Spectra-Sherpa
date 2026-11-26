/**
 * How the views of one registered reference package relate. The authority is the
 * package registry, as the reference catalog serves it (`dataset_package.relations`);
 * nothing here re-declares it. A relation applies only to an experiment imported
 * from that registered package, whose files are its declared views; a file with a
 * familiar name anywhere else gets no relation.
 */
export interface PackageViewEntry {
  package_id: string;
  view_id: string;
  relations: Array<{ relation_type: string; view_ids: string[] }>;
}

/** The declared relation shared by every chosen view of one registered package, or null. */
export function registeredViewRelation(
  packageId: unknown,
  viewIds: string[],
  catalog: Array<PackageViewEntry | null | undefined>,
): string | null {
  if (typeof packageId !== "string" || viewIds.length < 2) return null;
  const views = catalog.filter((entry): entry is PackageViewEntry => entry?.package_id === packageId);
  const declared = new Set(views.map((entry) => entry.view_id));
  if (!viewIds.every((view) => declared.has(view))) return null;
  const relation = views.flatMap((entry) => entry.relations)
    .find((candidate) => viewIds.every((view) => candidate.view_ids.includes(view)));
  return relation?.relation_type ?? null;
}

/** Why several ticked views cannot form one workflow source, and what to do instead. */
export function combinedViewsExplanation(relation: string | null, viewLabels: string[]): string {
  const names = viewLabels.length > 1
    ? `${viewLabels.slice(0, -1).join(", ")} and ${viewLabels[viewLabels.length - 1]}` : viewLabels.join("");
  if (relation === "same_specimens_aligned") {
    return `${names} measure the same specimens on different instruments. A workflow that uses them together `
      + "would place one specimen in both calibration and test, so its error would look better than it is. "
      + "Compare them here; to model, choose Use only beside one instrument, then apply its model to another "
      + "or add a calibration-transfer step.";
  }
  if (relation === "calibration_application_cohorts") {
    return `${names} are separate calibration, test and validation sets. Choose Use only beside the set to `
      + "model; evaluate or apply that model on another set afterwards.";
  }
  return `${names} may hold different variables (feature spaces) and are not verified to share specimens, `
    + "so they cannot form one workflow source. Compare them here; choose Use only beside one view to model it.";
}
