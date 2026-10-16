/**
 * Model-centric summary of a saved run, in the order a chemometrician reads a
 * model: what it is, how its data were pretreated, how many samples each
 * statistic rests on, and calibration / cross-validation / test statistics
 * side by side.
 *
 * Every number comes from a retained, backend-computed record (regression
 * comparison statistics, evaluator metric records, classification metric
 * contracts). Nothing is recomputed here, and each statistic keeps the
 * population role its producer recorded, so a calibration fit can never be
 * shown as validation.
 */

export type SummaryRole = "calibration" | "cross_validation" | "held_out_test";
export const SUMMARY_ROLES: SummaryRole[] = ["calibration", "cross_validation", "held_out_test"];

export interface SavedNode {
  node_id: string;
  node_type: string;
  label?: string;
  parameters: Record<string, unknown>;
}
export interface SavedEdge { from_node_id: string; to_node_id: string; from_output: string; to_input: string }
export interface SavedDefinition { nodes: SavedNode[]; edges: SavedEdge[] }

interface PresentationEntry { presentation_id: string; kind: string; source_ports: string[] }
export type PresentationContracts = Record<string, { contract?: { presentations?: PresentationEntry[] } } | undefined>;

export interface SummarySource { nodeId: string; port: string; kind: string }

export interface RegressionStatistics {
  role: SummaryRole;
  target: string;
  target_units?: unknown;
  n: number | null;
  rmse: number | null;
  r2: number | null;
  bias: number | null;
  sep: number | null;
  slope: number | null;
  source: string;
}

export interface ClassificationStatistics {
  role: SummaryRole;
  n: number | null;
  accuracy: number | null;
  balancedAccuracy: number | null;
  labels: string[];
  confusion: number[][] | null;
  source: string;
}

export interface ComponentSelectionRow {
  components: number;
  rmsec: number | null;
  rmsecv: number | null;
  r2x: number | null;
  r2y: number | null;
  q2: number | null;
  foldMeanRmse: number | null;
  foldRmseSe: number | null;
}

export interface ComponentSelectionResponse {
  name: string;
  unit: string | null;
  rows: ComponentSelectionRow[];
  minimumMeanFoldRmse: number | null;
  oneStandardError: number | null;
}

export interface ComponentSelectionSummary {
  selectedComponents: number;
  selectionRule: string;
  selectionRuleStatus: string;
  requestedComponents: number;
  selectedInCurve: boolean;
  nCalibration: number;
  cvStatus: "available" | "unavailable";
  cvReason: string | null;
  cvMethod: string | null;
  cvFolds: number | null;
  cvGroups: number | null;
  splitDigest: string | null;
  scaling: string;
  responses: ComponentSelectionResponse[];
  source: string;
}

export interface PcaComponentSelectionSummary {
  selectedComponents: number;
  selectedInCurve: boolean;
  nCalibration: number;
  reconstructionSpace: string;
  cvMethod: string | null;
  cvFolds: number | null;
  cvReason: string | null;
  rows: Array<{ components: number; explainedIncremental: number | null; explainedCumulative: number | null;
    calibrationReconstruction: number | null; cvReconstruction: number | null }>;
}

export interface PlsdaComponentSelectionSummary {
  selectedComponents: number;
  requestedComponents: number;
  nCalibration: number;
  classes: string[];
  cvMethod: string | null;
  cvFolds: number | null;
  cvReason: string | null;
  rows: Array<{ components: number; calibrationBalancedAccuracy: number | null;
    cvBalancedAccuracy: number | null; cvAccuracy: number | null; cvMacroF1: number | null }>;
  suggestedComponents: number | null;
}

export interface ModelSummary {
  model: { nodeId: string; method: string; label: string; settings: Array<[string, string]> } | null;
  preprocessing: string[];
  regression: RegressionStatistics[];
  classification: ClassificationStatistics[];
  componentSelection: ComponentSelectionSummary | null;
  pcaComponentSelection: PcaComponentSelectionSummary | null;
  plsdaComponentSelection: PlsdaComponentSelectionSummary | null;
}

const METHODS: Record<string, string> = {
  "model.fitted_pls": "PLS regression",
  "model.fitted_pcr": "Principal component regression",
  "classification.plsda": "PLS-DA",
  "classification.knn": "k-nearest neighbours",
  "classification.simca": "SIMCA",
  "model.pca": "PCA",
  "model.mcr_als": "MCR-ALS",
};

