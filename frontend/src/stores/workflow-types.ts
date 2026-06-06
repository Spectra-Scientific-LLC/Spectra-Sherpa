/**
 * Type definitions for the workflow store.
 *
 * Extracted from workflow.ts for module size reduction.
 * All types are re-exported from workflow.ts for backward compatibility.
 */

import type { NodeExecutionState, ExperimentStage } from "@/types";

export type ParamsMap = Record<string, unknown>;
export type UnknownRecord = Record<string, unknown>;
export type DataModality = "spectra" | "features" | "hsi";

export interface TemplateDataRole {
  role_type: string;
  node_binding: string;
  required?: boolean;
  binding_mode?: string;
  target_type?: string | null;
  connects_to_port?: string | null;
  description?: string;
  accepted_techniques?: string[] | null;
  accepted_data_roles?: string[] | null;
}

export interface TemplateDataBinding {
  source?: "experiment";
  experimentId: number;
  fileId?: number | null;
  stage?: ExperimentStage;
  targetBinding?: TemplateDataBinding;
  targetType?: string | null;
}

export type TemplateLaunchMode = "example" | "user";

export interface TemplateExampleBinding {
  source: ReferenceDatasetOption["source"];
  datasetName: string;
}

export interface WorkflowNode {
  id: string;
  type: string;
  x: number;
  y: number;
  params: ParamsMap;
  // Execution state (not persisted to backend, only used in frontend)
  executionState?: NodeExecutionState;
}

export interface WorkflowEdge {
  from: string;
  to: string;
  fromPort?: string;  // Output port name (default: "default")
  toPort?: string;    // Input port name for multi-input nodes (e.g., "X", "y")
  // Validation fields
  isValid?: boolean;  // Whether this connection is type-compatible
  validationError?: string | null;  // Error message if invalid
  dataType?: string | null;  // Data type flowing through edge (e.g., "dataset", "PCA")
}

export interface WorkflowTemplate {
  id: number;
  slug: string;
  name: string;
  description: string;
  category: string;
  status: string;
  data_modalities?: DataModality[];
  template_data: {
    nodes: BackendWorkflowNode[];
    edges: BackendWorkflowEdge[];
    canvas_state?: UnknownRecord;
    data_roles?: Record<string, TemplateDataRole>;
    data_modalities?: DataModality[];
    status?: string;
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
  source: "synthetic" | "eigenvector" | "sklearn" | "spectrochempy" | "oes";
  label: string;
  technique?: string | null;
  data_role?: string | null;
  data_modality?: DataModality | null;
  description?: string | null;
  featured?: boolean;
  has_embedded_target?: boolean;
  target_type?: string | null;
  task_type?: string | null;
  category?: string | null;
  file_path?: string | null;
  files?: string[] | null;
  file_count?: number | null;
  entry_type?: string | null;
}

export interface TypeRegistryEntry {
  uri: string;
  version: string;
  parent: string | null;
  parent_uri: string | null;
  category: string;
  description: string;
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
  workflow_id: number;
  run_id?: number | null;
  status: string;
  results: UnknownRecord;
  diagnostics?: Record<string, UnknownRecord>;
  node_statuses: Record<string, string>;
  executed_at: string;
  error?: string;
  integrity_hash?: string | null;
}

// Trial execution response (for DetailView independent execution)
export interface TrialExecuteResponse {
  target_node_id: string;
  status: string;  // "completed" or "error"
  result: UnknownRecord | null;
  error: string | null;
}

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
}

export interface ExperimentDataset {
  id: number;
  name: string;
  description: string | null;
  project_id?: number | null;
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

export interface WorkflowListItem {
  id: number;
  name: string;
  created_at: string;
  updated_at: string;
  description?: string | null;
  status?: string;
  project_id?: number | null;
  tab_color?: string | null;
  tab_color_override?: string | null;
  color_source?: "blank" | "ai" | "data" | "manual";
  primary_data_source_id?: number | null;
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
