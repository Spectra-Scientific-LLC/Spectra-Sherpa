import { defineStore } from "pinia";
import { ref, computed } from "vue";
import api from "@/api/client";
import type { NodeTypeMetadata, NodeLibraryResponse, NodeExecutionState, NodeExecutionStatus } from "@/types";
import { getErrorMessage } from "@/utils/errors";

type ParamsMap = Record<string, unknown>;
type UnknownRecord = Record<string, unknown>;

export interface WorkflowNode {
  id: number;
  type: string;
  x: number;
  y: number;
  params: ParamsMap;
  // Execution state (not persisted to backend, only used in frontend)
  executionState?: NodeExecutionState;
}

export interface WorkflowEdge {
  from: number;
  to: number;
  fromPort?: string;  // Output port name (default: "default")
  toPort?: string;    // Input port name for multi-input nodes (e.g., "X", "y")
  // Validation fields
  isValid?: boolean;  // Whether this connection is type-compatible
  validationError?: string | null;  // Error message if invalid
  dataType?: string | null;  // Data type flowing through edge (e.g., "NDDataset", "PCA")
}

// Input port definition for multi-input nodes (mirrors backend InputPort)
export interface InputPort {
  name: string;
  label: string;
  dataType: string;
  required: boolean;
  description?: string;
}

// DEPRECATED: Node types that have multiple named input ports
// This is now fetched from backend metadata via getNodeMetadata().input_ports
// Kept for backward compatibility only - will be removed in future version
export const MULTI_INPUT_NODES: Record<string, InputPort[]> = {
  PLS: [
    { name: "X", label: "Spectra (X)", dataType: "NDDataset", required: true, description: "Spectral data matrix" },
    { name: "y", label: "Concentrations (y)", dataType: "array", required: true, description: "Target values" },
  ],
  PCR: [
    { name: "X", label: "Spectra (X)", dataType: "NDDataset", required: true, description: "Spectral data matrix" },
    { name: "y", label: "Targets (y)", dataType: "array", required: true, description: "Target values" },
  ],
  SVR: [
    { name: "X", label: "Spectra (X)", dataType: "NDDataset", required: true, description: "Spectral data matrix" },
    { name: "y", label: "Targets (y)", dataType: "array", required: true, description: "Target values" },
  ],
  LINEAR_REGRESSION: [
    { name: "X", label: "Features (X)", dataType: "array", required: true, description: "Feature matrix" },
    { name: "y", label: "Targets (y)", dataType: "array", required: true, description: "Target values" },
  ],
  PLS_DA: [
    { name: "X", label: "Spectra (X)", dataType: "NDDataset", required: true, description: "Spectral data matrix" },
    { name: "y", label: "Class Labels (y)", dataType: "array", required: false, description: "Class labels for each sample" },
  ],
  KNN: [
    { name: "X", label: "Features (X)", dataType: "NDDataset", required: true, description: "Feature matrix (spectral data or scores)" },
    { name: "y", label: "Class Labels (y)", dataType: "array", required: false, description: "Class labels for each sample" },
  ],
  SIMCA: [
    { name: "X", label: "Features (X)", dataType: "NDDataset", required: true, description: "Feature matrix (spectral data or scores)" },
    { name: "y", label: "Class Labels (y)", dataType: "array", required: false, description: "Class labels for each sample" },
  ],
  TRAIN_TEST_SPLIT: [
    { name: "X", label: "Input Data", dataType: "NDDataset", required: true, description: "Data to split" },
    { name: "y", label: "Target Values (optional)", dataType: "array", required: false, description: "Target values for stratification" },
  ],
  PLS_PREDICT: [
    { name: "X_new", label: "New Spectra", dataType: "NDDataset", required: true, description: "New spectral data to predict" },
    { name: "model", label: "PLS Model", dataType: "model", required: true, description: "Trained PLS model" },
  ],
  PCA_TRANSFORM: [
    { name: "X_new", label: "New Spectra", dataType: "NDDataset", required: true, description: "New data to transform" },
    { name: "model", label: "PCA Model", dataType: "model", required: true, description: "Trained PCA model" },
  ],
  PLSDA_PREDICT: [
    { name: "X_new", label: "New Spectra", dataType: "NDDataset", required: true, description: "New spectral data to classify" },
    { name: "model", label: "PLS-DA Model", dataType: "model", required: true, description: "Trained PLS-DA model" },
  ],
  KNN_PREDICT: [
    { name: "X_new", label: "New Features", dataType: "NDDataset", required: true, description: "New feature data to classify" },
    { name: "model", label: "KNN Model", dataType: "model", required: true, description: "Trained KNN model" },
  ],
};

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

interface TypeRegistryEntry {
  uri: string;
  version: string;
  parent: string | null;
  parent_uri: string | null;
  category: string;
  description: string;
}

interface TypeRegistryPayload {
  version: string;
  types: Record<string, TypeRegistryEntry>;
  subtypes: Record<string, string[]>;
}

// Map frontend node types to backend DAG node types
export const NODE_TYPE_MAP: Record<string, string> = {
  // Data source nodes
  DATA: "data.source",
  FILE_LOAD: "data.file_load",
  MY_DATASET: "data.my_dataset",
  NIST_LIBRARY: "data.nist_library",
  SYNTHETIC_CURVE: "data.synthetic_curve",
  TRAIN_TEST_SPLIT: "data.train_test_split",

  // Preprocessing - atomic nodes (new)
  COSMIC_RAY: "preprocess.cosmic_ray",
  CLIP_RANGE: "preprocess.clip_range",
  CLIP_FLOOR: "preprocess.clip_floor",
  WAVENUMBER_ALIGN: "preprocess.wavenumber_align",
  SCALE_MAX: "preprocess.scale_max",
  CENTER_MEAN: "preprocess.center_mean",
  PARETO_SCALING: "preprocess.pareto_scaling",
  OSC: "preprocess.osc",
  AUTOSCALING: "preprocess.autoscaling",
  SG_DERIVATIVE: "preprocess.sg_derivative",
  EMSC: "preprocess.emsc",

  // Preprocessing - existing nodes
  NORMALIZE: "normalize.snv",
  SCALE: "normalize.scale",
  BASELINE: "baseline.penalized_ls",
  BASELINE_RB: "baseline.rubberband",
  SMOOTH: "smooth.savitzky_golay",
  DERIV_1: "derivative.first",
  DERIV_2: "derivative.second",
  DERIVATIVE_1ST: "derivative.first",  // Alias for DERIV_1
  DERIVATIVE_2ND: "derivative.second",  // Alias for DERIV_2
  MSC: "normalize.msc",
  SNV: "normalize.snv",
  MEAN_CENTER: "preprocess.center_mean",  // Alias for CENTER_MEAN
  AUTOSCALE: "preprocess.autoscaling",  // Alias for AUTOSCALING
  PARETO_SCALE: "preprocess.pareto_scaling",  // Alias for PARETO_SCALING

  // Synthesis / Blend nodes
  BLEND: "synthesis.blend",
  SPECIES: "synthesis.species",
  MERGE_SPECTRA: "synthesis.merge",

  // Analysis / Model nodes
  PCA: "model.pca",
  PCA_TRANSFORM: "model.pca_transform",
  PLS: "model.pls",
  PLS_PREDICT: "model.pls_predict",
  LINEAR_REGRESSION: "model.linear_regression",
  MCR: "model.mcr_als",
  EFA: "model.efa",
  PCR: "model.pcr",
  SVR: "model.svr",
  KMEANS: "model.kmeans",
  DBSCAN: "model.dbscan",
  HCA: "model.hca",
  PEAK: "analysis.peak_finding",
  PEAK_FINDING: "analysis.peak_finding",  // Alias for PEAK

  // Classification nodes
  PLS_DA: "classification.plsda",
  PLSDA_PREDICT: "classification.plsda_predict",
  KNN: "classification.knn",
  KNN_PREDICT: "classification.knn_predict",
  SIMCA: "classification.simca",

  // Diagnostics nodes
  OUTLIER_DETECTION: "diagnostics.outliers",
  CROSS_VALIDATION: "diagnostics.cross_validation",

  // Time Series nodes
  MOVING_WINDOW: "time_series.moving_window",
  TREND_REMOVAL: "time_series.trend_removal",

  // Output nodes
  STATS: "stats.summary",
  PLOT: "output.plot",
  CONTOUR_PLOT: "output.contour",
  DATA_TABLE: "output.data_table",
  EXPORT: "output.export",

  // Legacy mappings (backward compatibility)
  COSMIC: "preprocess.cosmic_ray",
};

const LEGACY_NODE_TYPE_REVERSE_MAP: Record<string, string> = {};
for (const [legacyType, dotType] of Object.entries(NODE_TYPE_MAP)) {
  if (!LEGACY_NODE_TYPE_REVERSE_MAP[dotType]) {
    LEGACY_NODE_TYPE_REVERSE_MAP[dotType] = legacyType;
  }
}

export const normalizeNodeType = (nodeType: string): string => {
  if (!nodeType) return nodeType;
  if (nodeType.includes(".")) {
    return nodeType.toLowerCase();
  }
  const mapped = NODE_TYPE_MAP[nodeType];
  if (mapped) {
    return mapped;
  }
  if (nodeType.includes("_")) {
    return nodeType.toLowerCase().replace(/_/g, ".");
  }
  return nodeType.toLowerCase();
};

export const getLegacyNodeType = (nodeType: string): string => {
  if (!nodeType) return nodeType;
  const legacy = LEGACY_NODE_TYPE_REVERSE_MAP[nodeType];
  if (legacy) return legacy;
  if (nodeType.includes(".")) {
    return nodeType.toUpperCase().replace(/\./g, "_");
  }
  return nodeType;
};