const SUMMARY_KINDS = new Set(["regression_comparison", "metric_record", "statistics_summary"]);
const EVALUATOR = /^diagnostics\.(labeled_)?(regression|classification)_evaluator(?:_v2)?$|^diagnostics\.cross_validation$|^selection\.nested_cv$/;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);
const finite = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

function normalizeRole(value: unknown): SummaryRole | null {
  if (value === "calibration" || value === "training" || value === "train") return "calibration";
  if (value === "cross_validation" || value === "cv") return "cross_validation";
  if (value === "held_out_test" || value === "test") return "held_out_test";
  return null;
}

/** The primary fitted model: the first saved node of a known model family. */
export function primaryModelNode(definition: SavedDefinition | null): SavedNode | null {
  return definition?.nodes.find((node) => node.node_type in METHODS)
    ?? definition?.nodes.find((node) => /^(model|classification)\.(fitted_|pls|pca|mcr|simca|knn)/.test(node.node_type)
      && !/apply|predict/.test(node.node_type))
    ?? null;
}

/** Pretreatment steps upstream of the model, in the order they are applied. */
export function preprocessingChain(definition: SavedDefinition | null, modelNodeId: string): string[] {
  if (!definition) return [];
  const byId = new Map(definition.nodes.map((node) => [node.node_id, node]));
  const depth = new Map<string, number>();
  const visit = (id: string, level: number) => {
    for (const edge of definition.edges.filter((item) => item.to_node_id === id)) {
      if ((depth.get(edge.from_node_id) ?? -1) >= level) continue;
      depth.set(edge.from_node_id, level);
      visit(edge.from_node_id, level + 1);
    }
  };
  visit(modelNodeId, 1);
  return [...depth]
    .filter(([id]) => byId.get(id)?.node_type.startsWith("preprocess."))
    .sort((left, right) => right[1] - left[1])
    .map(([id]) => byId.get(id)?.label || byId.get(id)?.node_type.replace(/^preprocess\./, "").replace(/_/g, " ") || id);
}

/** Retained outputs the summary reads: comparisons and metric records of models and evaluators. */
export function summarySources(definition: SavedDefinition | null, contracts: PresentationContracts | null, modelNodeId: string | null): SummarySource[] {
  if (!definition) return [];
  const sources: SummarySource[] = [];
  for (const node of definition.nodes) {
    if (node.node_id !== modelNodeId && !EVALUATOR.test(node.node_type)) continue;
    if (node.node_id === modelNodeId && (node.node_type === "model.fitted_pls" || node.node_type === "model.pca" || node.node_type === "classification.plsda")) {
      sources.push({ nodeId: node.node_id, port: "component_curve", kind: "component_selection" });
    }
    if (node.node_type === "diagnostics.cross_validation") {
      sources.push({ nodeId: node.node_id, port: "cv_metrics", kind: "cross_validation_report" });
      continue;
    }
    for (const presentation of contracts?.[node.node_id]?.contract?.presentations ?? []) {
      if (!SUMMARY_KINDS.has(presentation.kind)) continue;
      for (const port of presentation.source_ports) {
        if (!sources.some((item) => item.nodeId === node.node_id && item.port === port)) {
          sources.push({ nodeId: node.node_id, port, kind: presentation.kind });
        }
      }
    }
  }
  return sources;
}

function plsdaComponentSelectionFromRecord(value: unknown): PlsdaComponentSelectionSummary | null {
  if (!isRecord(value) || value.schema_version !== "spectrasherpa-plsda-component-curve/1"
    || !Array.isArray(value.calibration) || !isRecord(value.cross_validation) || !Array.isArray(value.classes)) return null;
  const selected = finite(value.selected_components);
  const nCalibration = finite(value.n_calibration);
  if (selected == null || nCalibration == null || !value.classes.every((item) => typeof item === "string")) return null;
  const cv = value.cross_validation;
  const cvRows = cv.status === "available" && Array.isArray(cv.rows) ? cv.rows as unknown[] : [];
  const rows = (value.calibration as unknown[]).flatMap((entry, index) => {
    if (!isRecord(entry) || finite(entry.components) !== index + 1) return [];
    const held = isRecord(cvRows[index]) && cvRows[index].components === entry.components ? cvRows[index] : null;
    return [{ components: index + 1, calibrationBalancedAccuracy: finite(entry.balanced_accuracy),
      cvBalancedAccuracy: held ? finite(held.balanced_accuracy) : null,
      cvAccuracy: held ? finite(held.accuracy) : null, cvMacroF1: held ? finite(held.f1_macro) : null }];
  });
  const suggestion = isRecord(cv.suggestion) ? finite(cv.suggestion.maximum_balanced_accuracy) : null;
  return { selectedComponents: selected, requestedComponents: finite(value.requested_components) ?? selected,
    nCalibration, classes: value.classes as string[],
    cvMethod: cv.status === "available" && typeof cv.method === "string" ? cv.method : null,
    cvFolds: cv.status === "available" ? finite(cv.n_folds) : null,
    cvReason: cv.status === "available" ? null : typeof cv.reason === "string" ? cv.reason : "Cross-validation was not retained.",
    rows, suggestedComponents: suggestion };
}

