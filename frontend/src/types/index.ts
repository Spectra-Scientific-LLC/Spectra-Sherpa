import type { components } from "./api/v1";

export type ExperimentStage = "raw" | "preprocessed" | "synthetic";

/** UI projection: the adapter supplies the schema's default file count. */
export type ExperimentSummary = components["schemas"]["ExperimentSummary"] & { file_count: number };

export type ExperimentDetail = components["schemas"]["ExperimentDetail"] & { file_count: number };

/** Historical rows may lack file metadata; their remaining fields derive from transport. */
export type ExperimentFile = Omit<components["schemas"]["ExperimentFileOut"], "file_type" | "file_size_bytes">
  & Partial<Pick<components["schemas"]["ExperimentFileOut"], "file_type" | "file_size_bytes">>;

export type ScientificAsset = components["schemas"]["ScientificAssetOut"] & { warnings: string[] };

export type ExperimentFileAssets = Omit<components["schemas"]["ExperimentFileAssetsOut"], "assets"> & {
  assets: ScientificAsset[];
};

export type VersionInfo = components["schemas"]["VersionInfo"];

export interface SpectrumPayload {
  label: string;
  file_path?: string | null;
  wavenumber?: number[] | null;
  absorbance?: number[] | null;
  source?: string;
  model_type?: string | null;
  model_at_wavenumber?: Array<string | null> | null;
  slope?: Array<number | null> | null;
  intercept?: Array<number | null> | null;
  s?: Array<number | null> | null;
  p?: Array<number | null> | null;
  c?: Array<number | null> | null;
  reference_concentration?: number | null;
  concentration_mode?: string | null;
  x_label?: string | null;
  x_unit?: string | null;
  pathlength_m?: number | null;
}

/** SherpaDataset.to_dict() output — same shape used by overlay in NodeDetailView. */
export interface SherpaDatasetDict {
  type?: string;
  version?: string;
  dataset_id?: string;
  shape?: number[];
  ndim?: number;
  /** API data may be n-D; consumers must inspect `shape`/`ndim` before treating rows as 2-D. */
  data: any[];
  n_samples: number;
  n_features: number;
  title?: string;
  units?: string;
  data_role?: string | null;
  x_axis?: import("@/utils/datasetAxisSets").DatasetAxisWire;
  y_axis?: import("@/utils/datasetAxisSets").DatasetAxisWire & {
    classes?: unknown[];
    exclusion_reasons?: Array<string | null>;
  };
  sample_axis?: import("@/utils/datasetAxisSets").DatasetAxisWire;
  inner_axes?: Record<string, import("@/utils/datasetAxisSets").DatasetAxisWire>;
  target?: unknown[] | unknown[][] | null;
  target_context?: {
    target_type?: string | null;
    target_name?: string | null;
    target_names?: string[] | null;
    target_units?: string | null;
    class_names?: string[] | null;
    n_classes?: number | null;
    selected_target?: string | null;
    reference_value_evidence?: ReferenceValueEvidence | null;
  };
  domain?: {
    technique?: string | null;
    instrument?: string | null;
    expected_units?: string | null;
    data_quantity?: string | null;
  };
  is_time_series?: boolean;
  descriptive?: Record<string, unknown>;
  source_identity?: Record<string, unknown>;
  source_history?: Record<string, unknown>;
  layout?: Record<string, unknown>;
  scientific_projection?: Record<string, unknown>;
  manifest?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  analysis_readiness?: DatasetAnalysisReadiness;
  analysis_binding?: {
    revision: string;
    sample_table_file_id: number;
    selected_target: string;
    target_type: "continuous" | "categorical";
    reference_declaration?: ReferenceValueDeclaration;
  };
}

export type ReferenceValueDeclaration = components["schemas"]["ReferenceValueDeclaration"];

/** Unvalidated laboratory JSON from the editor; server admission remains authoritative. */
export interface ReferenceDeclarationDraft extends Omit<ReferenceValueDeclaration, "method"> {
  method: (Omit<NonNullable<ReferenceValueDeclaration["method"]>, "precision"> & {
    precision: Record<string, unknown> | null;
  }) | null;
}

