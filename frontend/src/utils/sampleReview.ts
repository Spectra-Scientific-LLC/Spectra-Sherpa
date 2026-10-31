import type { ReviewCurationSource } from "./datasetCuration";
/** Exact identities only. Plot positions, labels and trace numbers are never keys. */
export interface ReviewRow {
  id: string;
  /** Optional retained GUI text, never a selection/join/decision identity. */
  display_label?: string;
  role: "calibration" | "excluded_projected" | "held_out_test";
  group: string;
  reference?: number[];
  predicted?: number[] | null;
  residual?: number[] | null;
  scores: number[] | null;
  t2: number | null;
  q: number | null;
  screened?: boolean;
  outside_t2?: boolean | null;
  outside_q?: boolean | null;
  screening_status?: "outside_global_screen" | "within_global_screen" | "unavailable";
  applicability_unavailable_reason?: string | null;
  projection_error?: string;
}
/** Old receipts and unavailable labels retain their exact ID fallback. */
export function reviewRowLabel(
  row: Pick<ReviewRow, "id" | "display_label"> | undefined,
  fallbackId = "",
): string {
  return typeof row?.display_label === "string" && row.display_label.trim()
    ? row.display_label
    : row?.id ?? fallbackId;
}
export interface RegressionStatistics {
  targets: Array<{
    target: string;
    metrics: { n_samples: number; rmse: number; r2: number | null; bias: number };
  }>;
}
export interface SpectralDisplay {
  x: number[];
  units: string;
  signal_units?: string;
  variable_count: number;
  display_count: number;
  rows: Record<string, Array<number | null>>;
  missing_ids?: string[];
  space?: string;
  downsampled?: boolean;
}
export interface ExecutedPreprocessingStep {
  node_id: string;
  operation: string;
  parameters: Record<string, unknown>;
  fitting_population: "sample_local" | "retained_calibration";
  fitted_state_sha256?: string;
  fitting_ids_sha256?: string;
  fitting_count?: number;
}
export interface ExecutedSplit {
  method: string;
  test_size: number;
  random_seed: number;
  plan_digest: string;
  groups_content_digest: string | null;
  n_groups: number | null;
  n_train: number;
  n_test: number;
}
export interface PcaExplanationDetail {
  schema_version: string;
  model_digest: string;
  feature_identity: string;
  reference_digest: string;
  reference_count: number;
  formula: string;
  space: string;
  preprocessing: string[];
  feature_count: number;
  feature_labels: string[] | null;
  feature_values: number[] | null;
  feature_units: string;
  top_per_statistic: number;
  loadings: number[][] | null;
  loadings_unavailable_reason: string | null;
  rows: Record<
    string,
    {
      variables: [number, number, number][];
      q_total: number;
      t2_total: number;
      omitted_q: number;
      omitted_t2: number;
      omitted_t2_absolute: number;
    }
  >;
}
export type PcaExplanations = PcaExplanationDetail | { unavailable_reason: string };

export interface PlsExplanationDetail {
  schema_version: string;
  model_digest: string;
  feature_identity: string;
  reference_digest: string;
  reference_count: number;
  response_identity: { names: string[] | null; units: Array<string | null> };
  baseline: number[];
  formula: string;
  preprocessing: string[];
  internal_scale: boolean;
  feature_count: number;
  feature_labels: string[] | null;
  feature_values: number[] | null;
  feature_units: string;
  signal_units: string | null;
  top_per_response: number;
  coefficients: number[][] | null;
  loadings: number[][] | null;
  vip: number[] | null;
  profiles_unavailable_reason: string | null;
  rows: Record<
    string,
    Array<{
      variables: [number, number][];
      prediction: number;
      contribution_total: number;
      omitted_signed: number;
      omitted_absolute: number;
    }>
  >;
}
export type PlsExplanations = PlsExplanationDetail | { unavailable_reason: string };