function pcaComponentSelectionFromRecord(value: unknown): PcaComponentSelectionSummary | null {
  if (!isRecord(value) || value.schema_version !== "spectrasherpa-pca-component-curve/1"
    || !Array.isArray(value.calibration) || !isRecord(value.cross_validation)) return null;
  const selected = finite(value.selected_components);
  const nCalibration = finite(value.n_calibration);
  if (selected == null || nCalibration == null) return null;
  const cv = value.cross_validation;
  const cvRows = cv.status === "available" && Array.isArray(cv.rows) ? cv.rows as unknown[] : [];
  const rows = (value.calibration as unknown[]).flatMap((entry, index) => {
    if (!isRecord(entry) || finite(entry.components) !== index + 1) return [];
    const held = isRecord(cvRows[index]) && cvRows[index].components === entry.components ? cvRows[index] : null;
    return [{ components: index + 1, explainedIncremental: finite(entry.explained_x_incremental),
      explainedCumulative: finite(entry.explained_x_cumulative),
      calibrationReconstruction: finite(entry.reconstruction_rmse),
      cvReconstruction: held ? finite(held.pooled_reconstruction_rmse) : null }];
  });
  return { selectedComponents: selected, selectedInCurve: value.selected_in_curve === true, nCalibration,
    reconstructionSpace: typeof value.reconstruction_space === "string" ? value.reconstruction_space : "unknown",
    cvMethod: cv.status === "available" && typeof cv.method === "string" ? cv.method : null,
    cvFolds: cv.status === "available" ? finite(cv.n_folds) : null,
    cvReason: cv.status === "available" ? null : typeof cv.reason === "string" ? cv.reason : "Cross-validation was not retained.",
    rows };
}

function componentSelectionFromRecord(value: unknown, source: string): ComponentSelectionSummary | null {
  if (!isRecord(value) || value.schema_version !== "spectrasherpa-pls-component-curve/1"
    || !Array.isArray(value.calibration) || !isRecord(value.cross_validation)
    || !Array.isArray(value.response_names) || !Array.isArray(value.response_units)) return null;
  const selected = finite(value.selected_components);
  const count = finite(value.n_calibration);
  if (selected == null || count == null || value.response_names.length === 0
    || value.response_names.length !== value.response_units.length) return null;
  const cv = value.cross_validation;
  const cvAvailable = cv.status === "available" && Array.isArray(cv.rows);
  const cvRows = cvAvailable ? cv.rows as unknown[] : [];
  const calibrationRows = value.calibration as unknown[];
  const responseUnits = value.response_units as unknown[];
  const responses = (value.response_names as unknown[]).flatMap((name, responseIndex) => {
    if (typeof name !== "string" || !name.trim()) return [];
    const rows: ComponentSelectionRow[] = calibrationRows.flatMap((entry, index) => {
      if (!isRecord(entry) || finite(entry.components) !== index + 1) return [];
      const cvEntry = isRecord(cvRows[index]) && cvRows[index].components === entry.components ? cvRows[index] : null;
      const pick = (record: Record<string, unknown> | null, key: string) =>
        record && Array.isArray(record[key]) ? finite((record[key] as unknown[])[responseIndex]) : null;
      return [{
        components: index + 1,
        rmsec: pick(entry, "rmsec"), rmsecv: pick(cvEntry, "rmsecv"),
        r2x: finite(entry.r2x_cumulative), r2y: pick(entry, "r2y_cumulative"), q2: pick(cvEntry, "q2"),
        foldMeanRmse: pick(cvEntry, "fold_rmse_mean"), foldRmseSe: pick(cvEntry, "fold_rmse_standard_error"),
      }];
    });
    const suggestion = cvAvailable && Array.isArray(cv.suggestions) && isRecord(cv.suggestions[responseIndex])
      ? cv.suggestions[responseIndex] as Record<string, unknown> : null;
    return [{ name, unit: typeof responseUnits[responseIndex] === "string" ? responseUnits[responseIndex] as string : null,
      rows, minimumMeanFoldRmse: finite(suggestion?.minimum_mean_fold_rmse),
      oneStandardError: finite(suggestion?.one_standard_error) }];
  });
  if (!responses.length) return null;
  return {
    selectedComponents: selected, requestedComponents: finite(value.requested_components) ?? selected,
    selectionRule: typeof value.selection_rule === "string" ? value.selection_rule : "manual_parameter",
    selectionRuleStatus: typeof value.selection_rule_status === "string" ? value.selection_rule_status : "unverified",
    selectedInCurve: value.selected_in_curve === true,
    nCalibration: count, cvStatus: cvAvailable ? "available" : "unavailable",
    cvReason: cvAvailable ? null : typeof cv.reason === "string" ? cv.reason : "Cross-validation evidence was not retained.",
    cvMethod: cvAvailable && typeof cv.method === "string" ? cv.method : null,
    cvFolds: cvAvailable ? finite(cv.n_folds) : null,
    cvGroups: cvAvailable ? finite(cv.n_groups) : null,
    splitDigest: cvAvailable && typeof cv.split_digest === "string" ? cv.split_digest : null,
    scaling: typeof value.scaling === "string" ? value.scaling : "unknown",
    responses, source,
  };
}