export interface ReferenceValueEvidence {
  schema_version: "spectrasherpa.reference-value-evidence/1";
  source_file_id: number;
  sample_table_file_id: number;
  sample_table_sha256: string;
  target_name: string;
  target_type: "continuous" | "categorical";
  units: string | null;
  method: ReferenceValueDeclaration["method"];
  provenance: string | null;
  precision_study_provenance: string | null;
  replicate_evidence_digest: string | null;
  source_included_count: number;
  missing_included_count: number;
  missing_excluded_count: number;
  instrument_repeatability: null;
  qualification_gaps: string[];
}

export interface AcquisitionPlan {
  schema_version: "spectrasherpa-acquisition-plan/3";
  experiment_id: number;
  plate_format_id: components["schemas"]["PlateFormatId"];
  plate_format_label: string;
  capacity: number;
  revision: string;
  samples: PlannedSample[];
  mixtures: PlannedMixture[];
  factors: PlannedFactor[];
  wells: AcquisitionPlanWell[];
  acquisition_order: AcquisitionOrderStep[];
  matching: AcquisitionMatching;
}

export type PlannedSample = components["schemas"]["PlannedSample"];

export type MixtureComponent = components["schemas"]["MixtureComponent"];

export type PlannedMixture = components["schemas"]["PlannedMixture"];

export type PlannedFactor = components["schemas"]["PlannedFactor"];

export type AcquisitionPlanWell = components["schemas"]["AcquisitionPlanWell"];

export type AcquisitionOrderStep = components["schemas"]["AcquisitionOrderStep"];

export type AcquisitionMatch = components["schemas"]["AcquisitionMatch"];

export type AcquisitionMatching = components["schemas"]["AcquisitionMatching"];

export interface MeasuredSampleTableEditor {
  schema_version: "spectrasherpa.sample-table-editor/1";
  source_file_id: number;
  revision: string;
  sample_table_file_id: number;
  selected_target: string;
  reference_declaration?: ReferenceValueDeclaration;
  target_definitions: Array<{
    name: string;
    type: "continuous" | "categorical";
  }>;
  annotation_columns: string[];
  plate_format_id: components["schemas"]["PlateFormatId"];
  rows: Array<{
    row_index: number;
    source_file_id: number;
    sample_id: string;
    include: boolean;
    targets: Record<string, string>;
    plate_id: string;
    well: string;
    annotations: Record<string, string>;
  }>;
}

export interface DatasetAnalysisReadinessReason {
  code: string;
  message: string;
  role: string | null;
}

export interface DatasetAnalysisReadinessDecision {
  template_slug: string;
  template_name: string;
  category: string;
  display_status:
    | "compatible"
    | "needs_target"
    | "needs_source"
    | "incompatible"
    | "pending"
    | "unavailable";
  status: "compatible" | "needs_input" | "incompatible" | "pending";
  reason_codes: string[];
  reasons: DatasetAnalysisReadinessReason[];
}

export interface DatasetAnalysisReadiness {
  independence?: {
    checked: boolean;
    violations: Array<{ code: string; field: string | null; message: string }>;
    suggested_groups: string[];
  };
  schema_version: "spectra-sherpa-dataset-analysis-readiness/1";
  scope: "structural";
  status: "ready" | "partial" | "unavailable";
  profile: {
    primary_role: string;
    modality: "spectra" | "features" | "hsi";
    technique: string;
    target_type: "continuous" | "categorical" | "ordinal" | null;
    target_fields: string[];
    identity_fields: string[];
    group_fields: string[];
    ordered_samples: boolean;
  } | null;
  template_count: number;
  counts: Record<
    "compatible" | "needs_target" | "needs_source" | "incompatible" | "pending" | "unavailable",
    number
  >;
  decisions: DatasetAnalysisReadinessDecision[];
  diagnostics: Array<{ code: string; message: string; detail: string }>;
}

/** One selected file or aggregate package admitted to a display-only plot. */
export interface DatasetPlotMember {
  /** Optional presentation grouping; never replaces sample or source identity. */
  curveGroupLabel?: string;
  /** Display-only color shared by a selection box and its spectra. */
  curveGroupColor?: string;
  fileId: number | null;
  fileName: string;
  dataset: SherpaDatasetDict;
}