const getParamMapping = (nodeType: string): Record<string, string> | undefined => {
  const legacyType = getLegacyNodeType(nodeType);
  return PARAM_NAME_MAP[nodeType] || PARAM_NAME_MAP[legacyType];
};

// Get reverse param mapping (backend → frontend) for a node type
// Used to convert backend metadata param names back to frontend names
export const getReverseParamMapping = (nodeType: string): Record<string, string> | undefined => {
  const mapping = getParamMapping(nodeType);
  if (!mapping) return undefined;

  // Reverse the mapping: backend → frontend
  const reverseMap: Record<string, string> = {};
  for (const [frontend, backend] of Object.entries(mapping)) {
    reverseMap[backend] = frontend;
  }
  return reverseMap;
};

// Map frontend parameter names to backend parameter names per node type
// UI uses user-friendly names, backend uses library-specific names
/**
 * Parameter name mapping between frontend and backend.
 *
 * This mapping is CRITICAL for validation and execution to work correctly.
 *
 * When adding new nodes with custom frontend parameter names:
 * 1. Add the mapping here
 * 2. Test validation in the UI
 * 3. Test execution to ensure backend receives correct parameter names
 *
 * Current mappings:
 * - SMOOTH, DERIV_1, DERIV_2: Savitzky-Golay parameters
 *   Frontend: window, poly | Backend: size, order
 *
 * - PCA, PLS, MCR, EFA, SIMPLISMA: Component analysis nodes
 *   Frontend: components | Backend: n_components
 */
export const PARAM_NAME_MAP: Record<string, Record<string, string>> = {
  // Smoothing and derivative nodes use Savitzky-Golay parameters
  SMOOTH: {
    window: "size",      // UI: window -> Backend: size
    poly: "order",       // UI: poly -> Backend: order
  },
  DERIV_1: {
    window: "size",      // UI: window -> Backend: size
    poly: "order",       // UI: poly -> Backend: order
  },
  DERIV_2: {
    window: "size",      // UI: window -> Backend: size
    poly: "order",       // UI: poly -> Backend: order
  },

  // Component analysis nodes now use n_components directly in both frontend and backend
  // No mapping needed anymore
};

// Migrate legacy parameter names (backward compatibility for old workflows)
// CRITICAL: Handles workflows saved before n_components migration
function migrateLegacyParams(nodeType: string, params: ParamsMap): ParamsMap {
  const result = { ...params };

  // Component analysis nodes: "components" → "n_components"
  const componentNodes = ['PCA', 'PLS', 'MCR', 'EFA', 'SIMPLISMA', 'PLS_DA', 'SIMCA'];
  const normalizedType = normalizeNodeType(nodeType);
  const legacyType = getLegacyNodeType(nodeType);

  if (componentNodes.includes(legacyType)) {
    if ('components' in result && !('n_components' in result)) {
      result.n_components = result.components;
      delete result.components;
      console.log(`[workflow.ts] Migrated legacy parameter: ${nodeType} components → n_components`);
    }
  }

  return result;
}

// Convert frontend params to backend params for a given node type
// IMPORTANT: If both frontend and backend keys exist (e.g., both "components" and "n_components"),
// only use the frontend key (the user's current value) and skip the backend key (old value).
function mapParamsToBackend(nodeType: string, params: ParamsMap): ParamsMap {
  // First migrate legacy parameters
  const migratedParams = migrateLegacyParams(nodeType, params);

  const mapping = getParamMapping(nodeType);
  if (!mapping) {
    return migratedParams;
  }

  // Build reverse mapping to detect backend keys (e.g., n_components -> components)
  const backendToFrontend: Record<string, string> = {};
  for (const [frontend, backend] of Object.entries(mapping)) {
    backendToFrontend[backend] = frontend;
  }

  const mappedParams: ParamsMap = {};
  for (const [key, value] of Object.entries(migratedParams)) {
    // Skip this key if it's a backend key AND its frontend equivalent exists
    // (means we have both "components" and "n_components", prefer "components")
    if (backendToFrontend[key] && migratedParams[backendToFrontend[key]] !== undefined) {
      continue; // Skip the backend key, we'll use the frontend key instead
    }

    const backendKey = mapping[key] || key;
    mappedParams[backendKey] = value;
  }
  return mappedParams;
}

// Convert backend params to frontend params for a given node type
function mapParamsFromBackend(nodeType: string, params: ParamsMap): ParamsMap {
  const mapping = getParamMapping(nodeType);
  if (!mapping) {
    return { ...params };
  }

  // Create reverse mapping
  const reverseMapping: Record<string, string> = {};
  for (const [frontend, backend] of Object.entries(mapping)) {
    reverseMapping[backend] = frontend;
  }

  const mappedParams: ParamsMap = {};
  for (const [key, value] of Object.entries(params)) {
    const frontendKey = reverseMapping[key] || key;
    mappedParams[frontendKey] = value;
  }
  return mappedParams;
}

// Backend API types
interface BackendWorkflowNode {
  node_id: string;
  node_type: string;
  label: string | null;
  parameters: ParamsMap;
  position_x: number;
  position_y: number;
}

interface BackendWorkflowEdge {
  from_node_id: string;
  to_node_id: string;
  from_output: string;
  to_input: string;
}

interface WorkflowCreatePayload {
  name: string;
  description?: string;
  status: string;
  canvas_state?: UnknownRecord;
  nodes: BackendWorkflowNode[];
  edges: BackendWorkflowEdge[];
}

interface WorkflowExecuteResponse {
  workflow_id: number;
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
}

export interface ExperimentDataset {
  id: number;
  name: string;
  description: string | null;
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
}

