/**
 * The per-sample table for an applied saved model ("Apply Saved Model Artifact").
 *
 * The node's `result` port holds whatever the applied model produces: regression
 * predictions, class responses, or PCA scores. The table names its title and
 * columns only from what the run saved alongside it, never by assumption:
 * regression also saves `y_pred`/`predictions`; classification saves `labels`
 * and `metadata.classes`; PCA saves a scores dataset with its own axis labels.
 * Anything else keeps the saved presentation's label and neutral column names.
 */
export type AppliedCell = number | string | null;

export interface AppliedResultTable {
  title: string;
  columns: string[];
  /** Per column: digits for numeric columns, null for text columns. */
  decimals: Array<number | null>;
  rows: Array<{ sample: string; cells: AppliedCell[] }>;
}

type Dict = Record<string, unknown>;
const isRecord = (value: unknown): value is Dict => !!value && typeof value === "object" && !Array.isArray(value);
const numberOrNull = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);

function matrixOf(value: unknown): unknown[][] | null {
  const data = Array.isArray(value) ? value : isRecord(value) && Array.isArray(value.data) ? value.data : null;
  if (!data) return null;
  return data.map((row) => (Array.isArray(row) ? row : [row]));
}

function axisLabels(value: unknown, width: number): string[] | null {
  if (!isRecord(value)) return null;
  const axis = isRecord(value.x_axis) ? value.x_axis : isRecord(value.feature_axis) ? value.feature_axis : null;
  const labels = axis?.labels;
  return Array.isArray(labels) && labels.length === width && labels.every((label) => typeof label === "string" && label)
    ? (labels as string[]) : null;
}

function numbered(name: string, width: number): string[] {
  return width === 1 ? [name] : Array.from({ length: width }, (_, index) => `${name} ${index + 1}`);
}

export function appliedResultTable(
  values: Dict,
  port: string,
  sampleIds: string[] | null,
  presentationLabel: string | null,
  columnDecimals: (values: unknown[]) => number,
): AppliedResultTable | null {
  if (!sampleIds) return null;
  const finish = (title: string, columns: string[], body: AppliedCell[][], numeric: boolean[]): AppliedResultTable | null => {
    if (body.length !== sampleIds.length || !columns.length || body.some((row) => row.length !== columns.length)) return null;
    const decimals = columns.map((_, index) => (numeric[index] ? columnDecimals(body.map((row) => row[index])) : null));
    return { title, columns, decimals, rows: body.map((cells, index) => ({ sample: sampleIds[index], cells })) };
  };

  if (port === "labels") {
    const labels = values.labels;
    if (!Array.isArray(labels)) return null;
    return finish("Predicted classes", ["Predicted class"], labels.map((label) => [label == null ? null : String(label)]), [false]);
  }
  if (port !== "result") return null;

  const result = values.result;
  const matrix = matrixOf(result);
  const width = matrix?.[0]?.length ?? 0;
  if (!matrix || !width) return null;
  const numericBody = matrix.map((row) => row.map(numberOrNull));
  const metadata = isRecord(values.metadata) ? values.metadata : {};

  // Classification: the predicted class beside one response per saved class.
  if (Array.isArray(values.labels)) {
    const classes = Array.isArray(metadata.classes) && metadata.classes.length === width ? metadata.classes.map(String) : null;
    const responses = classes ?? numbered("Response", width);
    const labels = values.labels as unknown[];
    if (labels.length !== matrix.length) return null;
    // PLS-DA records that its numbers are class-response scores, not probabilities.
    const title = typeof metadata.classification_output_semantics === "string" || isRecord(metadata.classification_output_semantics)
      ? "Class responses" : presentationLabel ?? "Class outputs";
    return finish(title, ["Predicted class", ...responses],
      numericBody.map((row, index) => [labels[index] == null ? null : String(labels[index]), ...row]),
      [false, ...responses.map(() => true)]);
  }
  // Regression: the run also saved the same matrix as its predictions.
  if (values.y_pred !== undefined || values.predictions !== undefined) {
    return finish("Predictions", numbered("Predicted", width), numericBody, numbered("", width).map(() => true));
  }
  // Decomposition scores carry their own component labels (PC1, PC2, …).
  const components = axisLabels(result, width);
  if (components) {
    const title = isRecord(result) && typeof result.title === "string" && result.title ? result.title : presentationLabel ?? "Scores";
    return finish(title, components, numericBody, components.map(() => true));
  }
  return finish(presentationLabel ?? "Applied result", numbered("Column", width), numericBody, numbered("", width).map(() => true));
}