/** One packaged dataset contributing selected members to the shared plot. */
export interface DatasetPlotSource {
  experimentId: number;
  name: string;
  members: DatasetPlotMember[];
  selectedFileCount: number;
  totalFileCount: number;
  selectedFileNames?: string[];
}

export interface CurvePoint {
  x: number;
  y: number;
}

export interface CurveSegment {
  startX: number;
  endX: number;
  xCoeffs: number[];
  yCoeffs: number[];
}

export interface CalibrationSummary {
  id: number;
  compound_name: string;
  concentration_mode: string;
  x_unit: string;
  pathlength_m?: number | null;
  created_at: string;
}

export interface CalibrationDetail extends CalibrationSummary {
  metadata: Record<string, unknown>;
}

export interface CalibrationFileOut {
  id: number;
  file_path: string;
  concentration: number;
  created_at: string;
}

export interface CalModelInfo {
  id: number;
  version_name: string;
  model_type: string;
  model_path: string;
  r_squared?: number | null;
  rmse?: number | null;
  is_active: boolean;
  created_at: string;
}

export interface NistSearchResult {
  name: string;
  cas_number?: string | null;
  nist_id: string;
}

export interface NistLibraryEntry {
  id: number;
  cas_number: string;
  compound_name: string;
  resolution: string;
  file_path: string;
  downloaded_at: string;
}

export type JobInfo = components["schemas"]["JobInfo"];

export interface LlmMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updatedAt: string;
}

// ── Sherpa Advisor Types ──────────────────────────────────────

export interface SherpaMessage {
  diagnostic_scope?: import("@/utils/diagnosticAdvisor").DiagnosticScope;
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  recommendations?: SherpaRecommendationPayload[];
  memoryScopes?: string[];
  followUps?: string[];
}

export interface SherpaResumeRecap {
  projectId: number;
  recap: string;
  lastActiveAt: string | null;
  cached: boolean;
}

export interface SherpaRecommendationPayload {
  suggestion_id: string;
  workflow_id: number | null;
  category: string;
  title: string;
  explanation: string;
  confidence: number;
  status: string;
  created_at: string;
  has_patch: boolean;
}

// Node execution states
export type NodeExecutionStatus = "pending" | "running" | "completed" | "error" | "stale";

// Node parameter metadata from backend
export interface NodeParameterMetadata {
  name: string;
  label: string;
  param_type: "number" | "boolean" | "select" | "text" | "string_list";
  default?: unknown;
  min_value?: number;
  max_value?: number;
  max_value_reason?: string;
  step?: number;
  options?: Array<{ label: string; value: unknown }>;
  description?: string;
  required: boolean;
  category?: "basic" | "advanced" | "internal"; // Internal bindings are populated by custody/import, not scientists.
  visible_when?: Record<string, string[]>; // Conditional visibility rules
}

// Port metadata for node inputs/outputs
export interface NodePortMetadata {
  name: string; // Port identifier (e.g., "X_train", "y_class", "model")
  type_ref: string; // Canonical type URI from backend type registry
  required: boolean;
  label: string; // Display label (e.g., "Training Spectra")
  description?: string;
  variadic?: boolean; // True = accepts multiple incoming edges (list input)
  accepted_data_roles?: string[] | null; // Dataset roles accepted by this port
}

// Exact immutable execution contract supplied by the live node registry.
// An absent contract means that the node is local-only and cannot enter a
// managed campaign; the UI does not infer authority from a node name.
export interface NodeExecutionContract {
  digest: string;
  payload: Record<string, unknown>;
}

export type ScientificPresentationMode = "model_summary" | "plot" | "record" | "table";

export interface ScientificPresentation {
  input_binding?: [string, "feature_axis" | "cluster_feature_axes" | "sample_axis"];
  output_binding?: [string, "target_context" | "feature_axis"];
  sample_labels_field?: string;
  presentation_id: string;
  label: string;
  kind: string;
  source_ports: string[];
  modes: ScientificPresentationMode[];
  description: string;
}

