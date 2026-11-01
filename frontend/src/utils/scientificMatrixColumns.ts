import type { NodeOutput } from "./nodeOutput";
import { isProjectedScientificKind } from "./scientificPresentation";
import { scientificColumnLabel } from "./scientificDisplay";

const classRowRoles = new Set(["class", "response_class", "actual_class", "predicted_class"]);

export function isConfusionMatrix(output: NodeOutput | null | undefined): boolean {
  return isProjectedScientificKind(output, "confusion_matrix") ||
    output?.descriptor?.scientific_kind === "confusion_matrix" || output?.metadata?.type === "ClassificationTest";
}

/** Use declared dimension semantics; neither shape nor class count defines a row. */
export function scientificMatrixClassRowRole(output: NodeOutput | null | undefined): string | null {
  const role = output?.descriptor?.dimensions?.[0]?.role;
  if (role) return classRowRoles.has(role) ? role : null;
  return isConfusionMatrix(output) ? "actual_class" : null;
}

/** Labels belong to this result's row axis, not a similarly sized input. */
export function scientificMatrixRowLabels(output: NodeOutput | null | undefined, rows: number): string[] {
  const value = output?.presentation_value as Record<string, unknown> | undefined;
  const axis = (value?.sample_axis ?? value?.y_axis) as Record<string, unknown> | undefined;
  const metadata = output?.metadata ?? {};
  const diagnostics = metadata.diagnostics as Record<string, unknown> | undefined;
  const row = output?.descriptor?.dimensions?.[0];
  const classRole = scientificMatrixClassRowRole(output);
  // A declared non-class axis contradicts a confusion presentation. Do not
  // recover class identity from unrelated sample labels, even at equal length.
  if (isConfusionMatrix(output) && !classRole) return [];
  if (classRole && (output?.descriptor?.shape_valid === false || (row?.size != null && row.size !== rows))) return [];
  // Select authority before validating it: malformed explicit labels must not
  // fall through to a convenient lower-priority label array.
  const candidate = row?.labels ?? axis?.labels ?? (classRole
    ? metadata.classes ?? diagnostics?.classes ?? (isConfusionMatrix(output) ? metadata.labels : undefined)
    : metadata.sample_labels ?? metadata.labels ?? diagnostics?.sample_labels);
  return Array.isArray(candidate) && candidate.length === rows &&
    candidate.every(label => (typeof label === "string" && label.trim().length > 0) ||
      (typeof label === "number" && Number.isFinite(label)))
    ? candidate.map(String) : [];
}

/** Column identity shared by full tables, Quick Plot and CSV. Shape validates
 * declared axes; it never establishes a sample, class or component role. */
export function scientificMatrixColumns(output: NodeOutput | null | undefined, width: number): string[] {
  const metadata = output?.metadata ?? {};
  const dimensions = output?.descriptor?.dimensions ?? [];
  const column = dimensions[dimensions.length - 1];
  const value = output?.presentation_value as Record<string, unknown> | undefined;
  const axis = (value?.feature_axis ?? value?.x_axis) as Record<string, unknown> | undefined;
  const diagnostics = metadata.diagnostics as Record<string, unknown> | undefined;
  const confusion = isProjectedScientificKind(output, "confusion_matrix") || metadata.type === "ClassificationTest";
  const response = confusion || isProjectedScientificKind(output, "target_matrix") ||
    ["target", "class", "response_class", "actual_class", "predicted_class", "actual_predicted_value"].includes(column?.role ?? "") ||
    ["class_probabilities", "class_response_scores_not_probabilities", "class_distances", "normalized_inverse_distance_affinity_not_probability"]
      .includes(String(metadata.numeric_output_semantics ?? diagnostics?.numeric_output_semantics));
  const component = column?.role === "component" || isProjectedScientificKind(output, "pca_scores") ||
    metadata.scientific_matrix_role === "component_concentrations";
  const candidates = response
    ? [column?.labels, metadata.target_names, confusion ? metadata.labels : null, metadata.classes,
      metadata.label_categories, diagnostics?.target_names,
      diagnostics?.classes, diagnostics?.label_categories, metadata.column_names]
    : component ? [column?.labels, metadata.pc_labels, metadata.labels, axis?.labels, metadata.feature_names]
    : [column?.labels, axis?.labels, metadata.feature_names, metadata.column_names,
      metadata.wavenumbers, Array.isArray(metadata.x_axis) ? metadata.x_axis : (metadata.x_axis as Record<string, unknown> | undefined)?.data, axis?.data];
  const names = candidates.find(value => Array.isArray(value) && value.length === width);
  if (Array.isArray(names)) return names.map(name => scientificColumnLabel(String(name), metadata));
  if (isProjectedScientificKind(output, "pls_explained_variance")) {
    return Array.from({ length: width }, (_, index) => index === 0 ? "X variance" : index === 1 ? "Y variance" : `Domain ${index + 1}`);
  }
  return Array.from({ length: width }, (_, index) => width === 1 ? "Value" : `Col_${index + 1}`);
}