export interface PlsApplicabilityDetail {
  schema_version: string;
  model_digest: string;
  source_contract_digest: string;
  feature_identity: string;
  reference_digest: string;
  reference_count: number;
  components: number;
  score_covariance_rank: number;
  rank_tolerance: number;
  confidence: number;
  calibration_t2_limit: number | null;
  application_t2_limit: number | null;
  calibration_t2_limit_method: string;
  application_t2_limit_method: string;
  q_limit: number | null;
  q_limit_method: string;
  q_numerical_tolerance: number;
  t2_unavailable_reason: string | null;
  q_unavailable_reason: string | null;
  neighborhood_support: string;
  claim_scope: string;
  internal_scale: boolean;
  score_units: string;
  q_units: string;
  space: string;
  preprocessing: string[];
  feature_count: number;
  feature_values: number[] | null;
  feature_units: string;
  signal_units: string | null;
  top_per_statistic: number;
  formula: string;
  contribution_formula: string;
  rows: Record<
    string,
    {
      variables: [number, number, number | null][];
      q_total: number;
      t2_total: number | null;
      omitted_q: number | null;
      omitted_t2: number | null;
      omitted_t2_absolute: number | null;
      decomposition_unavailable_reason?: string | null;
    }
  >;
}
export type PlsApplicability = PlsApplicabilityDetail | { unavailable_reason: string };
/** Screening describes predictor novelty, not response accuracy or local support. */
export function plsScreeningLabel(row: ReviewRow): string {
  if (row.projection_error) return row.projection_error;
  const flags = [
    row.outside_t2 ? "T² above limit" : "",
    row.outside_q ? "Q above limit" : "",
  ].filter(Boolean);
  if (flags.length)
    return (
      flags.join("; ") +
      (row.outside_t2 == null || row.outside_q == null ? "; partial screening" : "")
    );
  if (row.screening_status === "within_global_screen")
    return "Within global screen — local support unknown";
  return row.applicability_unavailable_reason || "Screening unavailable";
}

export interface PcaReview {
  pls_applicability?: PlsApplicability;
  pls_explanations?: PlsExplanations;
  explanations?: PcaExplanations;
  dataset_curation_source?: ReviewCurationSource | null;
  model_kind?: "pca" | "pls";
  target_names?: string[];
  target_units?: Array<string | null>;
  spectra?: SpectralDisplay;
  source_spectral_space?: string;
  model_input_spectra?: SpectralDisplay | { unavailable_reason: string };
  model_input_spectral_space?: string;
  model_input_signal_units?: string;
  model_input_axis_units?: string;
  preprocessing?: ExecutedPreprocessingStep[];
  executed_split?: ExecutedSplit | null;
  heldout_ids?: string[];
  full_test_statistics?: RegressionStatistics | null;
  review_subset_statistics?: RegressionStatistics | null;
  calibration_statistics?: RegressionStatistics | null;
  run_id: number;
  latest_run_id: number;
  revision: number;
  graph_digest: string;
  source_digest: string;
  stale: boolean;
  rows: ReviewRow[];
  n_components: number;
  n_calibration: number;
  calibration_t2_limit: number;
  application_t2_limit: number;
  q_limit: number;
  q_limit_method: string;
  state: {
    marked: string[];
    excluded: string[];
    heldout_excluded?: string[];
    post_review?: boolean;
    test_baseline?: { run_id: number; statistics: RegressionStatistics | null };
  };
  history: Array<{
    revision: number;
    action: string;
    reason: string;
    sample_ids: string[];
    run_id: number;
  }>;
}
export function selectedSampleIds(event: unknown, allowed: ReadonlySet<string>): string[] {
  const points = (event as { points?: Array<{ customdata?: unknown }> } | null)?.points;
  if (!Array.isArray(points)) return [];
  return [
    ...new Set(
      points
        .map((p) => p.customdata)
        .filter((id): id is string => typeof id === "string" && allowed.has(id)),
    ),
  ];
}
export function selectionIndices(
  data: Record<string, unknown>[],
  selected: ReadonlySet<string>,
): number[][] {
  return data.map((trace) =>
    Array.isArray(trace.customdata)
      ? trace.customdata.flatMap((id, i) => (typeof id === "string" && selected.has(id) ? [i] : []))
      : [],
  );
}