export interface NodePresentationContractPayload {
  schema_version: "spectrasherpa-node-presentation/1";
  default_presentation: string;
  presentations: ScientificPresentation[];
}

export interface NodePresentationContract {
  digest: string;
  payload: NodePresentationContractPayload;
}

export interface NodeDependencyReadiness {
  ready: boolean;
  blockers: string[];
  remediation: string[];
}

export interface NodeCatalogClassification {
  contract_status: string;
  runtime_family: string;
  lifecycle_kind: string;
  typed_port_status: string;
  managed_optimization_eligible: boolean;
  reason: string;
}

export interface NodeManagedOptimizationProfile {
  profile_id: string;
  profile_version: string;
  profile_digest: string;
  eligible: boolean;
  reason: string;
}

// Node metadata from backend
export interface NodeTypeMetadata {
  node_type: string;
  category: string;
  label: string;
  description: string;
  parameters: NodeParameterMetadata[];
  input_types: string[]; // Legacy - for backwards compatibility
  output_type: string; // Legacy - for backwards compatibility
  input_ports?: NodePortMetadata[]; // Named input ports (if multi-input node)
  output_ports?: NodePortMetadata[]; // Named output ports (if multi-output node)
  diagnostics?: string[]; // Diagnostic metric names emitted by this node
  execution_contract?: NodeExecutionContract | null;
  presentation_contract?: NodePresentationContract | null;
  dependency_readiness?: NodeDependencyReadiness;
  requires_scp?: boolean;
  catalog_classification?: NodeCatalogClassification;
  managed_optimization_profile?: NodeManagedOptimizationProfile;
}

// Node library response from backend
export interface NodeLibraryResponse {
  nodes: NodeTypeMetadata[];
  total: number;
  version?: string; // Backend API version for cache invalidation
  contract_schema_version?: string;
  registry_digest?: string;
  cache_identity?: string;
}

// Node execution state (stored per node in workflow)
export interface NodeExecutionState {
  status: NodeExecutionStatus;
  error_message?: string | null;
  error_details?: string | null; // Full stack trace for "Show Details"
  last_executed?: string | null; // ISO timestamp
  output_shape?: number[] | null; // e.g., [1000, 50] for dimensions
  output_shape_label?: string | null; // scientific material represented by output_shape
  output_type?: string | null; // e.g., "SherpaDataset", "PCA"
}

// ── Execution Runs (workflow run history) ───────────────────────

export interface ExecutionRunSummary {
  id: number;
  project_id: number | null;
  workflow_id: number | null;
  workflow_version_id: number | null;
  name: string;
  status: string;
  params_snapshot: components["schemas"]["ExecutionRunOut"]["params_snapshot"];
  results_summary: components["schemas"]["ExecutionRunOut"]["results_summary"];
  integrity_hash: string | null;
  executed_at: string;
  created_at: string;
  error: string | null;
  notes: string | null;
  labels: string[] | null;
  source_type: string | null;
  source_metadata: Record<string, unknown> | null;
  produced_artifact_uids: string[] | null;
  run_kind: NonNullable<components["schemas"]["ExecutionRunOut"]["run_kind"]>;
  attempted_artifact_uids: string[] | null;
  succeeded_artifact_uids: string[] | null;
}

export interface ExecutionRunDetail extends ExecutionRunSummary {
  environment_snapshot?: Record<string, unknown> | null;
  user_id: number;
  diagnostics: Record<string, Record<string, unknown>> | null;
  node_statuses: Record<string, string> | null;
}

export type RunListItem = Pick<
  ExecutionRunSummary,
  | "id"
  | "project_id"
  | "workflow_id"
  | "workflow_version_id"
  | "name"
  | "status"
  | "run_kind"
  | "executed_at"
  | "created_at"
  | "labels"
  | "produced_artifact_uids"
  | "attempted_artifact_uids"
  | "succeeded_artifact_uids"
> & { display_name?: string | null; workflow_name?: string | null };

export type EvaluationSelections = Record<number, { node_id: string; presentation_id: string }>;

