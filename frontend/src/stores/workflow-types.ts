/**
 * Type definitions for the workflow store.
 *
 * Extracted from workflow.ts for module size reduction.
 * All types are re-exported from workflow.ts for backward compatibility.
 */

import type {
  NodeExecutionState,
  ExperimentStage,
  NodePresentationContract,
  ScientificPresentation,
} from "@/types";

export type ParamsMap = Record<string, unknown>;
export type UnknownRecord = Record<string, unknown>;
export type DataModality = "spectra" | "features" | "hsi";
export type TemplateStatus = "ready" | "pending_data" | "pending_qualification" | "wip";
export type CompatibilityStatus = "compatible" | "needs_input" | "incompatible" | "pending";

export interface DatasetAnalysisProfile {
  primary_role: "X_spectra" | "X_features" | "X_hsi";
  modality: DataModality;
  technique: string;
  target_type: "continuous" | "categorical" | "ordinal" | null;
  target_fields: string[];
  identity_fields: string[];
  group_fields: string[];
  ordered_samples: boolean;
}

export interface DatasetCompatibilityDecision {
  dataset_id: string;
  template_slug: string;
  status: CompatibilityStatus;
  display_group:
    | "compatible"
    | "needs_target"
    | "needs_source"
    | "incompatible"
    | "pending"
    | "unavailable";
  scope: "structural";
  compatible: boolean;
  can_use_as_primary: boolean;
  reason_codes: string[];
  reasons: Array<{ code: string; message: string; role: string | null }>;
  technique_recommended: boolean;
  advisory_codes: string[];
  advisories: Array<{ code: string; message: string; role: string | null }>;
}

export interface DatasetCompatibilityMatrix {
  schema_version: "spectra-sherpa-reference-template-matrix/1";
  dataset_count: number;
  template_count: number;
  pair_count: number;
  datasets: ReferenceDatasetOption[];
  matrix: DatasetCompatibilityDecision[];
}

export interface TemplateDataRole {
  role_type: string;
  node_binding: string;
  required?: boolean;
  binding_mode?: string;
  target_type?: string | null;
  connects_to_port?: string | null;
  description?: string;
  accepted_techniques?: string[] | null;
  technique_match?: "advisory" | "required" | null;
  accepted_data_roles?: string[] | null;
}

export interface TemplateDataBinding {
  source?: "experiment";
  experimentId: number;
  displayName?: string | null;
  fileId?: number | null;
  fileIds?: number[] | null;
  allFiles?: boolean;
  assetId?: string | null;
  targetAuthority?: TargetAuthority | null;
  groupColumn?: string | null;
  stage?: ExperimentStage;
  targetBinding?: TemplateDataBinding;
}

export interface TargetAuthority {
  schema_version: "spectrasherpa-target-authority/1";
  column: string;
  target_type: "continuous" | "categorical";
  units: string | null;
  source_digest: string;
}

export type TemplateLaunchMode = "example" | "user" | "draft";

export interface TemplateExampleBinding {
  source: ReferenceDatasetOption["source"];
  datasetName: string;
  selectedTarget?: string | null;
  targetType?: string | null;
}

export interface WorkflowNode {
  id: string;
  type: string;
  /** Scientist-facing instance label; the canonical operation remains `type`. */
  label?: string;
  x: number;
  y: number;
  params: ParamsMap;
  // Execution state (not persisted to backend, only used in frontend)
  executionState?: NodeExecutionState;
}

export interface WorkflowEdge {
  from: string;
  to: string;
  fromPort?: string; // Output port name (default: "default")
  toPort?: string; // Input port name for multi-input nodes (e.g., "X", "y")
  // Validation fields
  isValid?: boolean; // Whether this connection is type-compatible
  validationError?: string | null; // Error message if invalid
  dataType?: string | null; // Data type flowing through edge (e.g., "dataset", "PCA")
}

