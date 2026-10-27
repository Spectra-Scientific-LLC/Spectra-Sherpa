import type { NodeOutput } from "./nodeOutput";
import { isProjectedScientificKind } from "./scientificPresentation";
import { scientificColumnLabel } from "./scientificDisplay";

/** Labels belong to this result's row axis, not a similarly sized input. */
export function scientificMatrixRowLabels(output: NodeOutput | null | undefined, rows: number): string[] {
  const value = output?.presentation_value as Record<string, unknown> | undefined;
  const axis = (value?.sample_axis ?? value?.y_axis) as Record<string, unknown> | undefined;
  const metadata = output?.metadata ?? {};
  const diagnostics = metadata.diagnostics as Record<string, unknown> | undefined;
  const candidate = output?.descriptor?.dimensions?.[0]?.labels ?? axis?.labels ??
    metadata.sample_labels ?? metadata.labels ?? diagnostics?.sample_labels;
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