export type ComparisonResultPair = components["schemas"]["ComparisonResultPair"];

export interface ComparisonResult {
  scientific_comparison?: import("./scientificComparison").EvidenceComparison | null;
  result_pairs?: ComparisonResultPair[];
  runs: ExecutionRunDetail[];
  rankable_metric_keys?: string[];
  metric_keys: string[];
  diff: Record<string, Record<string, unknown>>;
}

// ── Deploy (Batch Predictions + Folder Watches) ──────────────────

export interface BatchPredictionResult {
  id: number;
  run_id: number;
  file_name: string;
  file_path: string;
  status: string;
  results: Record<string, unknown> | null;
  error_message: string | null;
  processing_time_ms: number | null;
  model_id: string | null;
  retained_node_ids?: string[];
  created_at: string;
}

export type FolderWatch = components["schemas"]["FolderWatchOut"];

/**
 * One releaseable application target on the Deploy surface.
 *
 * `application_id` is the stable release handle on current servers. The
 * `artifact:<uid>` and `canonical:<id>` forms remain compatibility identities
 * while older Workbenches roll forward to the release registry.
 */
export interface DeployApplication {
  campaign_validation_recorded?: boolean;
  application_id: string;
  application_handle?: string | null;
  origin: "saved_run" | "portable";
  name: string;
  workflow_id: number;
  workflow_version_id: number | null;
  artifact_uid: string | null;
  canonical_artifact_id: number | null;
  artifact_digest?: string | null;
  source_run_id?: number | null;
  deploy_ready: boolean;
  refusal?: string | null;
}

/** Identity returned by a canonical import for the Deploy hand-off. */
export type ImportedApplicationIdentity = components["schemas"]["ImportedApplicationIdentity"];

// ── Projects ────────────────────────────────────────────────────────

export type StarterProgressSignal =
  | "has_project"
  | "has_data"
  | "has_workflow"
  | "has_preprocessing"
  | "has_executed"
  | "has_model";

export type StarterStep = components["schemas"]["StarterStep"];

/** A dataset a Starter plan can begin with: a reference or the user's own. */
export type StarterDatasetOption = components["schemas"]["StarterDatasetOption"];

export type StarterDatasetChoice = components["schemas"]["StarterDatasetChoice"];

/** A goal turned into ordered steps; stored on the project as ``goal_plan``. */
export type StarterPlan = components["schemas"]["StarterPlan"];

/** The project adapter fills the backend defaults required by the view. */
export type ProjectSummary = components["schemas"]["ProjectSummary"] & Required<Pick<
  components["schemas"]["ProjectSummary"],
  "description" | "parent_id" | "technique" | "sample_type" | "experiment_count" |
  "workflow_count" | "script_count" | "model_count" | "children_count" | "version_count"
>>;

export type ExperimentBrief = components["schemas"]["ExperimentBrief"];

export type WorkflowBrief = components["schemas"]["WorkflowBrief"];

export type ProjectDataSource = Required<components["schemas"]["ProjectDataSourceOut"]>;

export type AdvisorChannel = Required<components["schemas"]["AdvisorChannelOut"]>;

export type ScriptBrief = components["schemas"]["ScriptBrief"];

export type ModelBrief = components["schemas"]["ModelBrief"];

export type ProjectScriptSummary = components["schemas"]["ProjectScriptSummary"];

export type ProjectScriptDetail = components["schemas"]["ProjectScriptDetail"];

export type ProjectDetail = ProjectSummary & Required<Pick<components["schemas"]["ProjectDetail"],
  "metadata" | "experiments" | "workflows" | "scripts" | "models">> &
  Pick<components["schemas"]["ProjectDetail"], "application" | "application_handle"> & {
  data_sources: ProjectDataSource[];
  advisor_channels: AdvisorChannel[];
  children: ProjectSummary[];
};

export type ProjectCreate = components["schemas"]["ProjectCreate"];

export type ProjectUpdate = components["schemas"]["ProjectUpdate"];

export type ProjectVersionSummary = components["schemas"]["ProjectVersionSummary"];

export type ProjectVersionDetail = components["schemas"]["ProjectVersionDetail"];