// SpectrochemPy-based workflow templates
const TEMPLATES: Record<string, WorkflowTemplate> = {
  // === Core Project Templates ===
  project1: {
    id: "project1",
    name: "Project 1: Absorption Calibration",
    description: "Build wavenumber-specific absorption vs. concentration calibration models",
    nodes: [
      { id: 1, type: "DATA", x: 50, y: 100, params: { source: "experiment" } },
      { id: 2, type: "DATA", x: 50, y: 250, params: { source: "spectrochempy", example_dataset: "irdata" } },
      { id: 3, type: "BASELINE", x: 250, y: 100, params: { method: "als", lam: 100000, p: 0.001 } },
      { id: 4, type: "NORMALIZE", x: 250, y: 250, params: { method: "snv" } },
      { id: 5, type: "PLS", x: 450, y: 175, params: { n_components: 5 } },
      { id: 6, type: "STATS", x: 650, y: 100, params: { metrics: ["r2", "rmse", "mae"] } },
      { id: 7, type: "EXPORT", x: 650, y: 250, params: { filename: "calibration_model.pkl", format: "pickle" } },
    ],
    edges: [
      { from: 1, to: 3 },
      { from: 2, to: 4 },
      { from: 3, to: 5 },
      { from: 4, to: 5 },
      { from: 5, to: 6 },
      { from: 5, to: 7 },
    ],
  },
  project2: {
    id: "project2",
    name: "Project 2: MCR-ALS with Kinetics",
    description: "Multivariate Curve Resolution with kinetic constraints for time-resolved analysis",
    nodes: [
      { id: 1, type: "DATA", x: 50, y: 150, params: { source: "experiment" } },
      { id: 2, type: "BASELINE", x: 230, y: 100, params: { method: "als", lam: 50000, p: 0.01 } },
      { id: 3, type: "SMOOTH", x: 230, y: 250, params: { method: "savgol", window: 15, poly: 2 } },
      { id: 4, type: "MCR", x: 430, y: 175, params: { n_components: 3, max_iter: 100, tol: 0.1, non_negative_C: true, non_negative_St: true } },
      { id: 5, type: "PLOT", x: 630, y: 80, params: { type: "concentrations", xAxis: "time", yAxis: "conc" } },
      { id: 6, type: "PLOT", x: 630, y: 175, params: { type: "spectra", xAxis: "wavenumber", yAxis: "absorbance" } },
      { id: 7, type: "EXPORT", x: 630, y: 280, params: { filename: "mcr_results.csv", format: "csv" } },
    ],
    edges: [
      { from: 1, to: 2 },
      { from: 2, to: 3 },
      { from: 3, to: 4 },
      { from: 4, to: 5 },
      { from: 4, to: 6 },
      { from: 4, to: 7 },
    ],
  },

  // === SpectrochemPy Example-Based Templates ===
  ir_opus_analysis: {
    id: "ir_opus_analysis",
    name: "IR OPUS Import & Analysis",
    description: "Import Bruker OPUS files, preprocess IR spectra, and perform spectral analysis",
    nodes: [
      { id: 1, type: "DATA", x: 50, y: 150, params: { source: "file", format: "opus", path: "*.0" } },
      { id: 2, type: "SLICE", x: 230, y: 150, params: { start: 4000, end: 400, unit: "cm-1" } },
      { id: 3, type: "BASELINE_RB", x: 410, y: 100, params: {} },
      { id: 4, type: "NORMALIZE", x: 410, y: 220, params: { method: "area", range: [1800, 1500] } },
      { id: 5, type: "PEAK", x: 590, y: 150, params: { method: "find_peaks", prominence: 0.01, width: 5 } },
      { id: 6, type: "PLOT", x: 770, y: 80, params: { type: "spectra", show_peaks: true } },
      { id: 7, type: "STATS", x: 770, y: 220, params: { metrics: ["peak_areas", "peak_heights"] } },
    ],
    edges: [
      { from: 1, to: 2 },
      { from: 2, to: 3 },
      { from: 2, to: 4 },
      { from: 3, to: 5 },
      { from: 4, to: 5 },
      { from: 5, to: 6 },
      { from: 5, to: 7 },
    ],
  },
  efa_analysis: {
    id: "efa_analysis",
    name: "Evolving Factor Analysis (EFA)",
    description: "Determine the number of components in evolving mixtures using EFA",
    nodes: [
      { id: 1, type: "DATA", x: 50, y: 150, params: { source: "experiment", format: "csv" } },
      { id: 2, type: "NORMALIZE", x: 230, y: 150, params: { method: "mean_center" } },
      { id: 3, type: "EFA", x: 430, y: 150, params: { n_components: 10, direction: "both" } },
      { id: 4, type: "PLOT", x: 630, y: 80, params: { type: "efa_forward", log_scale: true } },
      { id: 5, type: "PLOT", x: 630, y: 220, params: { type: "efa_backward", log_scale: true } },
      { id: 6, type: "STATS", x: 810, y: 150, params: { metrics: ["rank", "explained_variance"] } },
    ],
    edges: [
      { from: 1, to: 2 },
      { from: 2, to: 3 },
      { from: 3, to: 4 },
      { from: 3, to: 5 },
      { from: 4, to: 6 },
      { from: 5, to: 6 },
    ],
  },
  pls_regression: {
    id: "pls_regression",
    name: "PLS Regression Analysis",
    description: "Partial Least Squares regression for quantitative spectroscopy",
    nodes: [
      { id: 1, type: "DATA", x: 50, y: 100, params: { source: "experiment", format: "csv" } },
      { id: 2, type: "DATA", x: 50, y: 250, params: { source: "reference", format: "csv", column: "concentration" } },
      { id: 3, type: "BASELINE", x: 250, y: 100, params: { method: "arpls", lam: 100000 } },
      { id: 4, type: "NORMALIZE", x: 250, y: 250, params: { method: "snv" } },
      { id: 5, type: "PLS", x: 450, y: 175, params: { n_components: 10 } },
      { id: 6, type: "PLOT", x: 650, y: 80, params: { type: "rmsecv", xAxis: "components" } },
      { id: 7, type: "PLOT", x: 650, y: 175, params: { type: "predicted_vs_actual" } },
      { id: 8, type: "STATS", x: 650, y: 280, params: { metrics: ["r2", "rmsec", "rmsecv", "rpd"] } },
    ],
    edges: [
      { from: 1, to: 3 },
      { from: 2, to: 4 },
      { from: 3, to: 5 },
      { from: 4, to: 5 },
      { from: 5, to: 6 },
      { from: 5, to: 7 },
      { from: 5, to: 8 },
    ],
  },
  raman_processing: {
    id: "raman_processing",
    name: "Raman Processing Pipeline",
    description: "Denoise Raman spectra with cosmic ray removal and fluorescence correction",
    nodes: [
      { id: 1, type: "DATA", x: 50, y: 150, params: { source: "experiment", format: "spc" } },
      { id: 2, type: "COSMIC", x: 230, y: 150, params: { method: "whitaker", threshold: 5, width: 3 } },
      { id: 3, type: "BASELINE", x: 410, y: 100, params: { method: "als", lam: 1e6, p: 0.001 } },
      { id: 4, type: "SMOOTH", x: 410, y: 220, params: { method: "whittaker", lam: 10 } },
      { id: 5, type: "NORMALIZE", x: 590, y: 150, params: { method: "max" } },
      { id: 6, type: "PLOT", x: 770, y: 80, params: { type: "overlay", show_baseline: true } },
      { id: 7, type: "EXPORT", x: 770, y: 220, params: { filename: "raman_processed.csv", format: "csv" } },
    ],
    edges: [
      { from: 1, to: 2 },
      { from: 2, to: 3 },
      { from: 2, to: 4 },
      { from: 3, to: 5 },
      { from: 4, to: 5 },
      { from: 5, to: 6 },
      { from: 5, to: 7 },
    ],
  },
  nmr_processing: {
    id: "nmr_processing",
    name: "NMR Processing Workflow",
    description: "Process NMR spectra with phase correction, baseline, and peak picking",
    nodes: [
      { id: 1, type: "DATA", x: 50, y: 150, params: { source: "experiment", format: "bruker" } },
      { id: 2, type: "PHASE", x: 230, y: 150, params: { method: "auto", pivot: null } },
      { id: 3, type: "BASELINE", x: 410, y: 100, params: { method: "als", lam: 100000, p: 0.001 } },
      { id: 4, type: "SLICE", x: 410, y: 220, params: { start: 12, end: -2, unit: "ppm" } },
      { id: 5, type: "PEAK", x: 590, y: 150, params: { method: "cwt", min_snr: 3 } },
      { id: 6, type: "FIT", x: 770, y: 100, params: { model: "lorentzian", optimize: true } },
      { id: 7, type: "STATS", x: 770, y: 220, params: { metrics: ["peak_areas", "integrals", "chemical_shifts"] } },
    ],
    edges: [
      { from: 1, to: 2 },
      { from: 2, to: 3 },
      { from: 2, to: 4 },
      { from: 3, to: 5 },
      { from: 4, to: 5 },
      { from: 5, to: 6 },
      { from: 5, to: 7 },
    ],
  },
  iris_decomposition: {
    id: "iris_decomposition",
    name: "IRIS Decomposition",
    description: "Integral Regularized Inversion of Spectra for relaxation analysis",
    nodes: [
      { id: 1, type: "DATA", x: 50, y: 150, params: { source: "experiment", format: "csv" } },
      { id: 2, type: "NORMALIZE", x: 230, y: 150, params: { method: "max" } },
      { id: 3, type: "IRIS", x: 430, y: 150, params: { kernel: "exp", regularization: "tikhonov", alpha: 0.01 } },
      { id: 4, type: "PLOT", x: 630, y: 80, params: { type: "distribution", xAxis: "tau", yAxis: "amplitude" } },
      { id: 5, type: "PLOT", x: 630, y: 220, params: { type: "fit_residuals" } },
      { id: 6, type: "EXPORT", x: 810, y: 150, params: { filename: "iris_distribution.csv", format: "csv" } },
    ],
    edges: [
      { from: 1, to: 2 },
      { from: 2, to: 3 },
      { from: 3, to: 4 },
      { from: 3, to: 5 },
      { from: 4, to: 6 },
    ],
  },

  // === Basic Templates ===
  preprocessing: {
    id: "preprocessing",
    name: "Standard Preprocessing",
    description: "Basic preprocessing pipeline: baseline, smoothing, normalization",
    nodes: [
      { id: 1, type: "DATA", x: 50, y: 150, params: { source: "experiment" } },
      { id: 2, type: "BASELINE", x: 230, y: 150, params: { method: "als", lam: 100000, p: 0.001 } },
      { id: 3, type: "SMOOTH", x: 410, y: 150, params: { method: "savgol", window: 15, poly: 2 } },
      { id: 4, type: "NORMALIZE", x: 590, y: 150, params: { method: "snv" } },
      { id: 5, type: "EXPORT", x: 770, y: 150, params: { filename: "preprocessed.csv", format: "csv" } },
    ],
    edges: [
      { from: 1, to: 2 },
      { from: 2, to: 3 },
      { from: 3, to: 4 },
      { from: 4, to: 5 },
    ],
  },
  pca: {
    id: "pca",
    name: "PCA Exploration",
    description: "Exploratory data analysis with PCA visualization and outlier detection",
    nodes: [
      { id: 1, type: "DATA", x: 50, y: 150, params: { source: "experiment" } },
      { id: 2, type: "NORMALIZE", x: 230, y: 150, params: { method: "mean_center" } },
      { id: 3, type: "PCA", x: 430, y: 150, params: { n_components: "5" } },
      { id: 4, type: "PLOT", x: 630, y: 60, params: { type: "scores", pc_x: 1, pc_y: 2 } },
      { id: 5, type: "PLOT", x: 630, y: 160, params: { type: "loadings", pc: 1 } },
      { id: 6, type: "PLOT", x: 630, y: 260, params: { type: "scree" } },
      { id: 7, type: "STATS", x: 810, y: 150, params: { metrics: ["explained_variance", "hotelling_t2", "q_residuals"] } },
    ],
    edges: [
      { from: 1, to: 2 },
      { from: 2, to: 3 },
      { from: 3, to: 4 },
      { from: 3, to: 5 },
      { from: 3, to: 6 },
      { from: 3, to: 7 },
    ],
  },
  peaks: {
    id: "peaks",
    name: "Peak Detection & Fitting",
    description: "Automated peak detection, fitting, and quantification workflow",
    nodes: [
      { id: 1, type: "DATA", x: 50, y: 150, params: { source: "experiment" } },
      { id: 2, type: "BASELINE", x: 230, y: 150, params: { method: "als", lam: 100000, p: 0.001 } },
      { id: 3, type: "SMOOTH", x: 410, y: 150, params: { method: "savgol", window: 11, poly: 3 } },
      { id: 4, type: "PEAK", x: 590, y: 100, params: { method: "find_peaks", prominence: 0.01 } },
      { id: 5, type: "FIT", x: 590, y: 220, params: { model: "gaussian", optimize: true } },
      { id: 6, type: "STATS", x: 770, y: 100, params: { metrics: ["peak_positions", "fwhm", "areas"] } },
      { id: 7, type: "PLOT", x: 770, y: 220, params: { type: "fitted", show_components: true } },
    ],
    edges: [
      { from: 1, to: 2 },
      { from: 2, to: 3 },
      { from: 3, to: 4 },
      { from: 3, to: 5 },
      { from: 4, to: 6 },
      { from: 5, to: 7 },
    ],
  },
  simplisma: {
    id: "simplisma",
    name: "SIMPLISMA Pure Variable Selection",
    description: "SIMPLe-to-use Interactive Self-modeling Mixture Analysis for initial estimates",
    nodes: [
      { id: 1, type: "DATA", x: 50, y: 150, params: { source: "experiment", format: "csv" } },
      { id: 2, type: "NORMALIZE", x: 230, y: 150, params: { method: "mean_center" } },
      { id: 3, type: "SIMPLISMA", x: 430, y: 150, params: { n_components: 3, noise: 3 } },
      { id: 4, type: "PLOT", x: 630, y: 80, params: { type: "purity", xAxis: "variable" } },
      { id: 5, type: "PLOT", x: 630, y: 220, params: { type: "pure_spectra" } },
      { id: 6, type: "EXPORT", x: 810, y: 150, params: { filename: "initial_estimates.csv", format: "csv" } },
    ],
    edges: [
      { from: 1, to: 2 },
      { from: 2, to: 3 },
      { from: 3, to: 4 },
      { from: 3, to: 5 },
      { from: 5, to: 6 },
    ],
  },
};

