/** Read the Filter node's exact retained selection; never reconstruct identity from values. */
export function sampleSelectionMap(value: unknown, rows: number) {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  if (!Array.isArray(record.provenance)) return null;
  const step = record.provenance[record.provenance.length - 1];
  if (step?.op_id !== "data.filter_samples") return null;
  const params = step.parameters;
  if (!params || !Number.isSafeInteger(params.n_input) || params.n_input < 0
    || !Number.isSafeInteger(params.n_selected) || params.n_selected !== rows) return null;
  const indices: unknown = params.no_filter === true
    ? Array.from({ length: params.n_input }, (_, index) => index) : params.selected_indices;
  if (!Array.isArray(indices) || indices.length !== rows
    || indices.some((index, position) => !Number.isSafeInteger(index) || index < 0
      || index >= params.n_input || (position > 0 && index <= indices[position - 1]))) return null;
  const resultRows = new Map<number, number>(indices.map((index, position) => [index, position + 1]));
  return { inputRows: params.n_input as number, retainedRows: rows, resultRows };
}
