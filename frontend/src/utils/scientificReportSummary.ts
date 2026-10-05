import type { ReportData, RunReportEntry } from "./reportGenerator";
import { reportGroups, reportRows, reportMarkdownText } from "./reportValues";

type Row = [string, string];
interface SummaryGroup { title: string; rows: Row[]; notices: string[]; table?: { headers: string[]; rows: string[][] } }

// Deliberately not a generic object dump. Keep population/target/scope context
// beside paper-style endpoint metrics; omit fold traces, model arrays and IDs.
const labels: Record<string, string> = {
  n_samples: "Samples (n)", n_observations: "Observations (n)", n_features: "Variables (p)",
  n_components: "Components / latent variables", n_selected: "Selected variables",
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
  const number = Number(value);
  return value.trim() && Number.isFinite(number) && !Number.isInteger(number)
    ? String(Number(number.toPrecision(4))) : value;
}

export function keyResultRows(value: unknown): Row[] {
  return reportRows(value).flatMap(([path, value]) => {
    const parts = path.split(" / ");
    // Lineage, source annotations and authority records belong to detailed
    // evidence, not paper-style endpoints (even when their leaves say "units").
    if (parts.some(part => /^(?:provenance|processing_history|target_context|selected_authority|target_authority|dataset_package|annotation_table|parameters)(?:\[\d+\])?$/i.test(part))) return [];
    // Retain per-target/class context, but not repetitive per-fold or row-level results.
    if (parts.some((part) => /^(?:per_fold|folds|residuals|predictions|scores|loadings|coefficients|comparison|calibration_comparison|target\[|data(?:\[|$))/i.test(part))) return [];
    const last = parts[parts.length - 1];
    const leaf = last.replace(/\[\d+\]/g, "").toLowerCase();
    const label = labels[leaf];
    if (!label) return [];
    const index = last.match(/\[\d+\]/g)?.join("") ?? "";
    const context = parts.slice(0, -1).join(" / ");
    return [[`${context ? `${context} / ` : ""}${label}${index}`, metricNames.has(leaf) && leaf !== "best_match" ? shortValue(value) : value] as Row];
  });
}

// These are already evidence-qualified, human-readable backend facts. Never
// infer a held-out population from a metric name alone.
const validationContext = /^(?:Dataset|Target|Group field|Split method|Development population|Test population|Groups \(|Evaluation population|Evaluation source|Metric denominator|Cross-validation method|Cross-validation (?:r2|rmse|mae|bias|q2)|Verified metric denominator|Verified CV metric|Validation groups|Repeated validation|Repeated population|Preprocessing within folds|Partition details|Detailed validation evidence)/i;

function runGroups(run: RunReportEntry): SummaryGroup[] {
  const notices = [run.evidence_notice, ...(run.evidence_gaps ?? []).map((gap) =>
    `${gap.node_id} / ${gap.output}: ${gap.reason} ${gap.recovery}`)].filter((v): v is string => !!v);
  if (run.status !== "completed") notices.unshift(`Run outcome: ${run.status}. Results may be incomplete.`);
  const context: Row[] = [["Run", `#${run.id} — ${run.status}`]];
  if (run.executed_at) context.push(["Executed", run.executed_at]);
  const validation = run.validation_summary?.schema_version === "spectrasherpa-readable-validation/1"
    && run.validation_summary.run_id === run.id ? run.validation_summary : undefined;
  if (run.workflow_identity?.source_name) context.push(["Saved data source", run.workflow_identity.source_name]);
  if (run.workflow_identity?.source_origin) context.push(["Data origin", run.workflow_identity.source_origin === "example" ? "Bundled example" : "Current project data"]);
  for (const row of validation?.rows ?? []) {
    if (!validationContext.test(row.label) && !/^(?:Regression statistics|Target list|Spectral axis|Spectral intensity)/.test(row.label)) continue;
    // Population counts belong in a short report; individual row positions do not.
    let value = row.value.replace(/; split-input row positions.*$/, "");
    if (/^Target \(/.test(row.label) && validation?.regression_results?.length) value = value.replace(/; units: [^)]*(?=\))/, "");
    context.push([row.label, /^(?:Verified CV metric|Cross-validation (?:r2|rmse|mae|bias|q2))/i.test(row.label) ? shortValue(value) : value]);
  }
  if (!validation) notices.push("Validation population was not retained in a readable summary; do not infer independent validation from metric names.");
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
    const units = [...new Set(results.map(result => result.units))];
    const sharedUnits = units.length === 1 && !!units[0]?.trim()
      && !/unavailable|not recorded|unknown/i.test(units[0]);
    const suffix = ` (${units[0]})`;
    const displayTarget = sharedUnits && target.endsWith(suffix) ? target.slice(0, -suffix.length) : target;
    context.push([`Response (Y): ${displayTarget}`, sharedUnits
      ? `${units[0]}; reference and predictions share this unit.`
      : "Units differ or are not recorded; see the population-specific unit column."]);
    groups.push({
      title: `${run.name} — ${displayTarget}`,
      rows: [],
      table: {
        headers: ["Population / source", ...(!sharedUnits ? ["Units"] : []), "n", "Reference range", "Reference mean", "Reference SD", "R²", "RMSE", "Bias", "SEP", "Slope", "Intercept"],
        rows: results.map(result => [
          `${roles[result.role] ?? "Unqualified population"} · ${result.node_id} / ${result.source_port}`,
          ...(!sharedUnits ? [result.units] : []), number(result.metrics.n_samples),
          `${number(result.reference_min)}–${number(result.reference_max)}`, number(result.reference_mean), number(result.reference_sd),
          ...["r2", "rmse", "bias", "sep", "slope", "intercept"].map(key => number(result.metrics[key])),
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
  let recordedCv = false;
  for (const node of nodes) {
    const settings = run.params_snapshot?.[node.node_id] ?? {};
    const diagnostics = run.diagnostics?.[node.node_id] ?? {};
    if (typeof diagnostics.effective_n_components === "number") {
      context.push([`PLS latent components (${node.label || node.node_id})`,
        `${diagnostics.effective_n_components} fitted; requested ${diagnostics.requested_n_components ?? settings.n_components ?? "not recorded"}. Components model X–Y covariance; they are not CV folds. The fit uses the requested count subject to numerical rank/covariance limits; this count alone is not evidence of CV-based selection.`]);
      context.push(["Explained-variance interpretation", "Entry [k] is the incremental fraction explained by latent component k, not fold k (0.8745 = 87.45%). X refers to predictors; Y refers to responses, with the fitted centering/scaling."]);
      for (const axis of ["x", "y"]) {
        const fractions = diagnostics[`${axis}_explained_variance`];
        if (Array.isArray(fractions) && fractions.length === diagnostics.effective_n_components
          && fractions.every(value => typeof value === "number" && Number.isFinite(value))) {
          context.push([`Cumulative explained ${axis.toUpperCase()} variance (${node.label || node.node_id})`,
            `${shortValue(String(100 * fractions.reduce((total, value) => total + value, 0)))}% across ${fractions.length} fitted components`]);
        }
      }
    }
    const folds = settings.cv_folds ?? settings.n_splits;
    if (folds !== undefined) {
      recordedCv = true;
      context.push([`CV configuration (${node.label || node.node_id})`,
        `${folds} folds requested in saved settings; method ${settings.cv_method ?? settings.method ?? "not recorded"}; seed ${settings.random_seed ?? "not recorded"}. Each fold holds out a subset while fitting on the remaining subsets; see retained validation evidence for actual partitions. These are not latent components.`]);
    }
  }
  if (!recordedCv) context.push(["CV configuration", "No fold count recorded in saved node settings; component variance entries do not establish cross-validation."]);
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
    const hasRegressionTable = regression.some(result => result.node_id === id);
    const rows = payloads.flatMap(keyResultRows).filter(([label]) => !hasRegressionTable ||
      /latent variables|Variables \(p\)|Explained [XY] variance/.test(label));
    if (!rows.length && !node?.node_type.match(modelTypes)) continue;
    if (node) rows.unshift(["Analysis", node.node_type]);
    // Only retained settings, never defaults/current graph, supply method context.
    for (const [key, value] of reportRows(run.params_snapshot?.[id])) {
      if (["n_components", "n_clusters", "method", "cv_folds", "n_splits"].includes(key)) rows.unshift([labels[key] ?? key, value]);
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

const introduction = "Key results from retained evidence, without AI. Calibration fit and cross-validation are not external validation. No cross-run ranking is inferred. Numeric metrics use four significant figures (counts remain exact); see Detailed report / JSON for full precision and evidence.";
const empty = "No key results available. Select a saved execution run and generate the report; a workflow definition alone is not a result.";
const escapeHtml = (value: string) => value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export function scientificSummaryHtml(data: ReportData): string {
  const groups = scientificSummaryGroups(data);
  return `<h2>Short summary</h2><p>${introduction}</p>` + (groups.length ? groups.map(group =>
    `<h3>${escapeHtml(group.title)}</h3><div style="overflow-x:auto"><table class="params-table"><tr>${(group.table?.headers ?? ["Result / context", "Value"]).map(label => `<th>${escapeHtml(label)}</th>`).join("")}</tr>${(group.table?.rows ?? group.rows).map(row => `<tr>${row.map(value => `<td>${escapeHtml(value)}</td>`).join("")}</tr>`).join("")}</table></div>${group.notices.map(notice => `<p>${escapeHtml(notice)}</p>`).join("")}`,
  ).join("") : `<p>${empty}</p>`);
}

export function scientificSummaryMarkdown(data: ReportData): string {
  const groups = scientificSummaryGroups(data);
  return `## Short summary\n\n${introduction}\n\n` + (groups.length ? groups.map(group =>
    `### ${reportMarkdownText(group.title)}\n\n| ${(group.table?.headers ?? ["Result / context", "Value"]).map(reportMarkdownText).join(" | ")} |\n| ${(group.table?.headers ?? ["Result / context", "Value"]).map(() => "---").join(" | ")} |\n${(group.table?.rows ?? group.rows).map(row => `| ${row.map(reportMarkdownText).join(" | ")} |`).join("\n")}\n\n${group.notices.map(reportMarkdownText).join("\n\n")}\n`,
  ).join("\n") : empty);
}
