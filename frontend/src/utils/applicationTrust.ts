/** Project retained application evidence without upgrading a global screen to qualification. */

export type ApplicationTrustRow = {
  sampleIndex: number;
  prediction: unknown;
  status: "outside_global_screen" | "within_global_screen" | "unavailable";
  t2: number | null;
  q: number | null;
  reason: string | null;
};

export type ApplicationTrustView = {
  artifactUid: string;
  modelType: string;
  method: string | null;
  referenceCount: number | null;
  t2Limit: number | null;
  qLimit: number | null;
  claimScope: string;
  rows: ApplicationTrustRow[];
};

const finite = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const array = (value: unknown): unknown[] => Array.isArray(value) ? value : [];

export function applicationTrustView(value: unknown): ApplicationTrustView | null {
  if (!value || typeof value !== "object") return null;
  const result = value as Record<string, unknown>;
  if (typeof result.artifact_uid !== "string" || typeof result.model_type !== "string") return null;
  const indices = array(result.sample_indices);
  const predictions = array(result.predictions);
  if (!indices.length || indices.length !== predictions.length ||
      indices.some(index => !Number.isSafeInteger(index) || (index as number) < 0) ||
      new Set(indices).size !== indices.length) return null;
  const applicability = result.applicability && typeof result.applicability === "object"
    ? result.applicability as Record<string, unknown> : {};
  const plsda = result.model_type === "plsda";
  const pls = result.model_type === "pls";
  const screenedRows = plsda ? array(applicability.rows) : [];
  const outside = pls ? array(applicability.out_of_domain) : [];
  const t2Values = pls ? array(applicability.hotelling_t2) : [];
  const qValues = pls ? array(applicability.q_residuals) : [];
  const rows = indices.map((index, position): ApplicationTrustRow => {
    const diagnostic = screenedRows.length === indices.length && screenedRows[position] &&
      typeof screenedRows[position] === "object" &&
      (screenedRows[position] as Record<string, unknown>).row_index === position
      ? screenedRows[position] as Record<string, unknown> : null;
    const rawStatus = plsda ? diagnostic?.screening_status
      : outside.length === indices.length ? outside[position] === true ? "outside_global_screen"
        : outside[position] === false ? "within_global_screen" : "unavailable" : "unavailable";
    const fittedScope = applicability.claim_scope === "provisional_calibration_screening" &&
      typeof applicability.method === "string" && applicability.method.length > 0;
    const status = fittedScope && (plsda || pls) &&
      (rawStatus === "outside_global_screen" || rawStatus === "within_global_screen")
      ? rawStatus : "unavailable";
    return {
      sampleIndex: index as number,
      prediction: predictions[position],
      status,
      t2: plsda ? finite(diagnostic?.t2) : finite(t2Values[position]),
      q: plsda ? finite(diagnostic?.q) : finite(qValues[position]),
      reason: status === "unavailable" ? String(
        applicability.warning || applicability.unavailable_reason || applicability.t2_unavailable_reason ||
        "No fitted, row-level applicability screen was retained for this model",
      ) : null,
    };
  });
  return {
    artifactUid: result.artifact_uid,
    modelType: result.model_type,
    method: typeof applicability.method === "string" ? applicability.method : null,
    referenceCount: finite(applicability.reference_samples),
    t2Limit: finite(applicability.t2_limit),
    qLimit: finite(applicability.q_limit),
    claimScope: plsda || pls
      ? "Global predictor-space screening only; local support and prediction correctness are unqualified."
      : "No supported fitted predictor-space screening method was retained for this model.",
    rows,
  };
}

/** Operational per-file runs retain the fitted screen as a separate exact node port. */
export function retainedNodeTrustView(modelId: string, screening: unknown, prediction: unknown): ApplicationTrustView | null {
  if (!screening || typeof screening !== "object") return null;
  const record = screening as Record<string, unknown>;
  const plsda = Array.isArray(record.rows);
  const count = plsda ? array(record.rows).length : array(record.out_of_domain).length;
  if (!count || count > 100000 || !Array.isArray(prediction) || prediction.length !== count) return null;
  const view = applicationTrustView({
    artifact_uid: modelId, model_type: plsda ? "plsda" : "pls",
    sample_indices: Array.from({ length: count }, (_, index) => index), predictions: prediction,
    applicability: record,
  });
  return view;
}