export const useWorkflowStore = defineStore("workflow", () => {
  // State
  const nodes = ref<WorkflowNode[]>([]);
  const edges = ref<WorkflowEdge[]>([]);
  const currentTemplateId = ref<string | null>(null);
  const hasUnsavedChanges = ref(false);
  const workflowName = ref("Untitled Workflow");
  const workflowId = ref<number | null>(null);
  const workflowDescription = ref("");
  const workflowHash = ref<string | null>(null);
  const isLoading = ref(false);
  const lastExecutionResults = ref<UnknownRecord | null>(null);
  const lastExecutionDiagnostics = ref<Record<string, UnknownRecord>>({});
  const workflowWarnings = ref<string[]>([]);
  const availableDatasets = ref<AvailableDatasets | null>(null);
  // Maps frontend canvas node IDs <-> backend workflow node_id strings.
  // Needed to correctly correlate status/result payloads when backend IDs are non-numeric.
  const frontendToBackendNodeIds = ref<Map<number, string>>(new Map());
  const backendToFrontendNodeIds = ref<Map<string, number>>(new Map());

  // Node library metadata (validation schemas, parameters, etc.)
  const nodeLibrary = ref<Map<string, NodeTypeMetadata>>(new Map());
  const isLoadingNodeLibrary = ref(false);
  const nodeLibraryLoadError = ref<string | null>(null);
  const nodeLibraryVersion = ref<string | null>(null); // Track backend version for cache invalidation
  const typeRegistry = ref<TypeRegistryPayload | null>(null);
  const isLoadingTypeRegistry = ref(false);
  const typeRegistryLoadError = ref<string | null>(null);

  // Workflow has been modified since last execution (stale state)
  const isWorkflowStale = ref(false);

  // Getters
  const nodeCount = computed(() => nodes.value.length);
  const edgeCount = computed(() => edges.value.length);
  const availableTemplates = computed(() => Object.values(TEMPLATES));

  const normalizeBackendExecutionStatus = (status: unknown): NodeExecutionStatus | null => {
    if (typeof status !== "string") {
      return null;
    }
    const normalized = status.toLowerCase();
    if (normalized === "completed" || normalized === "complete" || normalized === "success" || normalized === "succeeded") {
      return "completed";
    }
    if (normalized === "error" || normalized === "failed" || normalized === "failure") {
      return "error";
    }
    if (normalized === "running" || normalized === "in_progress" || normalized === "processing") {
      return "running";
    }
    if (normalized === "pending" || normalized === "queued") {
      return "pending";
    }
    return null;
  };

  const parseTypeRef = (
    typeRef: string
  ): { name: string; major: number; minor: number } | null => {
    const match = typeRef.match(
      /^spectrasherpa:\/\/types\/(?<name>[A-Za-z0-9_]+)\/(?<major>\d+)\.(?<minor>\d+)$/
    );
    if (!match?.groups) {
      return null;
    }
    return {
      name: match.groups.name,
      major: Number.parseInt(match.groups.major, 10),
      minor: Number.parseInt(match.groups.minor, 10),
    };
  };

  const typeRefToDisplayName = (typeRef: string): string => {
    const parsed = parseTypeRef(typeRef);
    if (!parsed) return typeRef;
    return `${parsed.name}@${parsed.major}.${parsed.minor}`;
  };

  /** Derive visual category (dataset, model, target, ...) from a type_ref URI. */
  const getCategoryFromTypeRef = (typeRef: string): string => {
    const parsed = parseTypeRef(typeRef);
    if (!parsed) return "dataset";
    const registry = typeRegistry.value;
    if (registry?.types?.[parsed.name]?.category) {
      return registry.types[parsed.name].category;
    }
    return "dataset";
  };

  const isSubtypeName = (childName: string, parentName: string): boolean => {
    const fallbackSubtypeMap: Record<string, string | null> = {
      Spectrum: "Array1D",
      SpectralDataset: "Array2D",
      ScoreMatrix: "Array2D",
      LoadingMatrix: "Array2D",
    };

    const registry = typeRegistry.value;
    if (!registry) {
      let current: string | null = childName;
      const seen = new Set<string>();
      while (current && !seen.has(current)) {
        seen.add(current);
        if (current === parentName) return childName !== parentName;
        current = fallbackSubtypeMap[current] ?? null;
      }
      return false;
    }

    const seen = new Set<string>();
    let currentName: string | null = childName;

    while (currentName && !seen.has(currentName)) {
      seen.add(currentName);
      if (currentName === parentName) {
        return childName !== parentName;
      }
      const currentEntry: TypeRegistryEntry | undefined = registry.types[currentName];
      currentName = currentEntry?.parent ?? null;
    }
    return false;
  };

  const validateTypeRefs = (
    sourceTypeRef: string,
    targetTypeRef: string
  ): { isValid: boolean; error?: string; dataType?: string } => {
    const source = parseTypeRef(sourceTypeRef);
    const target = parseTypeRef(targetTypeRef);

    if (!source) {
      return {
        isValid: false,
        error: `Malformed source type_ref: ${sourceTypeRef}`,
      };
    }
    if (!target) {
      return {
        isValid: false,
        error: `Malformed target type_ref: ${targetTypeRef}`,
      };
    }

    if (source.name === target.name) {
      if (source.major === target.major) {
        return {
          isValid: true,
          dataType: `${source.name}@${source.major}.${source.minor}`,
        };
      }
      return {
        isValid: false,
        error: `Version mismatch: ${typeRefToDisplayName(sourceTypeRef)} cannot connect to ${typeRefToDisplayName(targetTypeRef)} (major version differs)`,
        dataType: `${source.name}@${source.major}.${source.minor}`,
      };
    }

    // Subtype compatibility (child output to parent input).
    if (isSubtypeName(source.name, target.name)) {
      return {
        isValid: true,
        dataType: `${source.name}@${source.major}.${source.minor}`,
      };
    }

    return {
      isValid: false,
      error: `Type mismatch: ${typeRefToDisplayName(sourceTypeRef)} cannot connect to ${typeRefToDisplayName(targetTypeRef)}`,
      dataType: `${source.name}@${source.major}.${source.minor}`,
    };
  };

  function resolveBackendNodeId(frontendNodeId: number): string {
    const existing = frontendToBackendNodeIds.value.get(frontendNodeId);
    if (existing) {
      return existing;
    }
    const generated = String(frontendNodeId);
    frontendToBackendNodeIds.value.set(frontendNodeId, generated);
    backendToFrontendNodeIds.value.set(generated, frontendNodeId);
    return generated;
  }

  function resolveFrontendNodeId(backendNodeId: string): number | null {
    const key = String(backendNodeId);
    if (backendToFrontendNodeIds.value.has(key)) {
      return backendToFrontendNodeIds.value.get(key) ?? null;
    }
    const parsed = Number.parseInt(key, 10);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
    return null;
  }

  function clearNodeIdMappings(): void {
    frontendToBackendNodeIds.value.clear();
    backendToFrontendNodeIds.value.clear();
  }

  // Helper: Convert frontend nodes/edges to backend format
  function toBackendFormat(): { nodes: BackendWorkflowNode[]; edges: BackendWorkflowEdge[] } {
    const backendNodes: BackendWorkflowNode[] = nodes.value.map((n) => ({
      node_id: resolveBackendNodeId(n.id),
      node_type: normalizeNodeType(n.type),
      label: n.type,
      // Map UI parameter names to backend parameter names
      parameters: mapParamsToBackend(n.type, n.params),
      position_x: n.x,
      position_y: n.y,
    }));

    const backendEdges: BackendWorkflowEdge[] = edges.value.map((e) => ({
      from_node_id: resolveBackendNodeId(e.from),
      to_node_id: resolveBackendNodeId(e.to),
      from_output: e.fromPort || "default",
      to_input: e.toPort || "default",
    }));

    return { nodes: backendNodes, edges: backendEdges };
  }

  // Helper: Convert backend format to frontend nodes/edges
  function fromBackendFormat(
    backendNodes: BackendWorkflowNode[],
    backendEdges: BackendWorkflowEdge[]
  ): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } {
    clearNodeIdMappings();
    const usedIds = new Set<number>();
    let fallbackId = -1;
    const nodeIdMap = new Map<string, number>();

    const resolveNodeId = (rawId: unknown): number => {
      const key = rawId === undefined || rawId === null ? "" : String(rawId);
      if (nodeIdMap.has(key)) {
        return nodeIdMap.get(key) as number;
      }

      const parsed = Number.parseInt(key, 10);
      let resolved = Number.isFinite(parsed) ? parsed : NaN;

      if (!Number.isFinite(resolved) || usedIds.has(resolved)) {
        while (usedIds.has(fallbackId)) {
          fallbackId -= 1;
        }
        resolved = fallbackId;
        fallbackId -= 1;
      }

      usedIds.add(resolved);
      nodeIdMap.set(key, resolved);
      if (key) {
        frontendToBackendNodeIds.value.set(resolved, key);
        backendToFrontendNodeIds.value.set(key, resolved);
      }
      return resolved;
    };

    const frontendNodes: WorkflowNode[] = backendNodes.map((n) => {
      const frontendType = normalizeNodeType(n.node_type);
      return {
        id: resolveNodeId(n.node_id),
        type: frontendType,
        x: n.position_x || 100,
        y: n.position_y || 100,
        // Map backend parameter names to UI parameter names
        params: mapParamsFromBackend(frontendType, n.parameters || {}),
      };
    });

    const frontendEdges: WorkflowEdge[] = backendEdges.map((e) => ({
      from: resolveNodeId(e.from_node_id),
      to: resolveNodeId(e.to_node_id),
      fromPort: e.from_output !== "default" ? e.from_output : undefined,
      toPort: e.to_input !== "default" ? e.to_input : undefined,
    }));

    return { nodes: frontendNodes, edges: frontendEdges };
  }

  // Actions
  function loadTemplate(templateId: string) {
    const template = TEMPLATES[templateId];
    if (!template) {
      console.warn(`Template not found: ${templateId}`);
      return false;
    }

    // Deep copy the template data and normalize node types to dot format
    nodes.value = JSON.parse(JSON.stringify(template.nodes)).map((node: WorkflowNode) => ({
      ...node,
      type: normalizeNodeType(node.type),
    }));
    clearNodeIdMappings();
    for (const node of nodes.value) {
      resolveBackendNodeId(node.id);
    }
    edges.value = JSON.parse(JSON.stringify(template.edges));
    validateAllEdges();
    currentTemplateId.value = templateId;
    workflowName.value = template.name;
    hasUnsavedChanges.value = false;

    return true;
  }

  function clearWorkflow() {
    nodes.value = [];
    edges.value = [];
    clearNodeIdMappings();
    currentTemplateId.value = null;
    workflowName.value = "Untitled Workflow";
    workflowId.value = null;
    workflowDescription.value = "";
    workflowHash.value = null;
    hasUnsavedChanges.value = false;
    lastExecutionResults.value = null;
    lastExecutionDiagnostics.value = {};
    workflowWarnings.value = [];
  }

  // API Methods
  async function saveWorkflow(): Promise<number> {
    isLoading.value = true;
    try {
      const { nodes: backendNodes, edges: backendEdges } = toBackendFormat();

      if (workflowId.value) {
        // Update existing workflow
        const response = await api.put(`/workflows/${workflowId.value}`, {
          name: workflowName.value,
          description: workflowDescription.value,
          status: "draft",
          nodes: backendNodes,
          edges: backendEdges,
        });
        workflowHash.value = response.data.integrity_hash || null;
        hasUnsavedChanges.value = false;
        return response.data.id;
      } else {
        // Create new workflow
        const payload: WorkflowCreatePayload = {
          name: workflowName.value,
          description: workflowDescription.value,
          status: "draft",
          nodes: backendNodes,
          edges: backendEdges,
        };
        const response = await api.post("/workflows", payload);
        workflowId.value = response.data.id;
        workflowHash.value = response.data.integrity_hash || null;
        hasUnsavedChanges.value = false;
        return response.data.id;
      }
    } finally {
      isLoading.value = false;
    }
  }

  async function loadWorkflow(id: number): Promise<void> {
    isLoading.value = true;
    try {
      const response = await api.get(`/workflows/${id}`);
      const data = response.data;

      workflowId.value = data.id;
      workflowName.value = data.name;
      workflowDescription.value = data.description || "";
      workflowHash.value = data.integrity_hash || null;
      workflowWarnings.value = Array.isArray(data.warnings)
        ? data.warnings.filter((w: unknown): w is string => typeof w === "string")
        : [];

      const converted = fromBackendFormat(data.nodes || [], data.edges || []);
      nodes.value = converted.nodes;
      edges.value = converted.edges;
      validateAllEdges();

      currentTemplateId.value = null;
      hasUnsavedChanges.value = false;
    } finally {
      isLoading.value = false;
    }
  }

  async function listWorkflows(): Promise<WorkflowListItem[]> {
    const response = await api.get<WorkflowListItem[]>("/workflows");
    return response.data;
  }

  async function deleteWorkflow(id: number): Promise<void> {
    await api.delete(`/workflows/${id}`);
    if (workflowId.value === id) {
      clearWorkflow();
    }
  }

  async function executeWorkflow(
    initialData?: ParamsMap
  ): Promise<WorkflowExecuteResponse> {
    // Always save if not saved OR if there are unsaved changes (WYSIWYG principle)
    if (!workflowId.value || hasUnsavedChanges.value) {
      await saveWorkflow();
    }

    // Mark all nodes as running before execution
    for (const node of nodes.value) {
      setNodeExecutionState(node.id, { status: "running" });
    }

    isLoading.value = true;
    try {
      const response = await api.post(`/workflows/${workflowId.value}/execute`, {
        initial_data: initialData || {},
      });

      // Store results and integrity hash
      lastExecutionResults.value = response.data.results;
      lastExecutionDiagnostics.value = response.data.diagnostics || {};
      if (response.data.integrity_hash) {
        workflowHash.value = response.data.integrity_hash;
      }

      // Process node statuses from backend response
      const nodeStatuses = response.data.node_statuses || {};
      for (const node of nodes.value) {
        const backendNodeId = resolveBackendNodeId(node.id);
        const status = nodeStatuses[backendNodeId] ?? nodeStatuses[String(node.id)];
        const result = response.data.results?.[backendNodeId] ?? response.data.results?.[String(node.id)];
        const normalizedStatus = normalizeBackendExecutionStatus(status);
        const hasResult = result !== undefined;

        // Update node execution state based on status
        if (normalizedStatus === "completed" || (normalizedStatus === null && hasResult)) {
          // Extract shape information from result if available
          let outputShape: number[] | null = null;
          let outputType: string | null = null;

          if (result) {
            const primaryResult = (result && typeof result === "object" && "default" in result) ? result.default : result;
            if (primaryResult?.type) {
              outputType = primaryResult.type;
            }
            if (primaryResult?.shape && Array.isArray(primaryResult.shape)) {
              outputShape = primaryResult.shape;
            }
            // Handle NDDataset with n_samples and n_features
            if (primaryResult?.n_samples !== undefined && primaryResult?.n_features !== undefined) {
              outputShape = [primaryResult.n_samples, primaryResult.n_features];
            }
          }

          setNodeExecutionState(node.id, {
            status: "completed",
            error_message: null,
            error_details: null,
            last_executed: new Date().toISOString(),
            output_shape: outputShape,
            output_type: outputType,
          });
        } else if (normalizedStatus === "error") {
          // Extract error message from response or use generic message
          const errorMsg = response.data.error || "Node execution failed";
          setNodeExecutionState(node.id, {
            status: "error",
            error_message: errorMsg,
            error_details: errorMsg, // Could be enhanced with stack trace
            last_executed: new Date().toISOString(),
            output_shape: null,
            output_type: null,
          });
        } else if (normalizedStatus === "running") {
          setNodeExecutionState(node.id, { status: "running" });
        } else {
          // Pending/unknown/non-executed node.
          setNodeExecutionState(node.id, { status: "pending" });
        }
      }

      // Clear stale flag after successful execution
      clearWorkflowStale();

      return response.data;
    } catch (error: unknown) {
      // Mark all nodes as error on workflow execution failure
      const errorMsg = getErrorMessage(error, "Execution failed");
      for (const node of nodes.value) {
        setNodeExecutionState(node.id, {
          status: "error",
          error_message: errorMsg,
          error_details: errorMsg,
        });
      }
      throw error;
    } finally {
      isLoading.value = false;
    }
  }

  async function executeNode(
    nodeId: string,
    initialData?: ParamsMap
  ): Promise<WorkflowExecuteResponse> {
    // Always save if not saved OR if there are unsaved changes (WYSIWYG principle)
    if (!workflowId.value || hasUnsavedChanges.value) {
      await saveWorkflow();
    }

    // Mark target node and its dependencies as running
    const parsedNodeId = typeof nodeId === "string" ? Number.parseInt(nodeId, 10) : nodeId;
    const nodeIdNum = Number.isFinite(parsedNodeId) ? parsedNodeId : resolveFrontendNodeId(nodeId);
    const backendNodeId = nodeIdNum !== null ? resolveBackendNodeId(nodeIdNum) : String(nodeId);
    if (nodeIdNum !== null) {
      setNodeExecutionState(nodeIdNum, { status: "running" });
    }

    isLoading.value = true;
    try {
      const response = await api.post(`/workflows/${workflowId.value}/execute`, {
        node_id: backendNodeId,
        initial_data: initialData || {},
      });

      // Update results for the specific node
      if (!lastExecutionResults.value) {
        lastExecutionResults.value = {};
      }
      Object.assign(lastExecutionResults.value, response.data.results);
      if (response.data.diagnostics) {
        lastExecutionDiagnostics.value = {
          ...lastExecutionDiagnostics.value,
          ...response.data.diagnostics,
        };
      }

      // Process node statuses from backend response
      const nodeStatuses = response.data.node_statuses || {};
      for (const node of nodes.value) {
        const currentBackendNodeId = resolveBackendNodeId(node.id);
        const status = nodeStatuses[currentBackendNodeId] ?? nodeStatuses[String(node.id)];
        const result = response.data.results?.[currentBackendNodeId] ?? response.data.results?.[String(node.id)];
        const normalizedStatus = normalizeBackendExecutionStatus(status);
        const hasResult = result !== undefined;

        // Update node execution state based on status
        if (normalizedStatus === "completed" || (normalizedStatus === null && hasResult)) {
          // Extract shape information from result if available
          let outputShape: number[] | null = null;
          let outputType: string | null = null;

          if (result) {
            const primaryResult = (result && typeof result === "object" && "default" in result) ? result.default : result;
            if (primaryResult?.type) {
              outputType = primaryResult.type;
            }
            if (primaryResult?.shape && Array.isArray(primaryResult.shape)) {
              outputShape = primaryResult.shape;
            }
            // Handle NDDataset with n_samples and n_features
            if (primaryResult?.n_samples !== undefined && primaryResult?.n_features !== undefined) {
              outputShape = [primaryResult.n_samples, primaryResult.n_features];
            }
          }

          setNodeExecutionState(node.id, {
            status: "completed",
            error_message: null,
            error_details: null,
            last_executed: new Date().toISOString(),
            output_shape: outputShape,
            output_type: outputType,
          });
        } else if (normalizedStatus === "error") {
          const errorMsg = response.data.error || "Node execution failed";
          setNodeExecutionState(node.id, {
            status: "error",
            error_message: errorMsg,
            error_details: errorMsg,
            last_executed: new Date().toISOString(),
            output_shape: null,
            output_type: null,
          });
        } else if (normalizedStatus === "running") {
          setNodeExecutionState(node.id, { status: "running" });
        }
      }

      return response.data;
    } catch (error: unknown) {
      // Mark node as error
      const errorMsg = getErrorMessage(error, "Execution failed");
      if (nodeIdNum !== null) {
        setNodeExecutionState(nodeIdNum, {
          status: "error",
          error_message: errorMsg,
          error_details: errorMsg,
        });
      }
      throw error;
    } finally {
      isLoading.value = false;
    }
  }

  /**
   * Execute a trial run of a node with trial parameters.
   *
   * This is used by DetailView to run a node with temporary parameters
   * without persisting anything to the workflow. Creates a fresh execution
   * context (no caching) for each trial.
   *
   * @param targetNodeId - The node to execute with trial params
   * @param trialParams - Trial parameters to override for target node
   * @param initialData - Initial data for DATA nodes (optional)
   * @returns Trial execution result
   */
  async function executeTrial(
    targetNodeId: string,
    trialParams: ParamsMap,
    initialData?: ParamsMap
  ): Promise<TrialExecuteResponse> {
    const targetFrontendId = Number.parseInt(targetNodeId, 10);
    const resolvedTargetNodeId = Number.isFinite(targetFrontendId)
      ? resolveBackendNodeId(targetFrontendId)
      : targetNodeId;

    // Build nodes list from current workflow (using backend format)
    const trialNodes = nodes.value.map((node) => ({
      node_id: resolveBackendNodeId(node.id),
      node_type: normalizeNodeType(node.type),
      parameters: node.params || {},
    }));

    // Build edges list from current workflow
    const trialEdges = edges.value.map((edge) => ({
      from_node_id: resolveBackendNodeId(edge.from),
      to_node_id: resolveBackendNodeId(edge.to),
      from_output: edge.fromPort || "default",
      to_input: edge.toPort || "default",
    }));

    try {
      const response = await api.post("/workflows/trial/execute", {
        target_node_id: resolvedTargetNodeId,
        trial_params: trialParams,
        nodes: trialNodes,
        edges: trialEdges,
        initial_data: initialData || {},
      });
      return response.data;
    } catch (error: unknown) {
      // Return error in the same format as backend
      return {
        target_node_id: targetNodeId,
        status: "error",
        result: null,
        error: getErrorMessage(error, String(error)),
      };
    }
  }

  async function exportToPython(): Promise<string> {
    if (!workflowId.value) {
      await saveWorkflow();
    }

    const response = await api.get(`/workflows/${workflowId.value}/export/python`);
    return response.data.python_code;
  }

  async function exportToNotebook(): Promise<Record<string, unknown>> {
    if (!workflowId.value) {
      await saveWorkflow();
    }

    const response = await api.get(`/workflows/${workflowId.value}/export/notebook`);
    return response.data.notebook;
  }

  async function fetchAvailableDatasets(): Promise<AvailableDatasets> {
    const response = await api.get("/datasets/available");
    availableDatasets.value = response.data;
    return response.data;
  }

  /**
   * Cache for SpectroChemPy example files by dataset.
   * Avoids redundant API calls when switching between datasets.
   */
  const spectroChemPyFileCache = ref<Map<string, Array<{label: string; value: string; path: string}>>>(new Map());

  /**
   * Fetch available files for a SpectroChemPy example dataset.
   * Results are cached to avoid redundant API calls.
   *
   * @param dataset - Dataset name (irdata, ramandata, nmrdata, galacticdata)
   * @returns Array of file options for dropdown
   */
  async function fetchSpectroChemPyFiles(dataset: string): Promise<Array<{label: string; value: string; path: string}>> {
    // Check cache first
    if (spectroChemPyFileCache.value.has(dataset)) {
      const cached = spectroChemPyFileCache.value.get(dataset)!;
      console.log(`[fetchSpectroChemPyFiles] Returning ${cached.length} cached files for ${dataset}`);
      return cached;
    }

    // Ensure API key is set (fallback for dev mode)
    if (!localStorage.getItem("api_key") && import.meta.env.DEV) {
      const defaultKey = import.meta.env.VITE_DEFAULT_API_KEY || "default-local-key";
      console.log(`[fetchSpectroChemPyFiles] Setting default API key for dev mode`);
      localStorage.setItem("api_key", defaultKey);
    }

    try {
      console.log(`[fetchSpectroChemPyFiles] Fetching files from API for ${dataset}...`);
      console.log(`[fetchSpectroChemPyFiles] API key present:`, !!localStorage.getItem("api_key"));
      const response = await api.get("/workflows/spectrochempy-examples");
      const allFiles = response.data;

      console.log(`[fetchSpectroChemPyFiles] API returned datasets:`, Object.keys(allFiles));

      // Cache all datasets at once (response contains all dataset files)
      for (const [datasetName, files] of Object.entries(allFiles)) {
        const typedFiles = Array.isArray(files) ? files : [];
        spectroChemPyFileCache.value.set(
          datasetName,
          typedFiles as Array<{ label: string; value: string; path: string }>
        );
        console.log(`[fetchSpectroChemPyFiles] Cached ${typedFiles.length} files for ${datasetName}`);
      }

      const result = allFiles[dataset] || [];
      console.log(`[fetchSpectroChemPyFiles] Returning ${result.length} files for ${dataset}`, result.length > 0 ? result[0] : 'empty');
      return result;
    } catch (error: unknown) {
      console.error(`[fetchSpectroChemPyFiles] Failed for ${dataset}:`, error);
      console.error(`[fetchSpectroChemPyFiles] Error message:`, getErrorMessage(error));
      return [];
    }
  }

  /**
   * Get available SpectroChemPy dataset names.
   * Returns dataset names from cache, or empty array if not yet loaded.
   */
  const availableSpectroChemPyDatasets = computed(() => {
    return Array.from(spectroChemPyFileCache.value.keys());
  });

  /**
   * Clear SpectroChemPy file cache.
   * Call when backend version changes or on manual refresh.
   */
  function clearSpectroChemPyFileCache() {
    spectroChemPyFileCache.value.clear();
  }

  /**
   * Caches for reference dataset options (fetched from /builder/reference-datasets API).
   * A single API call populates both eigenvector and sklearn caches.
   */
  const eigenvectorDatasetCache = ref<Array<{label: string; value: string}>>([]);
  const sklearnDatasetCache = ref<Array<{label: string; value: string}>>([]);

  /**
   * Fetch available reference datasets from the API.
   * Populates both eigenvector and sklearn caches from one call.
   */
  async function fetchReferenceDatasets(): Promise<void> {
    if (eigenvectorDatasetCache.value.length > 0 && sklearnDatasetCache.value.length > 0) {
      return;
    }
    try {
      const response = await api.get("/builder/reference-datasets");
      const toOptions = (arr: Array<{name: string; label: string}>) =>
        arr.map(d => ({ label: d.label, value: d.name }));
      eigenvectorDatasetCache.value = toOptions(response.data.eigenvector || []);
      sklearnDatasetCache.value = toOptions(response.data.sklearn || []);
    } catch (error: unknown) {
      console.error("[fetchReferenceDatasets] Failed:", getErrorMessage(error));
    }
  }

  // Backward-compatible alias
  const fetchEigenvectorDatasets = fetchReferenceDatasets;

  /**
   * Fetch type registry metadata used for connection compatibility checks.
   */
  async function fetchTypeRegistry(force: boolean = false): Promise<void> {
    if (isLoadingTypeRegistry.value) return;
    if (!force && typeRegistry.value) return;

    isLoadingTypeRegistry.value = true;
    typeRegistryLoadError.value = null;

    try {
      const response = await api.get<TypeRegistryPayload>("/workflows/types/registry", {
        headers: {
          "Cache-Control": "no-cache",
          Pragma: "no-cache",
        },
      });
      typeRegistry.value = response.data;
    } catch (error: unknown) {
      const errMsg = getErrorMessage(error, "Failed to load type registry");
      typeRegistryLoadError.value = errMsg;
      console.error("[WorkflowStore] Failed to load type registry:", errMsg);
    } finally {
      isLoadingTypeRegistry.value = false;
    }
  }

  /**
   * Fetch node library from backend (validation schemas, parameter definitions).
   * Call this on app initialization.
   */
  async function fetchNodeLibrary(force: boolean = false): Promise<void> {
    if (isLoadingNodeLibrary.value) return;

    isLoadingNodeLibrary.value = true;
    nodeLibraryLoadError.value = null;

    try {
      const response = await api.get<NodeLibraryResponse>("/workflows/nodes/library", {
        headers: {
          'Cache-Control': 'no-cache',  // Force fresh fetch
          'Pragma': 'no-cache'
        }
      });
      const library = new Map<string, NodeTypeMetadata>();

      for (const nodeMetadata of response.data.nodes) {
        library.set(nodeMetadata.node_type, nodeMetadata);
      }

      const newVersion = response.data.version || "1.0.0";
      const oldVersion = nodeLibraryVersion.value;

      nodeLibrary.value = library;
      nodeLibraryVersion.value = newVersion;

      if (oldVersion && oldVersion !== newVersion && !force) {
        console.warn(`[WorkflowStore] Backend version changed: ${oldVersion} → ${newVersion}. Node library refreshed.`);
      } else {
        console.log(`[WorkflowStore] Loaded ${library.size} node types from backend (v${newVersion})`);
      }

      // Keep type compatibility registry aligned with node metadata refresh.
      await fetchTypeRegistry(force || !typeRegistry.value);
    } catch (error: unknown) {
      const errMsg = getErrorMessage(error, "Failed to load node library");
      nodeLibraryLoadError.value = errMsg;
      console.error("[WorkflowStore] Failed to load node library:", errMsg);
    } finally {
      isLoadingNodeLibrary.value = false;
    }
  }

  /**
   * Check if backend version has changed and refetch if needed.
   * Call this on visibility change or periodically.
   */
  async function checkAndRefreshNodeLibrary(): Promise<void> {
    if (!nodeLibraryVersion.value) {
      // Initial load
      await fetchNodeLibrary();
      return;
    }

    try {
      // Quick version check (lightweight)
      const response = await api.get<NodeLibraryResponse>("/workflows/nodes/library", {
        headers: { 'Cache-Control': 'no-cache' }
      });
      const serverVersion = response.data.version || "1.0.0";

      if (serverVersion !== nodeLibraryVersion.value) {
        console.log(`[WorkflowStore] Backend updated (${nodeLibraryVersion.value} → ${serverVersion}), refreshing node library...`);
        await fetchNodeLibrary(true);
      }
    } catch (error) {
      // Silently fail - don't disrupt user experience
      console.debug("[WorkflowStore] Version check failed:", error);
    }
  }

  /**
   * Get metadata for a node type (from library).
   */
  function getNodeMetadata(nodeType: string): NodeTypeMetadata | null {
    // Map frontend node type to backend node type
    const backendType = normalizeNodeType(nodeType);
    return nodeLibrary.value.get(backendType) || null;
  }

  /**
   * Validate node parameters against metadata.
   * Returns array of validation errors (empty if valid).
   */
  function validateNodeParams(nodeType: string, params: ParamsMap): Array<{ param_name: string; message: string }> {
    const metadata = getNodeMetadata(nodeType);
    if (!metadata) {
      return [{ param_name: "_metadata", message: "Node metadata not available" }];
    }

    // Map frontend parameter names to backend names before validation
    // E.g., SMOOTH uses "window"/"poly" in UI but "size"/"order" in backend
    const mappedParams = mapParamsToBackend(nodeType, params);

    // Build reverse mapping to convert backend param names back to frontend names
    const paramMapping = getParamMapping(nodeType);
    const backendToFrontend: Record<string, string> = {};
    if (paramMapping) {
      for (const [frontend, backend] of Object.entries(paramMapping)) {
        backendToFrontend[backend] = frontend;
      }
    }

    const errors: Array<{ param_name: string; message: string }> = [];

    for (const paramDef of metadata.parameters) {
      const value = mappedParams[paramDef.name];
      // Use frontend parameter name in error messages if mapping exists
      const displayParamName = backendToFrontend[paramDef.name] || paramDef.name;

      // Check required
      if (paramDef.required && (value === undefined || value === null || value === '')) {
        errors.push({
          param_name: displayParamName,
          message: `${paramDef.label} is required`,
        });
        continue;
      }

      // Skip validation if value is empty and not required
      if (value === undefined || value === null || value === '') {
        continue;
      }

      // Type validation
      if (paramDef.param_type === "number") {
        if (typeof value !== "number" || isNaN(value)) {
          errors.push({
            param_name: displayParamName,
            message: `${paramDef.label} must be a number`,
          });
          continue;
        }

        // Range validation (only validate if min/max are actual numbers, not null/undefined)
        if (paramDef.min_value !== undefined && paramDef.min_value !== null && value < paramDef.min_value) {
          errors.push({
            param_name: displayParamName,
            message: `${paramDef.label} must be ≥ ${paramDef.min_value}`,
          });
        }
        if (paramDef.max_value !== undefined && paramDef.max_value !== null && value > paramDef.max_value) {
          errors.push({
            param_name: displayParamName,
            message: `${paramDef.label} must be ≤ ${paramDef.max_value}`,
          });
        }
      } else if (paramDef.param_type === "boolean") {
        if (typeof value !== "boolean") {
          errors.push({
            param_name: displayParamName,
            message: `${paramDef.label} must be true or false`,
          });
        }
      }

      // Custom validation for n_components in PCA/PLS nodes
      if (paramDef.name === "n_components" && paramDef.param_type === "text") {
        const strValue = String(value).trim();
        const lowerValue = strValue.toLowerCase();

        // Check if it's "mle"
        if (lowerValue === "mle") {
          continue; // Valid
        }

        // Try to parse as number
        try {
          const numValue = parseFloat(strValue);

          if (isNaN(numValue)) {
            errors.push({
              param_name: displayParamName,
              message: `${paramDef.label} must be an integer (e.g., 5), 'mle', or float 0-1 (e.g., 0.95)`,
            });
            continue;
          }

          // Check if it's an integer >= 1
          if (Number.isInteger(numValue) && numValue >= 1) {
            continue; // Valid
          }

          // Check if it's a float between 0 and 1 (variance threshold)
          if (numValue > 0 && numValue < 1) {
            continue; // Valid
          }

          // Invalid number
          errors.push({
            param_name: displayParamName,
            message: `${paramDef.label} must be ≥ 1 (integer) or between 0-1 (variance threshold)`,
          });
        } catch (e) {
          errors.push({
            param_name: displayParamName,
            message: `${paramDef.label} must be an integer (e.g., 5), 'mle', or float 0-1 (e.g., 0.95)`,
          });
        }
      }
    }

    return errors;
  }

  /**
   * Set node execution state.
   */
  function setNodeExecutionState(nodeId: number, state: Partial<NodeExecutionState>) {
    const node = nodes.value.find((n) => n.id === nodeId);
    if (node) {
      node.executionState = { ...(node.executionState || { status: "pending" }), ...state };
    }
  }

  /**
   * Get node execution state.
   */
  function getNodeExecutionState(nodeId: number): NodeExecutionState | null {
    const node = nodes.value.find((n) => n.id === nodeId);
    return node?.executionState || null;
  }

  /**
   * Mark workflow as stale (modified since last execution).
   */
  function markWorkflowStale() {
    isWorkflowStale.value = true;
  }

  /**
   * Clear stale flag (after successful execution).
   */
  function clearWorkflowStale() {
    isWorkflowStale.value = false;
  }

  function addNode(node: WorkflowNode) {
    // Initialize execution state
    node.type = normalizeNodeType(node.type);
    node.executionState = { status: "pending" };
    nodes.value.push(node);
    resolveBackendNodeId(node.id);
    hasUnsavedChanges.value = true;
    markWorkflowStale();
  }

  function removeNode(nodeId: number) {
    const backendNodeId = frontendToBackendNodeIds.value.get(nodeId);
    if (backendNodeId) {
      backendToFrontendNodeIds.value.delete(backendNodeId);
    }
    frontendToBackendNodeIds.value.delete(nodeId);
    nodes.value = nodes.value.filter((n) => n.id !== nodeId);
    edges.value = edges.value.filter((e) => e.from !== nodeId && e.to !== nodeId);
    hasUnsavedChanges.value = true;
    markWorkflowStale();
  }

  function updateNode(nodeId: number, updates: Partial<WorkflowNode>) {
    const node = nodes.value.find((n) => n.id === nodeId);
    if (node) {
      Object.assign(node, updates);
      hasUnsavedChanges.value = true;
      markWorkflowStale();
    }
  }

  /**
   * Validate an edge connection between two nodes.
   * Checks if the output type of the source node is compatible with the input types of the target node.
   */
  function validateEdge(edge: WorkflowEdge): { isValid: boolean; error?: string; dataType?: string } {
    const sourceNode = nodes.value.find(n => n.id === edge.from);
    const targetNode = nodes.value.find(n => n.id === edge.to);

    if (!sourceNode || !targetNode) {
      return {
        isValid: false,
        error: "⚠️ Connection Error: Source or target node no longer exists. Please delete this connection."
      };
    }

    const sourceMetadata = getNodeMetadata(sourceNode.type);
    const targetMetadata = getNodeMetadata(targetNode.type);

    if (!sourceMetadata || !targetMetadata) {
      return {
        isValid: false,
        error: "⚠️ Validation Unavailable: Node type information is still loading. Please wait and try again."
      };
    }

    // Port-level validation (if ports are defined)
    if (sourceMetadata.output_ports && targetMetadata.input_ports) {
      // Get the specific output port (default to first output port if not specified)
      const outputPortName = edge.fromPort || "default";
      const outputPort = sourceMetadata.output_ports.find(p => p.name === outputPortName)
                         || sourceMetadata.output_ports[0]; // Fallback to first port

      // Get the specific input port (must be specified for multi-input nodes)
      let inputPort;
      if (edge.toPort) {
        inputPort = targetMetadata.input_ports.find(p => p.name === edge.toPort);
        if (!inputPort) {
          const availablePorts = targetMetadata.input_ports.map(p => `"${p.label}" (${typeRefToDisplayName(p.type_ref)})`).join(', ');
          return {
            isValid: false,
            error: `❌ Invalid Port: "${edge.toPort}" doesn't exist on ${targetMetadata.label}. Available ports: ${availablePorts}`
          };
        }
      } else if (targetMetadata.input_ports.length === 1) {
        // Single input port - auto-connect
        inputPort = targetMetadata.input_ports[0];
      } else {
        // Multi-input node but no port specified
        const availablePorts = targetMetadata.input_ports.map(p => `"${p.label}" (${typeRefToDisplayName(p.type_ref)})`).join(', ');
        return {
          isValid: false,
          error: `🔌 Select Input Port: ${targetMetadata.label} has multiple inputs. Please click the specific port: ${availablePorts}`
        };
      }

      if (!outputPort || !inputPort) {
        return {
          isValid: false,
          error: "❌ Missing source or target port metadata for this connection.",
        };
      }

      // type_ref-based validation
      const typeValidation = validateTypeRefs(outputPort.type_ref, inputPort.type_ref);
      if (!typeValidation.isValid) {
        return {
          isValid: false,
          error: `❌ ${typeValidation.error}. ${sourceMetadata.label}'s "${outputPort.label}" (${typeRefToDisplayName(outputPort.type_ref)}) cannot connect to ${targetMetadata.label}'s "${inputPort.label}" (${typeRefToDisplayName(inputPort.type_ref)}).`,
          dataType: typeValidation.dataType ?? typeRefToDisplayName(outputPort.type_ref),
        };
      }
      return {
        isValid: true,
        dataType: typeValidation.dataType ?? typeRefToDisplayName(outputPort.type_ref),
      };
    }

    // Hybrid validation: multi-output source (with output_ports) → legacy target (without input_ports)
    // Example: DataSourceNode (has "default" and "target" ports) → PCA/HCA (legacy single input)
    if (sourceMetadata.output_ports && !targetMetadata.input_ports) {
      // Get the default output port (what the executor will extract)
      const outputPortName = edge.fromPort || "default";
      const outputPort = sourceMetadata.output_ports.find(p => p.name === outputPortName)
                         || sourceMetadata.output_ports[0];

      if (!outputPort) {
        return {
          isValid: false,
          error: `❌ No output port found on ${sourceMetadata.label}. Available ports: ${sourceMetadata.output_ports.map(p => p.label).join(', ')}`
        };
      }

      // Derive category from type_ref to validate against legacy input_types
      const outputCategory = getCategoryFromTypeRef(outputPort.type_ref);
      const categoryToClassNames: Record<string, string[]> = {
        'dataset': ['NDDataset', 'array'],
        'target': ['array', 'list', 'any'],
        'model': ['PCAModel', 'PLSModel', 'PLSDAModel', 'HCAResult', 'any'],
        'config': ['dict', 'config', 'any'],
        'array': ['array', 'list', 'any'],
        'number': ['number', 'float', 'int', 'any'],
        'visualization': ['dict', 'plot', 'any'],
      };

      const inputTypes = targetMetadata.input_types;
      const compatibleClassNames = categoryToClassNames[outputCategory] || [outputCategory];

      // Check if any compatible class name is accepted by target
      const isCompatible = compatibleClassNames.some(className => inputTypes.includes(className))
                        || inputTypes.includes("any");

      if (!isCompatible) {
        return {
          isValid: false,
          error: `❌ Type Mismatch: ${sourceMetadata.label}'s "${outputPort.label}" port outputs "${typeRefToDisplayName(outputPort.type_ref)}" data, but ${targetMetadata.label} only accepts ${inputTypes.map(t => `"${t}"`).join(" or ")}. Try connecting from a different output port.`,
          dataType: typeRefToDisplayName(outputPort.type_ref),
        };
      }

      return { isValid: true, dataType: typeRefToDisplayName(outputPort.type_ref) };
    }

    // Legacy validation (backward compatibility for nodes without port metadata)
    const outputType = sourceMetadata.output_type;
    const inputTypes = targetMetadata.input_types;

    // Check if output type is compatible with any of the accepted input types
    const isCompatible = inputTypes.includes(outputType) || inputTypes.includes("any");

    if (!isCompatible) {
      return {
        isValid: false,
        error: `❌ Type Mismatch: ${sourceMetadata.label} outputs "${outputType}" data, but ${targetMetadata.label} only accepts ${inputTypes.map(t => `"${t}"`).join(" or ")}. Check the node documentation for compatible connections.`,
        dataType: outputType
      };
    }

    return { isValid: true, dataType: outputType };
  }

  /**
   * Validate all edges in the workflow and update their validation state.
   */
  function validateAllEdges() {
    for (const edge of edges.value) {
      const validation = validateEdge(edge);
      edge.isValid = validation.isValid;
      edge.validationError = validation.error || null;
      edge.dataType = validation.dataType || null;
    }
  }

  function addEdge(edge: WorkflowEdge) {
    // Prevent duplicates - same from/to/fromPort/toPort
    const exists = edges.value.some(
      (e) =>
        e.from === edge.from &&
        e.to === edge.to &&
        e.fromPort === edge.fromPort &&
        e.toPort === edge.toPort
    );
    if (!exists) {
      // Validate the edge before adding
      const validation = validateEdge(edge);
      edge.isValid = validation.isValid;
      edge.validationError = validation.error || null;
      edge.dataType = validation.dataType || null;

      edges.value.push(edge);
      hasUnsavedChanges.value = true;
      markWorkflowStale();
    }
  }

  function removeEdge(from: number, to: number) {
    edges.value = edges.value.filter(
      (e) => !(e.from === from && e.to === to)
    );
    hasUnsavedChanges.value = true;
    markWorkflowStale();
  }

  function setNodes(newNodes: WorkflowNode[]) {
    // Initialize execution state for all nodes
    for (const node of newNodes) {
      if (!node.executionState) {
        node.executionState = { status: "pending" };
      }
    }
    const nextNodeIds = new Set(newNodes.map((node) => node.id));
    for (const [frontendId, backendId] of frontendToBackendNodeIds.value.entries()) {
      if (!nextNodeIds.has(frontendId)) {
        frontendToBackendNodeIds.value.delete(frontendId);
        backendToFrontendNodeIds.value.delete(backendId);
      }
    }
    nodes.value = newNodes;
    for (const node of newNodes) {
      resolveBackendNodeId(node.id);
    }
    hasUnsavedChanges.value = true;
    markWorkflowStale();
  }

  function setEdges(newEdges: WorkflowEdge[]) {
    edges.value = newEdges.map((edge) => {
      const validation = validateEdge(edge);
      return {
        ...edge,
        isValid: validation.isValid,
        validationError: validation.error || null,
        dataType: validation.dataType || null,
      };
    });
    hasUnsavedChanges.value = true;
    markWorkflowStale();
  }

  return {
    // State
    nodes,
    edges,
    currentTemplateId,
    hasUnsavedChanges,
    workflowName,
    workflowId,
    workflowDescription,
    workflowHash,
    isLoading,
    lastExecutionResults,
    lastExecutionDiagnostics,
    workflowWarnings,
    availableDatasets,

    // Node library state
    nodeLibrary,
    isLoadingNodeLibrary,
    nodeLibraryLoadError,
    typeRegistry,
    isLoadingTypeRegistry,
    typeRegistryLoadError,
    isWorkflowStale,

    // Getters
    nodeCount,
    edgeCount,
    availableTemplates,

    // Local Actions
    loadTemplate,
    clearWorkflow,
    addNode,
    removeNode,
    updateNode,
    addEdge,
    removeEdge,
    setNodes,
    setEdges,

    // Node library & validation
    fetchNodeLibrary,
    fetchTypeRegistry,
    checkAndRefreshNodeLibrary,
    getNodeMetadata,
    normalizeNodeType,
    getLegacyNodeType,
    getReverseParamMapping,
    validateTypeRefs,
    validateNodeParams,
    validateEdge,
    validateAllEdges,
    resolveFrontendNodeId,
    resolveBackendNodeId,
    setNodeExecutionState,
    getNodeExecutionState,
    markWorkflowStale,
    clearWorkflowStale,

    // API Actions
    saveWorkflow,
    loadWorkflow,
    listWorkflows,
    deleteWorkflow,
    executeWorkflow,
    executeNode,
    executeTrial,
    exportToPython,
    exportToNotebook,
    fetchAvailableDatasets,
    fetchSpectroChemPyFiles,
    availableSpectroChemPyDatasets,
    clearSpectroChemPyFileCache,
    eigenvectorDatasetCache,
    sklearnDatasetCache,
    fetchReferenceDatasets,
    fetchEigenvectorDatasets,
  };
});
