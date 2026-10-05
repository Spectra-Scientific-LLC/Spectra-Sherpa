export interface ValidationLedgerRow {
  sample: string;
  target?: string;
  reference: unknown;
  predicted: unknown;
  residual?: unknown;
  correct?: boolean;
  role?: string;
}

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const isLabel = (value: unknown): value is string =>
  typeof value === "string" && value.length > 0;

const isObservation = (value: unknown): boolean =>
  isLabel(value) || typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value));

const isRole = (value: unknown): boolean =>
  value === "calibration" || value === "cross_validation" || value === "held_out_test" || value === "unqualified_evaluation";

/** Extract the canonical sample-level true/predicted rows from a saved result. */
export function extractValidationLedgerRows(value: unknown): ValidationLedgerRow[] {
  const root = asRecord(value);
  const presentation = asRecord(root?.presentation_value) ?? root;
  const records = presentation?.data;
  const tableSchema = presentation?.schema_version;
  if (tableSchema === "spectrasherpa-regression-comparison/1"
    || tableSchema === "spectrasherpa-classification-comparison/1") {
    if (!Array.isArray(records) || !Array.isArray(presentation?.shape)
      || presentation.shape[0] !== records.length) return [];
    // A partial ledger must never masquerade as the complete population.
    if (!records.every((raw) => {
      const row = asRecord(raw);
      if (!row || !isLabel(row.sample) || !isRole(row.role)
        || !isObservation(row.reference) || !isObservation(row.predicted)) return false;
      return tableSchema === "spectrasherpa-classification-comparison/1"
        ? typeof row.correct === "boolean"
        : isLabel(row.target) && [row.reference, row.predicted, row.residual].every(
          (number) => typeof number === "number" && Number.isFinite(number),
        );
    })) return [];
    return records.map((raw) => {
      const row = asRecord(raw);
      if (!row) throw new Error("Validated ledger row missing");
      return {
        sample: String(row.sample),
        ...(row.target == null ? {} : { target: String(row.target) }),
        reference: row.reference,
        predicted: row.predicted,
        ...(row.residual == null ? {} : { residual: row.residual }),
        ...(typeof row.correct === "boolean" ? { correct: row.correct } : {}),
        ...(row.role == null ? {} : { role: String(row.role) }),
      };
    });
  }

  const metadata = asRecord(presentation?.metadata) ?? asRecord(root?.metadata);
  if (metadata?.source_schema !== "spectrasherpa-regression-comparison/1") return [];
  if (!Number.isInteger(metadata.n_rows) || (metadata.n_rows as number) < 0) return [];
  const rows: ValidationLedgerRow[] = [];
  const traces = Array.isArray(presentation?.data) ? presentation.data : [];
  for (const trace of traces) {
    const item = asRecord(trace);
    // The canonical producer declares observations as markers. Its 1:1 line
    // is also a scatter trace, but it is presentation geometry, not samples.
    if (!item || item.type !== "scatter" || item.mode !== "markers") continue;
    if (!Array.isArray(item.x) || !Array.isArray(item.y) || !Array.isArray(item.text)
      || !Array.isArray(item.customdata) || !isLabel(item.name)) return [];
    const count = item.x.length;
    if (item.y.length !== count || item.text.length !== count || item.customdata.length !== count) return [];
    for (let index = 0; index < count; index += 1) {
      const detail = item.customdata[index];
      if (!isLabel(item.text[index]) || !Array.isArray(detail) || detail.length !== 2
        || !isRole(detail[1]) || ![item.x[index], item.y[index], detail[0]].every(
          (number) => typeof number === "number" && Number.isFinite(number),
        )) return [];
      rows.push({
        sample: item.text[index],
        target: item.name,
        reference: item.x[index],
        predicted: item.y[index],
        residual: detail[0],
        role: detail[1],
      });
    }
  }
  return rows.length === metadata.n_rows ? rows : [];
}

export function validationLedgerCsv(rows: ValidationLedgerRow[]): string {
  const columns = ["sample", "target", "reference", "predicted", "residual", "correct", "role"] as const;
  const quote = (value: unknown): string => {
    const text = value == null ? "" : String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => quote(row[column])).join(",")),
  ].join("\n");
}

/** Explain why a recognized comparison cannot supply a complete ledger. */
export function validationLedgerUnavailableReason(value: unknown, rows: ValidationLedgerRow[]): string | null {
  if (rows.length) return null;
  const root = asRecord(value);
  const presentation = asRecord(root?.presentation_value) ?? root;
  const metadata = asRecord(presentation?.metadata) ?? asRecord(root?.metadata);
  const records = presentation?.data;
  const comparison = presentation?.schema_version === "spectrasherpa-regression-comparison/1"
    || presentation?.schema_version === "spectrasherpa-classification-comparison/1"
    || metadata?.source_schema === "spectrasherpa-regression-comparison/1"
    || (Array.isArray(records) && records.some((row) => {
      const record = asRecord(row);
      return record && ("reference" in record || "predicted" in record);
    }));
  return comparison
    ? "Validation ledger unavailable: complete, aligned sample identities and prediction rows were not retained."
    : null;
}
