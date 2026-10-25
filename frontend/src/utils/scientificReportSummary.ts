import type { ReportData, RunReportEntry } from "./reportGenerator";
import { reportGroups, reportRows, reportMarkdownText } from "./reportValues";
import { scientificErrorMetricLabel, scientificMetricKey } from "./scientificDisplay";
import { resolveMethodHelpUrl } from "./documentation";
import type { ScientificValueDescriptor } from "@/stores/workflow-types";
import { formatTimestamp } from "./format";

type Row = [string, string];
interface SummaryGroup { title: string; rows: Row[]; notices: string[]; table?: { headers: string[]; rows: string[][] } }

// Deliberately not a generic object dump. Keep population/target/scope context
// beside paper-style endpoint metrics; omit fold traces, model arrays and IDs.
const labels: Record<string, string> = {
  n_samples: "Samples (n)", n_observations: "Observations (n)", n_features: "Variables (p)",
  n_components: "Components (A)", n_selected: "Selected variables",
  requested_n_components: "Requested latent variables", effective_n_components: "Effective latent variables",
  x_explained_variance: "Explained X variance by latent component", y_explained_variance: "Explained Y variance by latent component",
  n_train: "Training samples", n_test: "Test samples", n_folds: "CV folds",
  target_name: "Target", target: "Target", units: "Units", target_units: "Target units",
  "target preview": "Target preview",
  class_name: "Class", class_label: "Class", support: "Class support",
  metric_scope: "Metric scope", evidence_scope: "Evidence scope", population_scope: "Population",
  evaluation_scope: "Evaluation scope", task_type: "Task", method: "Method",
  r2: "R²", r2_train: "Calibration R²", r2_test: "Test R²", r2_cv: "CV R²", q2: "Q²",
  rmse: "RMSE", rmsec: "RMSEC", rmsecv: "RMSECV", rmsep: "RMSEP",
  rmse_train: "Calibration RMSE", rmse_test: "Test RMSE", rmse_cv: "CV RMSE",
  mae: "MAE", bias: "Bias", sep: "SEP", rpd: "RPD", rer: "RER",
  slope: "Prediction slope", intercept: "Prediction intercept",
  explained_variance_ratio: "Explained variance ratio by component",
  cumulative_explained_variance: "Cumulative explained variance",
  cumulative_explained_variance_ratio: "Cumulative explained variance ratio",
  accuracy: "Accuracy", balanced_accuracy: "Balanced accuracy", f1_macro: "Macro F1",
  macro_f1: "Macro F1", sensitivity: "Sensitivity", specificity: "Specificity",
  precision: "Precision", recall: "Recall", f1: "F1", roc_auc: "ROC AUC",
  lof_percent: "Lack of fit (%)", lack_of_fit: "Lack of fit", converged: "Converged",
  n_iter: "Iterations", n_iterations: "Iterations", r_squared: "R²",
  silhouette_score: "Silhouette score", n_clusters: "Clusters",
  cumulative_variance: "Cumulative variance", explained_variance: "Explained variance",
  reconstruction_error: "Reconstruction error", n_iterations_run: "Iterations",
  precision_macro: "Macro precision", recall_macro: "Macro recall",
  sensitivity_macro: "Macro sensitivity", specificity_macro: "Macro specificity",
  n_classes: "Classes", n_outliers: "Outliers", mean_n_selected: "Mean selected variables",
  best_rmsecv: "Selected-model RMSECV (tuning)", global_rmsecv: "Full-spectrum RMSECV",
  best_match: "Best library match", top_hqi: "Top HQI (similarity, not identification certainty)",
};
for (const [scope, title] of [["train", "Training"], ["cv", "CV"], ["test", "Test"]]) {
  for (const metric of ["accuracy", "balanced_accuracy", "f1_macro", "precision_macro", "recall_macro", "sensitivity_macro", "specificity_macro"]) {
    labels[`${scope}_${metric}`] = `${title} ${labels[metric]}`;
  }
}
const modelTypes = /^(?:model|regression|classification|decomposition|clustering|selection)\./;
const metricNames = new Set(Object.keys(labels).filter((key) => ![
  "method", "task_type", "units", "target", "target_name", "target_units", "class_name", "class_label",
  "metric_scope", "evidence_scope", "population_scope", "evaluation_scope",
].includes(key)));