export interface WorkflowTemplate {
  id: number;
  slug: string;
  name: string;
  description: string;
  category: string;
  status: TemplateStatus;
  status_detail: string | null;
  data_modalities?: DataModality[];
  template_data: {
    nodes: BackendWorkflowNode[];
    edges: BackendWorkflowEdge[];
    canvas_state?: UnknownRecord;
    data_roles?: Record<string, TemplateDataRole>;
    data_modalities?: DataModality[];
    status: TemplateStatus;
    status_detail?: string;
  };
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkflowTemplateCatalog {
  templates: WorkflowTemplate[];
  total: number;
}

export interface ReferenceDatasetOption {
  name: string;
  source: "builtin" | "registered" | "synthetic" | "eigenvector" | "sklearn" | "oes";
  dataset_id?: string | null;
  label: string;
  technique?: string | null;
  data_role?: string | null;
  data_modality?: DataModality | null;
  description?: string | null;
  technical_summary?: string | null;
  featured?: boolean;
  has_embedded_target?: boolean;
  target_type?: string | null;
  target_fields?: string[] | null;
  task_type?: string | null;
  category?: string | null;
  file_path?: string | null;
  files?: string[] | null;
  file_count?: number | null;
  entry_type?: string | null;
  provider?: string | null;
  provider_page?: string | null;
  download_url?: string | null;
  download_page?: string | null;
  requires_runtime_download?: boolean;
  attribution?: string | null;
  no_endorsement?: string | null;
  admission?: "exact_user_acquired_file" | null;
  expected_size_bytes?: number | null;
  availability?: string | null;
  analysis_profile?: DatasetAnalysisProfile | null;
  dataset_package?: {
    package_id: string;
    package_title: string;
    package_description: string;
    assembly_mode: "homogeneous_collection" | "heterogeneous_views";
    artifact_ids: string[];
    view_id: string;
    view_label: string;
    instrument: string;
    cohort: string;
    initially_selected: boolean;
    relations: Array<{
      relation_id: string;
      relation_type: string;
      view_ids: string[];
      row_identity: string;
    }>;
  } | null;
}

export interface TypeRegistryEntry {
  uri: string;
  version: string;
  parent: string | null;
  parent_uri: string | null;
  category: string;
  description: string;
  scientific_kind: string;
  view_kind: string;
  rank: number[];
  dimension_roles: string[];
  view_modes: string[];
  content_categories: string[];
}

export interface TypeRegistryPayload {
  version: string;
  types: Record<string, TypeRegistryEntry>;
  subtypes: Record<string, string[]>;
}

// Backend API types
export interface BackendWorkflowNode {
  node_id: string;
  node_type: string;
  label: string | null;
  parameters: ParamsMap;
  example_binding?: {
    source: ReferenceDatasetOption["source"];
    dataset_name: string;
    selected_target?: string | null;
    target_type?: string | null;
  };
  position_x: number;
  position_y: number;
}

export interface BackendWorkflowEdge {
  from_node_id: string;
  to_node_id: string;
  from_output: string;
  to_input: string;
}

export interface WorkflowCreatePayload {
  name: string;
  description?: string;
  status: string;
  canvas_state?: UnknownRecord;
  project_id?: number | null;
  tab_color?: string | null;
  color_source?: "blank" | "ai" | "data" | "manual" | null;
  primary_data_source_id?: number | null;
  nodes: BackendWorkflowNode[];
  edges: BackendWorkflowEdge[];
}

export interface WorkflowExecuteResponse {
  params_snapshot?: Record<string, ParamsMap>;
  workflow_id: number;
  run_id?: number | null;
  status: string;
  results: UnknownRecord;
  result_descriptors?: Record<string, NodeScientificValueDescriptors>;
  result_presentations?: Record<string, ExecutedPresentationRecord>;
  diagnostics?: Record<string, UnknownRecord>;
  node_statuses: Record<string, string>;
  executed_at: string;
  error?: string;
  integrity_hash?: string | null;
}

/** Authoritative admission result for a persisted workflow. */
export interface WorkflowPreflightIssue {
  level: "error" | "warning";
  code?: string | null;
  message: string;
  node_id?: string | null;
  port?: string | null;
}

export interface WorkflowPreflightEdge {
  from_node_id: string;
  from_output: string;
  to_node_id: string;
  to_input: string;
  status: "typed_valid" | "invalid";
  reason?: string | null;
}

export interface WorkflowPreflightResponse {
  workflow_id: number;
  is_valid: boolean;
  issues: WorkflowPreflightIssue[];
  semantic_edges: WorkflowPreflightEdge[];
}

// Trial execution response (for DetailView independent execution)
export interface TrialExecuteResponse {
  target_node_id: string;
  status: string; // "completed" or "error"
  result: UnknownRecord | null;
  result_descriptor?: NodeScientificValueDescriptors | null;
  result_presentation?: ExecutedPresentationRecord | null;
  diagnostics?: UnknownRecord | null;
  error: string | null;
}

export interface ExecutedPresentationRecord {
  schema_version: "spectrasherpa-executed-presentation/1";
  contract_digest: string;
  contract: NodePresentationContract["payload"];
  presentations: Array<ScientificPresentation & { content_categories: string[] }>;
}

export interface ScientificDimensionDescriptor {
  role: string;
  size: number;
  labels?: string[];
}

export interface ScientificValueDescriptor {
  schema_version: "spectrasherpa-scientific-value/1";
  port_name: string;
  type_ref: string;
  label: string;
  scientific_kind: string;
  view_kind: string;
  shape: number[] | null;
  dimensions: ScientificDimensionDescriptor[];
  view_modes: string[];
  content_categories: string[];
  shape_valid: boolean;
  shape_issue: string | null;
}

export type NodeScientificValueDescriptors = Record<string, ScientificValueDescriptor>;

// Available datasets for DATA node selection
export interface DatasetFile {
  id: number;
  file_path: string;
  file_type: string | null;
  file_size_bytes: number;
  shape?: number[] | null;
  n_samples?: number | null;
  n_features?: number | null;
  data_role?: string | null;
  x_title?: string | null;
  x_units?: string | null;
  is_spectra?: boolean | null;
  target_names?: string[] | null;
  target_types?: Record<string, "continuous" | "categorical"> | null;
}

export interface ExperimentDataset {
  id: number;
  name: string;
  description: string | null;
  project_id?: number | null;
  target_names?: string[] | null;
  target_types?: Record<string, "continuous" | "categorical"> | null;
  target_mode?: string | null;
  selected_target?: string | null;
  target_complete_rows?: number | null;
  target_any_rows?: number | null;
  target_row_count?: number | null;
  stages: {
    raw: DatasetFile[];
    preprocessed: DatasetFile[];
    synthetic: DatasetFile[];
  };
}

export interface LibraryDataset {
  id: number;
  compound_name: string;
  cas_number: string;
  resolution: string | null;
  file_path: string;
}

export interface AvailableDatasets {
  experiments: ExperimentDataset[];
  library: LibraryDataset[];
  builder: UnknownRecord[];
}

export type WorkflowPurpose = "analysis" | "managed_candidate_authority";

export interface WorkflowListItem {
  id: number;
  name: string;
  created_at: string;
  updated_at: string;
  description?: string | null;
  status?: string;
  purpose: WorkflowPurpose;
  project_id?: number | null;
  tab_color?: string | null;
  tab_color_override?: string | null;
  color_source?: "blank" | "ai" | "data" | "manual";
  primary_data_source_id?: number | null;
  primary_data_source_name?: string | null;
  data_origin?: "current" | "example" | null;
  data_source_ids?: number[];
  advisor_channel_id?: number | null;
  created_from_template_name?: string | null;
  created_from_template_version?: string | null;
  created_from_workflow_id?: number | null;
  created_from_workflow_name?: string | null;
  sheet_order?: number;
  node_count?: number;
  edge_count?: number;
}