function regressionFromComparison(value: unknown, source: string): RegressionStatistics[] {
  if (!isRecord(value) || value.schema_version !== "spectrasherpa-regression-comparison/1") return [];
  const role = normalizeRole(isRecord(value.metadata) ? value.metadata.role : null);
  const statistics = isRecord(value.statistics) ? value.statistics.targets : null;
  if (!role || !Array.isArray(statistics)) return [];
  return statistics.flatMap((entry, index) => {
    if (!isRecord(entry) || !isRecord(entry.metrics)) return [];
    const metrics = entry.metrics;
    const metadata = isRecord(value.metadata) ? value.metadata : {};
    const response = isRecord(metadata.response_identity) ? metadata.response_identity : {};
    const units = metadata.target_units ?? response.units;
    return [{
      role, target: typeof entry.target === "string" ? entry.target : "Response", n: finite(metrics.n_samples),
      target_units: "units" in entry ? entry.units : (Array.isArray(units) ? units[index] : units),
      rmse: finite(metrics.rmse), r2: finite(metrics.r2), bias: finite(metrics.bias), sep: finite(metrics.sep),
      slope: finite(metrics.slope), source,
    }];
  });
}

function regressionFromCrossValidation(value: unknown, source: string): RegressionStatistics[] {
  if (!isRecord(value) || value.task_type !== "regression" || !isRecord(value.overall_metrics)) return [];
  const metrics = value.overall_metrics;
  return [{
    role: "cross_validation", target: "Response", n: finite(metrics.n_samples ?? value.n_samples),
    target_units: value.target_units,
    rmse: finite(metrics.rmsecv ?? metrics.rmse), r2: finite(metrics.r2_cv ?? metrics.r2), bias: finite(metrics.bias),
    sep: finite(metrics.sep), slope: finite(metrics.slope), source,
  }];
}

function classificationFromEvaluation(value: unknown, source: string): ClassificationStatistics[] {
  if (!isRecord(value) || value.task_type !== "classification" || !Array.isArray(value.confusion_matrix)) return [];
  const authority = isRecord(value.population_authority) ? value.population_authority : null;
  const role = normalizeRole(authority?.role) ?? null;
  if (!role) return [];
  return [{
    role, n: finite(value.n_samples), accuracy: finite(value.accuracy), balancedAccuracy: finite(value.balanced_accuracy),
    labels: Array.isArray(value.labels) ? value.labels.map(String) : [],
    confusion: value.confusion_matrix as number[][], source,
  }];
}