function shortValue(value: string): string {
  const qualified = value.match(/^([^ ]+) (\(.+\) · Protocol: .+)$/);
  if (qualified) return `${shortValue(qualified[1])} ${qualified[2]}`;
  const number = Number(value);
  return value.trim() && Number.isFinite(number) && !Number.isInteger(number)
    ? String(Number(number.toPrecision(4))) : value;
}

function variancePercent(fraction: number): string {
  const rounded = shortValue(String(fraction * 100));
  return fraction < 1 && Number(rounded) >= 100 ? "<100%" : `${rounded}%`;
}

export function keyResultRows(value: unknown, descriptors?: Record<string, ScientificValueDescriptor>): Row[] {
  return (reportGroups({ result: value })[0]?.[1] ?? []).flatMap(([path, value]) => {
    const parts = path.split(" / ");
    // Lineage, source annotations and authority records belong to detailed
    // evidence, not paper-style endpoints (even when their leaves say "units").
    if (parts.some(part => /^(?:scientific_projection|provenance|processing_history|target_context|selected_authority|target_authority|dataset_package|annotation_table|parameters|recipe|model|fitted_state|diagnostic_state|evaluations|quality|component_curve)(?:\[\d+\])?$/i.test(part))) return [];
    // Retain per-target/class context, but not repetitive per-fold or row-level results.
    if (parts.some((part) => /^(?:per_fold|folds|residuals|predictions|(?:x_|y_)?scores|(?:x_|y_)?loadings|variable_correlations|coefficients|comparison|calibration_comparison|target\[|data(?:\[|$))/i.test(part))) return [];
    const last = parts[parts.length - 1];
    const leaf = scientificMetricKey(last).toLowerCase();
    if (leaf === "target preview") return [];
    const descriptor = descriptors?.[parts[0]];
    const dimensions = descriptor?.shape_valid ? descriptor.dimensions : undefined;
    const dimension = leaf === "n_samples" ? dimensions?.[0] : leaf === "n_features" ? dimensions?.[dimensions.length - 1] : null;
    const roleLabels: Record<string, string> = {
      sample: "Samples (n)", observation: "Observations (n)", feature: "Variables (p)",
      spectral_variable: "Variables (p)", component: "Components (A)",
      target: "Responses", actual_class: "Reference classes", predicted_class: "Predicted classes",
    };
    const label = dimension && Number(value) === dimension.size
      ? roleLabels[dimension.role] ?? `${dimension.role.replace(/_/g, " ")} count`
      : labels[leaf];
    if (!label) return [];
    const index = last.match(/\[\d+\]/g)?.join("") ?? "";
    const contexts = parts.slice(0, -1).filter(part => !["default", "metrics", "classification_metrics", "metadata", "extra", "quality_summary"].includes(part));
    // Canonical split metrics and their flattened aliases describe the same
    // population. Normalize names, never merge different populations/values.
    const splitIndex = contexts.lastIndexOf("splits");
    const split = contexts[splitIndex + 1];
    const splitLabel = splitIndex >= 0 && splitIndex === contexts.length - 2 ? labels[`${split}_${leaf}`] : undefined;
    if (splitLabel) contexts.splice(splitIndex, 2);
    const context = contexts.join(" / ");
    return [[`${context ? `${context} / ` : ""}${splitLabel ?? label}${index}`, metricNames.has(leaf) && leaf !== "best_match" ? shortValue(value) : value] as Row];
  });
}

function classificationTables(value: unknown, title: string, depth = 0): SummaryGroup[] {
  if (!value || typeof value !== "object" || Array.isArray(value) || depth > 3) return [];
  const record = value as Record<string, unknown>;
  if (record.schema_version !== "spectrasherpa.classification-evaluation/1") {
    return Object.entries(record).flatMap(([key, item]) => classificationTables(item, `${title} / ${key}`, depth + 1));
  }
  const names = record.labels;
  const matrix = record.confusion_matrix;
  if (!Array.isArray(names) || names.length === 0 || names.length > 100
    || !names.every(name => typeof name === "string") || !Array.isArray(matrix)
    || matrix.length !== names.length || !matrix.every(row => Array.isArray(row) && row.length === names.length
      && row.every(count => typeof count === "number" && Number.isInteger(count) && count >= 0))) return [];
  const groups: SummaryGroup[] = [{ title: `${title} — confusion matrix`, rows: [],
    table: { headers: ["Reference / predicted", ...names], rows: matrix.map((row, index) => [names[index], ...row.map(String)]) },
    notices: ["Rows are reference classes; columns are predicted classes. Counts describe this evaluation only."] }];
  if (Array.isArray(record.per_class) && record.per_class.every(row => row && typeof row === "object" && typeof row.label === "string")) {
    groups.push({ title: `${title} — per-class performance`, rows: [],
      table: { headers: ["Class", "Support", "Precision", "Recall", "Specificity", "F1"],
        rows: record.per_class.map(row => [row.label, ...["support", "precision", "recall", "specificity", "f1"].map(key =>
          typeof row[key] === "number" && Number.isFinite(row[key]) ? shortValue(String(row[key])) : "—")]) },
      notices: [] });
  }
  return groups;
}

/** Omit scalar copies only when the same retained per-class table is renderable. */
function withoutRenderedClassRows(value: unknown, depth = 0): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value) || depth > 3) return value;
  const record = value as Record<string, unknown>;
  const hasTable = record.schema_version === "spectrasherpa.classification-evaluation/1"
    && classificationTables(record, "").some(group => group.title.endsWith("— per-class performance"));
  return Object.fromEntries(Object.entries(record)
    .filter(([key]) => !(hasTable && key === "per_class"))
    .map(([key, child]) => [key, withoutRenderedClassRows(child, depth + 1)]));
}

