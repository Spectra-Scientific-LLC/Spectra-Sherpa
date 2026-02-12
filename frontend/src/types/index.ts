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

export interface FileInfoResponse {
  status: string;
  num_spectra: number;
  num_wavenumbers: number;
  wavenumber_min: number | null;
  wavenumber_max: number | null;
  absorbance_min: number | null;
  absorbance_max: number | null;
  labels: string[];
  source: string;
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
}

// Port metadata for node inputs/outputs
export interface NodePortMetadata {
  name: string;  // Port identifier (e.g., "X_train", "y_class", "model")
  type_ref: string;  // Canonical type URI from backend type registry
  required: boolean;
  label: string;  // Display label (e.g., "Training Spectra")
  description?: string;
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
