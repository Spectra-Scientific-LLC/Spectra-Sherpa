/* eslint-disable @typescript-eslint/no-explicit-any -- serialized typed projection boundary */
/** A view of retained evidence; never mutates the producing result. */
export function projectActiveSpectralCohort(output: any): {
  output: any;
  population: any;
  error: string | null;
} {
  const unchanged = { output, population: null, error: null };
  if (output?.metadata?.scientific_presentation?.kind !== "spectral_dataset") return unchanged;
  const matrix = output.data;
  const value = output.presentation_value ?? output;
  const rowAxis = value.sample_axis ?? value.y_axis ?? {};
  const colAxis = value.feature_axis ?? value.x_axis ?? {};
  const masked = rowAxis.include_mask != null || colAxis.include_mask != null;
  if (!masked && !Object.keys(rowAxis).length && !Object.keys(colAxis).length) return unchanged;
  const refuse = (error: string) => ({ output: { ...output, data: [] }, population: null, error });
  if (
    !Array.isArray(matrix) ||
    !matrix.length ||
    !Array.isArray(matrix[0]) ||
    !matrix[0].length ||
    matrix.some((row) => !Array.isArray(row) || row.length !== matrix[0].length)
  )
    return refuse("Spectral projection requires a nonempty rectangular retained matrix.");
  const validMask = (mask: unknown, size: number) =>
    mask == null ||
    (Array.isArray(mask) &&
      mask.length === size &&
      mask.every((item) => typeof item === "boolean"));
  if (!validMask(rowAxis.include_mask, matrix.length))
    return refuse("Sample inclusion mask does not match the retained result rows.");
  if (!validMask(colAxis.include_mask, matrix[0].length))
    return refuse("Feature inclusion mask does not match the retained result columns.");
  const rows = matrix
    .map((_: unknown, index: number) => index)
    .filter((index: number) => rowAxis.include_mask?.[index] !== false);
  const cols = matrix[0]
    .map((_: unknown, index: number) => index)
    .filter((index: number) => colAxis.include_mask?.[index] !== false);
  if (!rows.length)
    return refuse("All retained observations are excluded by the sample inclusion mask.");
  if (!cols.length)
    return refuse("All retained features are excluded by the feature inclusion mask.");
  const population = {
    shown: rows.length,
    total: rows.length,
    available: matrix.length,
    excluded: matrix.length - rows.length,
    shown_features: cols.length,
    available_features: matrix[0].length,
    excluded_features: matrix[0].length - cols.length,
    source_row_indices: rows,
    source_feature_indices: cols,
    scope: "active_result_rows",
    table_scope: "active_cohort",
  };
  const axisView = (axis: any, indices: number[], count: number) => {
    const aligned = (items: unknown) => {
      if (!Array.isArray(items) || items.length !== count)
        throw new Error("Axis aligned metadata does not match the retained matrix dimensions.");
      return indices.map((i) => items[i]);
    };
    const view = { ...axis, include_mask: indices.map(() => true) };
    for (const key of [
      "labels",
      "data",
      "values",
      "classes",
      "exclusion_reasons",
      "selection_scores",
    ])
      if (axis[key] != null) view[key] = aligned(axis[key]);
    if (axis.sample_table != null) {
      if (typeof axis.sample_table !== "object" || Array.isArray(axis.sample_table))
        throw new Error("Sample table must contain aligned columns.");
      view.sample_table = Object.fromEntries(
        Object.entries(axis.sample_table).map(([key, values]) => [key, aligned(values)]),
      );
    }
    for (const key of ["alternate_scales", "alternate_label_sets", "class_sets"]) {
      if (axis[key] == null) continue;
      if (!Array.isArray(axis[key]))
        throw new Error("Alternate axis sets must be aligned sequences.");
      view[key] = axis[key].map((set: any) => ({ ...set, values: aligned(set?.values) }));
    }
    return view;
  };
  try {
    const projectedRows = axisView(rowAxis, rows, matrix.length);
    const projectedCols = axisView(colAxis, cols, matrix[0].length);
    const metadata = { ...output.metadata, ...(masked ? { display_population: population } : {}) };
    for (const [keys, indices, count] of [
      [["sample_labels", "labels", "sample_classes"], rows, matrix.length],
      [["wavenumbers", "feature_names"], cols, matrix[0].length],
    ] as const) {
      for (const key of keys)
        if (Array.isArray(metadata[key])) {
          if (metadata[key].length !== count)
            return refuse(
              "Metadata labels or coordinates do not match the retained matrix dimensions.",
            );
          metadata[key] = indices.map((i: number) => metadata[key][i]);
        }
    }
    metadata.sample_labels =
      projectedRows.labels ??
      metadata.sample_labels ??
      metadata.labels ??
      rows.map((i: number) => `Retained row ${i + 1}`);
    if (
      !projectedCols.labels &&
      !projectedCols.data &&
      !projectedCols.values &&
      !metadata.feature_names
    )
      metadata.feature_names = cols.map((i: number) => `Retained feature ${i + 1}`);
    if (projectedCols.data ?? projectedCols.values)
      metadata.wavenumbers = projectedCols.data ?? projectedCols.values;
    if (projectedCols.labels) metadata.feature_names = projectedCols.labels;
    if (projectedCols.title) metadata.x_title = projectedCols.title;
    if (projectedCols.units) metadata.x_units = projectedCols.units;
    const data = rows.map((r: number) => cols.map((c: number) => matrix[r][c]));
    return {
      output: {
        ...output,
        data,
        metadata,
        presentation_value: {
          ...value,
          data,
          sample_axis: projectedRows,
          y_axis: projectedRows,
          feature_axis: projectedCols,
          x_axis: projectedCols,
        },
      },
      population: masked ? population : null,
      error: null,
    };
  } catch (error) {
    return refuse((error as Error).message);
  }
}
