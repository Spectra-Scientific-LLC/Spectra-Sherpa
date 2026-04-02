export type ExperimentStage = "raw" | "preprocessed" | "synthetic";

export interface ExperimentSummary {
  id: number;
  name: string;
  description?: string | null;
  created_at: string;
  file_count: number;
}

export interface ExperimentDetail extends ExperimentSummary {
  metadata: Record<string, unknown>;
}

export interface ExperimentFile {
  id: number;
  file_path: string;
  file_type?: string | null;
  stage: ExperimentStage;
  file_size_bytes?: number | null;
  created_at: string;
}

export interface VersionInfo {
  id: number;
  version_name: string;
  description?: string | null;
  created_at: string;
  parent_version_id?: number | null;
  file_count: number;
}

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

export interface PreprocessResponse {
  status: string;
  data: SpectrumPayload[];
  metadata?: Record<string, unknown> | null;
}

/** SherpaDataset.to_dict() output — same shape used by overlay in NodeDetailView. */
export interface SherpaDatasetDict {
  type?: string;
  data: (number | null)[][];
  n_samples: number;
  n_features: number;
  title?: string;
  units?: string;
  x_axis?: {
    data?: number[];
    labels?: string[];
    title?: string;
    units?: string;
  };
  y_axis?: {
    data?: number[];
    labels?: string[];
    title?: string;
    units?: string;
  };
  is_time_series?: boolean;
  metadata?: Record<string, unknown>;
}

export interface PreprocessSettings {
  align_wavenumbers: boolean;
  wavenumber_alignment_method: string;
  wavenumber_alignment_tolerance: number;
  wavenumber_merge_tolerance: number;
  filter_direction?: "wavenumber" | "time";
  apply_cosmic_ray_removal: boolean;
  cosmic_ray_window: number;
  cosmic_ray_zscore: number;
  apply_savgol: boolean;
  savgol_window: number;
  savgol_polyorder: number;
  apply_range_limit: boolean;
  min_wavenumber?: number | null;
  max_wavenumber?: number | null;
  apply_clip_floor: boolean;
  clip_floor: number;
  apply_scale: boolean;
  scale_max_to: number;
}

