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
    return `Shared specimens — ${names} measure the same specimens; pooling risks leakage between calibration and test · Use one view or calibration transfer.`;
  }
  if (relation === "calibration_application_cohorts") {
    return "Separate cohorts — calibration, test and validation sets serve different roles · Use one view to fit.";
  }
  return "Separate views — different feature spaces or unverified specimen alignment · Use one view to fit.";
}