function runGroups(run: RunReportEntry): SummaryGroup[] {
  const notices = [run.evidence_notice, ...(run.evidence_gaps ?? []).map((gap) =>
    `${gap.node_id} / ${gap.output}: ${gap.reason} ${gap.recovery}`)].filter((v): v is string => !!v);
  if (run.status !== "completed") notices.unshift(`Run outcome: ${run.status}. Results may be incomplete.`);
  const context: Row[] = [["Run", `#${run.id} — ${run.status}`]];
  if (run.executed_at) context.push(["Executed", formatTimestamp(run.executed_at)]);
  const validation = run.validation_summary?.schema_version === "spectrasherpa-readable-validation/1"
    && run.validation_summary.run_id === run.id ? run.validation_summary : undefined;
  if (run.workflow_identity?.source_name) context.push(["Saved data source", run.workflow_identity.source_name]);
  if (run.workflow_identity?.source_origin) context.push(["Data origin", run.workflow_identity.source_origin === "example" ? "Bundled example" : "Current project data"]);
  // The producer selects and shortens context at the point where its scientific
  // meaning is known. Changing a display label must not change report content.
  for (const row of validation?.summary_rows ?? validation?.rows ?? []) {
    context.push([row.label, row.value]);
  }
  if (!validation) notices.push("Validation population unavailable.");
  if (run.selection_provenance?.state === "unavailable") notices.push(run.selection_provenance.reason || "Saved data selection unavailable.");
  const groups: SummaryGroup[] = [{ title: run.name, rows: context, notices }];
  const regression = validation?.regression_results ?? [];
  const roles: Record<string, string> = {
    calibration: "Calibration / training", cross_validation: "Cross-validation",
    held_out_test: "Held-out test (recorded role)", unqualified_evaluation: "Evaluation (independence unverified)",
  };
  const number = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? shortValue(String(value)) : "—";
  for (const target of [...new Set(regression.map(result => result.target))]) {
    const results = regression.filter(result => result.target === target);
    const errorNames: Record<string, string> = { calibration: "RMSEC", cross_validation: "RMSECV", held_out_test: "RMSEP" };
    const errorLabels = [...new Set(results.map(result => errorNames[result.role] || "RMSE"))];
    const errorHeading = errorLabels.length === 1 ? errorLabels[0] : "Error by population";
    const units = [...new Set(results.map(result => result.units))];
    const sharedUnits = units.length === 1 && results.every(result =>
      result.unit_context?.state === "recorded" && result.unit_context.value === units[0]);
    const suffix = ` (${units[0]})`;
    const displayTarget = sharedUnits && target.endsWith(suffix) ? target.slice(0, -suffix.length) : target;
    context.push([`Response (Y): ${displayTarget}`, sharedUnits
      ? `${units[0]}; reference and predictions share this unit.`
      : "Units differ or are not recorded; see the population-specific unit column."]);
    groups.push({
      title: `${run.name} — ${displayTarget}`,
      rows: [],
      table: {
        headers: ["Population / source", ...(!sharedUnits ? ["Units"] : []), "n", "Reference range", "Reference mean", "Reference SD", "R²", errorHeading, "Bias", "SEP", "Slope", "Intercept"],
        rows: results.map(result => [
          `${roles[result.role] ?? "Unqualified population"} · ${result.node_id} / ${result.source_port}`,
          ...(!sharedUnits ? [result.units] : []), number(result.metrics.n_samples),
          `${number(result.reference_min)}–${number(result.reference_max)}`, number(result.reference_mean), number(result.reference_sd),
          number(result.metrics.r2),
          `${scientificErrorMetricLabel("rmse", { target_units: result.units }, errorNames[result.role] || "RMSE")}: ${number(result.metrics.rmse)}`,
          ...["bias", "sep", "slope", "intercept"].map(key => ["bias", "sep"].includes(key)
            ? `${scientificErrorMetricLabel(key, { target_units: result.units })}: ${number(result.metrics[key])}`
            : number(result.metrics[key])),
        ]),
      },
      notices: [
        "A dash (—) denotes an unavailable or undefined value, not zero. Reference mean and sample SD describe the full retained population, not a preview. RMSE uses n observations; calibration RMSE is RMSEC, not degrees-of-freedom-adjusted SEC. SEP is bias-corrected residual SD (n−1).",
        "Bias = predicted − reference; slope/intercept fit predicted against reference. Units apply to range, SD, RMSE, bias, SEP and intercept; R² and slope are dimensionless.",
        "SEC and its effective degrees of freedom, reference-method precision/replicate weighting, bias significance, 95% agreement coverage and outlier/extrapolation qualification are not established by this table. It is not an ASTM E1655 compliance assessment.",
      ],
    });
    for (const result of results) {
      if (!result.observations?.length) continue;
      groups.push({
        title: `${roles[result.role]} — complete target list (${result.node_id} / ${result.source_port})`,
        rows: [],
        table: { headers: ["Sample / population row", "Reference", "Predicted"],
          rows: result.observations.map(row => [row.sample, String(row.reference), String(row.predicted)]) },
        notices: [`${result.observations.length} of ${result.metrics.n_samples} observations; target ${displayTarget}${sharedUnits ? "" : `; units ${result.units}`}. Labels are retained comparison labels, not necessarily original file row IDs.`],
      });
    }
  }
  const nodes = run.saved_definition?.nodes ?? [];
  let recordedCv = (validation?.rows ?? []).some((row) => /^(?:Component CV design|Cross-validation design|Cross-validation method) \(/.test(row.label));
  for (const node of nodes) {
    const settings = run.params_snapshot?.[node.node_id] ?? {};
    const diagnostics = run.diagnostics?.[node.node_id] ?? {};
    if (node.node_type === "preprocess.osc") {
      notices.push("OSC uses reference values. Its correction must be fitted within each training fold before assessing held-out predictions; full-dataset OSC before validation leaks reference information.");
    }
    if (["model.fitted_pls", "classification.plsda", "classification.knn"].includes(node.node_type) && typeof settings.scale === "boolean") {
      context.push([`Scaling (${node.label || node.node_id})`, settings.scale
        ? "Autoscaled (mean-centred, divided by variable standard deviation)"
        : "Mean-centred; no variable scaling"]);
    }
    if (node.node_type === "model.pca" && typeof settings.standardized === "boolean" && typeof settings.scaled === "boolean") {
      context.push([`Scaling (${node.label || node.node_id})`, settings.standardized
        ? "Autoscaled in PCA"
        : settings.scaled ? "Min–max scaled in PCA" : "Mean-centred in PCA"]);
    }
    if (typeof diagnostics.effective_n_components === "number") {
      context.push([`PLS latent components (${node.label || node.node_id})`,
        `${diagnostics.effective_n_components} fitted; requested ${diagnostics.requested_n_components ?? settings.n_components ?? "not recorded"} (not CV folds).`]);
      context.push(["Explained variance", "Incremental fraction by component k, not fold k; X = predictors, Y = responses."]);
      for (const axis of ["x", "y"]) {
        const fractions = diagnostics[`${axis}_explained_variance`];
        if (Array.isArray(fractions) && fractions.length === diagnostics.effective_n_components
          && fractions.every(value => typeof value === "number" && Number.isFinite(value))) {
          context.push([`Cumulative explained ${axis.toUpperCase()} variance (${node.label || node.node_id})`,
            `${variancePercent(fractions.reduce((total, value) => total + value, 0))} across ${fractions.length} fitted components`]);
        }
      }
    }
    const folds = settings.cv_folds ?? settings.n_splits;
    if (folds !== undefined) {
      recordedCv = true;
      context.push([`CV configuration (${node.label || node.node_id})`,
        `${folds} folds requested; method ${settings.cv_method ?? settings.method ?? "not recorded"}; seed ${settings.random_seed ?? "not recorded"}.`]);
    }
  }
  if (!recordedCv && nodes.some(node => modelTypes.test(node.node_type))) {
    context.push(["CV configuration", "No executed CV design retained"]);
  }
  const preprocessing = nodes.filter(node => /^(?:preprocess|baseline|normalize|smooth|transfer)\./.test(node.node_type));
  if (preprocessing.length) context.push(["Preprocessing (saved operations)", preprocessing.map(node => {
    const settings = reportRows(run.params_snapshot?.[node.node_id]).filter(([key]) =>
      ["method", "scale_method", "std_ddof", "window_length", "polyorder", "deriv", "derivative", "order"].includes(key));
    return `${node.label || node.node_type}${settings.length ? ` (${settings.map(([key, value]) => `${key}=${value}`).join(", ")})` : ""}`;
  }).join("; ")]);
  if (!run.saved_definition) groups[0].notices.push("Saved method definition unavailable; current editor settings were not substituted.");
  const nodeIds = new Set([...Object.keys(run.results_summary ?? {}), ...Object.keys(run.diagnostics ?? {}), ...nodes.filter(n => modelTypes.test(n.node_type)).map(n => n.node_id)]);
  for (const id of nodeIds) {
    if (id.startsWith("_")) continue;
    const node = nodes.find(n => n.node_id === id);
    const payloads = [run.results_summary?.[id], run.diagnostics?.[id]];
    // A declared PCA scree port aliases its producer's retained variance-ratio
    // diagnostic. Keep one copy, only when the exact vectors agree.
    const record = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
    const retained = record(run.diagnostics?._scientific_presentations?.[id]);
    const presentations = record(retained.contract).presentations;
    if (Array.isArray(presentations)) for (const presentation of presentations) {
      const declaration = record(presentation);
      if (declaration.kind !== "pca_explained_variance" || !Array.isArray(declaration.source_ports) || declaration.source_ports.length !== 1) continue;
      const port = String(declaration.source_ports[0]);
      const result = record(payloads[0]);
      const diagnostic = record(payloads[1]);
      if (Array.isArray(result[port]) && Array.isArray(diagnostic.explained_variance_ratio)
        && JSON.stringify(result[port]) === JSON.stringify(diagnostic.explained_variance_ratio)) {
        payloads[0] = Object.fromEntries(Object.entries(result).filter(([key]) => key !== port));
      }
    }
    groups.push(...classificationTables(run.results_summary?.[id], `${run.name} — ${node?.label || id}`));
    const hasRegressionTable = regression.some(result => result.node_id === id);
    let descriptors = run.diagnostics?._scientific_values?.[id] as Record<string, ScientificValueDescriptor> | undefined;
    if (node?.node_type === "stats.summary") {
      const inputs = (run.saved_definition?.edges ?? []).filter(edge => edge.to_node_id === id);
      if (inputs.length === 1) {
        const edge = inputs[0];
        const values = run.diagnostics?._scientific_values as Record<string, Record<string, ScientificValueDescriptor>> | undefined;
        const input = values?.[edge.from_node_id]?.[edge.from_output || "default"];
        if (input?.shape_valid) descriptors = { ...descriptors, default: input };
        // Statistics on a model result are an explicit derived projection,
        // not another fit. Its count/variance aliases belong to that model.
        if (input && ["score_matrix", "loading_matrix"].includes(input.scientific_kind)
          && nodes.some(source => source.node_id === edge.from_node_id && modelTypes.test(source.node_type))
          && run.results_summary?.[edge.from_node_id]) continue;
      }
    }
    const rows = payloads.flatMap((payload, index) => keyResultRows(index === 0 ? withoutRenderedClassRows(payload) : payload, descriptors)).filter(([label]) => !(node?.node_type.startsWith("data.") && /components|latent variables/i.test(label))).filter(([label]) => !hasRegressionTable ||
      /latent variables|Variables \(p\)|Explained [XY] variance/.test(label));
    if (!rows.length && !node?.node_type.match(modelTypes)) continue;
    if (node) rows.unshift(["Analysis", node.node_type]);
    // Only retained settings, never defaults/current graph, supply method context.
    for (const [key, value] of reportRows(run.params_snapshot?.[id])) {
      if (key === "n_components" && !node?.node_type.match(modelTypes)) continue;
      if (key === "n_components") {
        if (!rows.some(([label, actual]) => label === "Components (A)" && actual === value)) rows.unshift(["Requested components", value]);
      } else if (["n_clusters", "method", "cv_folds", "n_splits"].includes(key)) rows.unshift([labels[key] ?? key, value]);
    }
    const unique = rows.filter((row, i) => rows.findIndex(other => other[0] === row[0] && other[1] === row[1]) === i);
    const warnings: string[] = [];
    for (const payload of payloads) {
      for (const [path, value] of reportRows(payload)) {
        if (path.split(" / ").some(part => /^(?:warnings?|limitations?|interpretation)(?:\[\d+\])?$/i.test(part))) {
          if (!warnings.includes(value)) warnings.push(value);
        }
      }
    }
    if (run.node_statuses?.[id] && run.node_statuses[id] !== "completed") warnings.push(`Node outcome: ${run.node_statuses[id]}`);
    groups.push({ title: `${run.name} — ${node?.label || id}`, rows: unique, notices: warnings });
  }
  if (groups.length === 1) groups[0].notices.push("No supported key results retained. Select Detailed report to inspect other outputs.");
  return groups;
}

export function scientificSummaryGroups(data: ReportData): SummaryGroup[] {
  if (data.runs?.length) return data.runs.flatMap(runGroups);
  return reportGroups(data.terminalMetrics).flatMap(([id]) => {
    const rows = keyResultRows(data.terminalMetrics[id]);
    return rows.some(([label]) => [...metricNames].some(key => label.includes(labels[key])))
      ? [{ title: data.nodes.find(n => n.nodeId === id)?.label || id, rows,
        notices: ["Live results; validation population is not verified by this summary."] }] : [];
  });
}

const introduction = "Metrics: 4 significant figures; counts exact. Calibration and cross-validation do not establish independent test performance.";
const methodologyUrl = resolveMethodHelpUrl("shortSummary")!;
const empty = "No key results available. Select a saved execution run and generate the report; a workflow definition alone is not a result.";
const escapeHtml = (value: string) => value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export function scientificSummaryHtml(data: ReportData): string {
  const groups = scientificSummaryGroups(data);
  return `<h2>Short summary <a class="method-help" href="${methodologyUrl}" target="_blank" rel="noopener noreferrer" title="Summary methodology" aria-label="Summary methodology (opens documentation)">?</a></h2><p>${introduction}</p>` + (groups.length ? groups.map(group =>
    `<h3>${escapeHtml(group.title)}</h3><div style="overflow-x:auto"><table class="params-table"><tr>${(group.table?.headers ?? ["Result / context", "Value"]).map(label => `<th>${escapeHtml(label)}</th>`).join("")}</tr>${(group.table?.rows ?? group.rows).map(row => `<tr>${row.map(value => `<td>${escapeHtml(value)}</td>`).join("")}</tr>`).join("")}</table></div>${group.notices.map(notice => `<p>${escapeHtml(notice)}</p>`).join("")}`,
  ).join("") : `<p>${empty}</p>`);
}

export function scientificSummaryMarkdown(data: ReportData): string {
  const groups = scientificSummaryGroups(data);
  return `## Short summary\n\n${introduction} [Summary methodology](${methodologyUrl})\n\n` + (groups.length ? groups.map(group =>
    `### ${reportMarkdownText(group.title)}\n\n| ${(group.table?.headers ?? ["Result / context", "Value"]).map(reportMarkdownText).join(" | ")} |\n| ${(group.table?.headers ?? ["Result / context", "Value"]).map(() => "---").join(" | ")} |\n${(group.table?.rows ?? group.rows).map(row => `| ${row.map(reportMarkdownText).join(" | ")} |`).join("\n")}\n\n${group.notices.map(reportMarkdownText).join("\n\n")}\n`,
  ).join("\n") : empty);
}