export interface BlendResponse {
  status: string;
  wavenumbers: number[];
  times: number[];
  absorbance_matrix: number[][];
  statistics: Record<string, number>;
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

export interface JobInfo {
  id: number;
  job_type: string;
  status: string;
  progress: number;
  progress_message?: string | null;
  result_path?: string | null;
  error_message?: string | null;
  compute_location: string;
  compute_node?: string | null;
  last_heartbeat?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface LlmMessage {
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
  role: "user" | "assistant" | "system";
  content: string;
  recommendations?: SherpaRecommendationPayload[];
}

export interface SherpaRecommendationPayload {
  suggestion_id: string;
  workflow_id: number;
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
  param_type: "number" | "boolean" | "select" | "text";
  default?: unknown;
  min_value?: number;
  max_value?: number;
  step?: number;
  options?: Array<{ label: string; value: unknown }>;
  description?: string;
  required: boolean;
  category?: "basic" | "advanced";  // Parameter complexity level
  visible_when?: Record<string, string[]>;  // Conditional visibility rules
}

// Port metadata for node inputs/outputs
export interface NodePortMetadata {
  name: string;  // Port identifier (e.g., "X_train", "y_class", "model")
  type_ref: string;  // Canonical type URI from backend type registry
  required: boolean;
  label: string;  // Display label (e.g., "Training Spectra")
  description?: string;
  variadic?: boolean;  // True = accepts multiple incoming edges (list input)
}

// Node metadata from backend
export interface NodeTypeMetadata {
  node_type: string;
  category: string;
  label: string;
  description: string;
  parameters: NodeParameterMetadata[];
  input_types: string[];  // Legacy - for backwards compatibility
  output_type: string;  // Legacy - for backwards compatibility
  input_ports?: NodePortMetadata[];  // Named input ports (if multi-input node)
  output_ports?: NodePortMetadata[];  // Named output ports (if multi-output node)
  diagnostics?: string[];  // Diagnostic metric names emitted by this node
}

// Node library response from backend
export interface NodeLibraryResponse {
  nodes: NodeTypeMetadata[];
  total: number;
  version?: string; // Backend API version for cache invalidation
}

// Node execution state (stored per node in workflow)
export interface NodeExecutionState {
  status: NodeExecutionStatus;
  error_message?: string | null;
  error_details?: string | null;  // Full stack trace for "Show Details"
  last_executed?: string | null;  // ISO timestamp
  output_shape?: number[] | null;  // e.g., [1000, 50] for dimensions
  output_type?: string | null;  // e.g., "NDDataset", "PCA"
}

// Validation error
export interface ValidationError {
  param_name: string;
  message: string;
}

// ── Execution Runs (Experiments page) ───────────────────────────

export interface ExecutionRunSummary {
  id: number;
  workflow_id: number;
  workflow_version_id: number | null;
  name: string;
  status: string;
  results_summary: Record<string, Record<string, unknown>>;
  integrity_hash: string | null;
  executed_at: string;
  created_at: string;
  error: string | null;
  notes: string | null;
  labels: string[] | null;
  source_type: string | null;
  source_metadata: Record<string, unknown> | null;
  model_ids: string[] | null;
}

export interface ExecutionRunDetail extends ExecutionRunSummary {
  user_id: number;
  params_snapshot: Record<string, Record<string, unknown>>;
  diagnostics: Record<string, Record<string, unknown>> | null;
  node_statuses: Record<string, string> | null;
}

export interface ComparisonResult {
  runs: ExecutionRunDetail[];
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
  created_at: string;
}

export interface FolderWatch {
  id: number;
  user_id: number;
  workflow_id: number;
  name: string;
  folder_path: string;
  file_pattern: string;
  poll_interval_sec: number;
  is_enabled: boolean;
  processed_files: Record<string, string> | null;
  last_poll_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface BatchPredictRequest {
  folder_path: string;
  file_pattern?: string;
  run_name?: string;
}

export interface BatchPredictResponse {
  job_id: number;
  run_id: number;
  message: string;
}

// ── Projects ────────────────────────────────────────────────────────

export interface ProjectSummary {
  id: number;
  name: string;
  description: string | null;
  parent_id: number | null;
  technique: string | null;
  sample_type: string | null;
  experiment_count: number;
  workflow_count: number;
  script_count: number;
  model_count: number;
  children_count: number;
  version_count: number;
  created_at: string;
  updated_at: string;
}

export interface ExperimentBrief {
  id: number;
  name: string;
  description: string | null;
  file_count: number;
}

export interface WorkflowBrief {
  id: number;
  name: string;
  description: string | null;
  status: string;
  integrity_hash: string | null;
}

export interface ScriptBrief {
  id: number;
  name: string;
  description: string | null;
  language: string;
  priority: number;
  source_workflow_id: number | null;
  code_length: number;
}

export interface ModelBrief {
  artifact_uid: string;
  name: string;
  model_type: string;
  n_features: number;
  n_components: number | null;
  metrics: Record<string, unknown> | null;
  created_at: string;
}

export interface ProjectScriptSummary {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  language: string;
  priority: number;
  source_workflow_id: number | null;
  code_length: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectScriptDetail extends ProjectScriptSummary {
  code: string;
}

export interface ProjectDetail extends ProjectSummary {
  metadata: Record<string, unknown>;
  experiments: ExperimentBrief[];
  workflows: WorkflowBrief[];
  scripts: ScriptBrief[];
  models: ModelBrief[];
  children: ProjectSummary[];
}

export interface ProjectCreate {
  name: string;
  description?: string | null;
  parent_id?: number | null;
  metadata?: Record<string, unknown>;
  technique?: string | null;
  sample_type?: string | null;
}

export interface ProjectUpdate {
  name?: string | null;
  description?: string | null;
  parent_id?: number | null;
  metadata?: Record<string, unknown>;
  technique?: string | null;
  sample_type?: string | null;
}

export interface ProjectVersionSummary {
  id: number;
  version_number: number;
  change_description: string | null;
  include_raw_data: boolean;
  created_at: string;
  created_by: number;
}

export interface ProjectVersionDetail extends ProjectVersionSummary {
  snapshot: Record<string, unknown>;
}

export interface SaveProjectRequest {
  change_description?: string | null;
  include_raw_data?: boolean;
}