function classificationFromModelMetrics(value: unknown, source: string): ClassificationStatistics[] {
  if (!isRecord(value) || value.task_type !== "classification" || !isRecord(value.splits)) return [];
  const matrices = isRecord(value.confusion_matrices) ? value.confusion_matrices : {};
  const labels = Array.isArray(value.classes) ? value.classes.map(String) : [];
  return Object.entries(value.splits).flatMap(([split, metrics]) => {
    const role = normalizeRole(split);
    if (!role || !isRecord(metrics)) return [];
    const confusion = Array.isArray(matrices[split]) ? matrices[split] as number[][] : null;
    const n = confusion ? confusion.flat().reduce((total, item) => total + (finite(item) ?? 0), 0) : null;
    return [{
      role, n, accuracy: finite(metrics.accuracy), balancedAccuracy: finite(metrics.balanced_accuracy),
      labels, confusion, source,
    }];
  });
}

const METHOD_SETTINGS: Array<[string, string, (value: unknown, nodeType: string) => string | null]> = [
  ["n_components", "Components", (value, type) => typeof value === "number"
    ? `${value} ${/pls|plsda/.test(type) ? "latent variable" : "component"}${value === 1 ? "" : "s"}` : null],
  ["scale", "X scaling", (value) => typeof value === "boolean" ? (value ? "Autoscaled" : "Mean-centred") : null],
  ["n_neighbors", "Neighbours", (value) => typeof value === "number" ? String(value) : null],
  ["metric", "Distance", (value) => typeof value === "string" ? value : null],
  ["confidence_level", "Confidence level", (value) => typeof value === "number" ? `${Number((value * 100).toPrecision(4))}%` : null],
];

/** Assemble the summary from the saved definition, effective parameters and retained records. */
export function buildModelSummary(
  definition: SavedDefinition | null,
  effectiveParameters: Record<string, Record<string, unknown>> | null | undefined,
  records: Array<{ source: SummarySource; value: unknown }>,
): ModelSummary {
  const node = primaryModelNode(definition);
  const regression: RegressionStatistics[] = [];
  const classification: ClassificationStatistics[] = [];
  let componentSelection: ComponentSelectionSummary | null = null;
  let pcaComponentSelection: PcaComponentSelectionSummary | null = null;
  let plsdaComponentSelection: PlsdaComponentSelectionSummary | null = null;
  for (const { source, value } of records) {
    const key = `${source.nodeId}/${source.port}`;
    if (source.port === "component_curve" && source.nodeId === node?.node_id) {
      componentSelection = componentSelectionFromRecord(value, key);
      pcaComponentSelection = pcaComponentSelectionFromRecord(value);
      plsdaComponentSelection = plsdaComponentSelectionFromRecord(value);
    }
    regression.push(...regressionFromComparison(value, key), ...regressionFromCrossValidation(value, key));
    classification.push(...classificationFromEvaluation(value, key), ...classificationFromModelMetrics(value, key));
  }
  let model: ModelSummary["model"] = null;
  if (node) {
    // Effective parameters are what ran; authored ones are only a fallback for
    // runs that predate their retention, never current defaults.
    const parameters = effectiveParameters?.[node.node_id] ?? node.parameters ?? {};
    const settings = METHOD_SETTINGS.flatMap(([key, label, format]) => {
      const text = format(parameters[key], node.node_type);
      return text ? [[label, text] as [string, string]] : [];
    });
    model = { nodeId: node.node_id, method: METHODS[node.node_type] ?? node.label ?? node.node_type, label: node.label ?? node.node_id, settings };
  }
  const unique = <T extends { role: SummaryRole; source: string }>(items: T[], key: (item: T) => string) =>
    [...new Map(items.map((item) => [key(item), item])).values()];
  return {
    model,
    preprocessing: node ? preprocessingChain(definition, node.node_id) : [],
    regression: unique(regression, (item) => `${item.role}|${item.target}|${item.source}`),
    classification: unique(classification, (item) => `${item.role}|${item.source}`),
    componentSelection,
    pcaComponentSelection,
    plsdaComponentSelection,
  };
}

/** Name of the error statistic in the conventional chemometric vocabulary. */
export function rmseName(role: SummaryRole): string {
  return role === "calibration" ? "RMSEC" : role === "cross_validation" ? "RMSECV" : "RMSEP";
}

/** Name of the coefficient of determination for each population. */
export function r2Name(role: SummaryRole): string {
  return role === "calibration" ? "R² (calibration)" : role === "cross_validation" ? "Q² (cross-validated R²)" : "R² (test set)";
}
