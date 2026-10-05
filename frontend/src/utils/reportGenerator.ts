import { reportNodePlotsHtml, type ReportNodePlotSection } from "./reportNodePlots";
import type { ValidationFigure } from "@/utils/validationReportPlots";
import type { ReportProjectEvidenceSnapshot } from "@/stores/report";
import { reportRows, reportGroups, formatReportValue } from "./reportValues";
import { scientificSummaryHtml } from "./scientificReportSummary";
/* eslint-disable @typescript-eslint/no-explicit-any -- report generation walks mixed workflow metadata/metric payloads for presentation only. */
/**
 * Provenance report generator — produces self-contained HTML from workflow
 * execution data. All plots are embedded as base64 PNG (no external deps).
 *
 * Extended for the Report page with optional sections: execution results,
 * diagnostics, run comparison, and AI-generated narrative.
 */

export interface ReportNode {
  nodeId: string;
  nodeType: string;
  label: string;
  parameters: Record<string, any>;
  positionX: number;
  positionY: number;
  status?: string;
  outputShape?: number[] | null;
  outputType?: string | null;
}

export interface ReportEdge {
  fromNodeId: string;
  toNodeId: string;
  fromOutput: string;
  toInput: string;
}

export interface ReportRegressionResult {
  node_id: string;
  source_port: string;
  target: string;
  units: string;
  role: string;
  reference_min: number;
  reference_max: number;
  reference_sd: number | null;
  reference_mean?: number;
  observations?: { sample: string; reference: number; predicted: number }[];
  metrics: Record<string, number | string | null>;
  bias_definition: string;
}

export interface RunReportEntry {
  node_plots?: ReportNodePlotSection[];
  validation_summary?: { schema_version: string; run_id: number; rows: { label: string; value: string }[]; figures?: ValidationFigure[]; regression_results?: ReportRegressionResult[] };
  id: number;
  name: string;
  status: string;
  executed_at: string | null;
  results_summary: Record<string, Record<string, unknown>>;
  diagnostics: Record<string, Record<string, unknown>> | null;
  params_snapshot: Record<string, Record<string, unknown>>;
  node_statuses: Record<string, string> | null;
  integrity_hash: string | null;
  labels: string[] | null;
  evidence_notice?: string;
  workflow_identity?: {
    project_id: number | null;
    workflow_id: number;
    template_name: string | null;
    template_version: string | null;
    source_name: string | null;
    source_origin: "current" | "example" | null;
  };
  evidence_gaps?: Array<{
    node_id: string;
    output: string;
    role?: string | null;
    state: "reduced" | "missing" | "unverified";
    category: "reduced" | "session_only" | "storage_limit" | "unavailable" | "unverified";
    reason: string;
    recovery: string;
  }>;
  selection_provenance?: {
    state: "exact" | "unavailable";
    reason: string | null;
    executor_user_id: number;
    workflow_version_id: number | null;
    revisions: Array<{
      revision_number: number;
      source_node_id: string;
      created_by: number;
      created_at: string;
      reason: string | null;
      selection: {
        dataset_name: string;
        selected_file_ids: number[] | null;
        target_authority: { column: string; target_type: string; units: string | null } | null;
        group_column: string | null;
        scientific_collection_sha256: string;
      };
    }>;
    scientific_receipts: Array<{
      node_id: string;
      scientific_digest: string;
      shape: number[];
      selection_lineage?: Array<{
        node_id: string | null;
        operation: "data.filter_samples";
        parameters: Record<string, unknown>;
        selected_index_ranges: number[][];
        selected_indices_sha256: string;
        input_shape: number[] | null;
        output_shape: number[] | null;
      }>;
    }>;
  };
  saved_definition?: { nodes: { node_id: string; label?: string; node_type: string }[] } | null;
}

export interface ReportComparison {
  metric_keys: string[];
  diff: Record<string, Record<string, unknown>>;
  rankable_metrics?: string[];
  result_pairs?: { state: string; reason: string }[];
}

export interface ReportSections {
  pipelineDetails: boolean;
  connections: boolean;
  executionResults: boolean;
  diagnostics: boolean;
  runComparison: boolean;
  aiNarrative: boolean;
}

export interface ReportData {
  reportMode?: "summary" | "detailed";
  workflowName: string;
  workflowDescription: string | null;
  integrityHash: string | null;
  generatedAt: string;
  nodes: ReportNode[];
  edges: ReportEdge[];
  plotImages: Map<string, string>; // nodeId -> base64 PNG data URL
  terminalMetrics: Record<string, any>;

  // Optional fields for Report page (backward-compatible)
  technique?: string | null;
  sampleType?: string | null;
  runs?: RunReportEntry[];
  comparison?: ReportComparison | null;
  narrativeMarkdown?: string | null;
  sections?: ReportSections;
  workflowIdentity?: {
    project_id: number | null;
    workflow_id: number;
    template_name: string | null;
    template_version: string | null;
    source_name: string | null;
    source_origin: "current" | "example" | null;
  };
  projectEvidence?: ReportProjectEvidenceSnapshot | null;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function projectEvidenceHtml(snapshot: ReportProjectEvidenceSnapshot | null | undefined): string {
  if (!snapshot) return "";
  const note = "Project evidence captured at report generation. These are current project records, not proof that every record belongs to the selected report runs.";
  let html = `<h2>Project evidence</h2><p>${escapeHtml(note)}</p>`;
  html += `<p>Captured ${escapeHtml(snapshot.capturedAt)} · Project ${escapeHtml(String(snapshot.projectId ?? "unavailable"))}</p>`;
  if (snapshot.state !== "available") return html + `<p>${escapeHtml(snapshot.reason ?? "Evidence unavailable.")}</p>`;
  html += `<table class="connection-table"><tr><th>Record</th><th>State</th><th>Active name</th><th>Digest</th></tr>`;
  for (const record of snapshot.records) {
    html += `<tr><td>${escapeHtml(record.label)}</td><td>${escapeHtml(record.state)}</td>`;
    html += `<td>${escapeHtml(record.name ?? "Not recorded")}</td><td class="hash">${escapeHtml(record.digest ?? "—")}</td></tr>`;
  }
  return html + "</table>";
}

function buildStyleSheet(): string {
  return `
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #ffffff; color: #334155; line-height: 1.6;
      max-width: 1000px; margin: 0 auto; padding: 40px 24px;
    }
    h1 { font-size: 1.8rem; color: #172033; margin-bottom: 8px; }
    h2 { font-size: 1.3rem; color: #172033; margin: 32px 0 16px; border-bottom: 1px solid #cbd5e1; padding-bottom: 8px; }
    h3 { font-size: 1.15rem; font-weight: 700; color: #172033; margin: 28px 0 14px; padding: 10px 14px; background: #f8fafc; border-left: 4px solid #2563eb; }
    h3 small { display: block; font-size: 0.8rem; font-weight: 400; margin-top: 4px; }
    .report-figure { margin: 16px 0 24px; padding: 14px; border: 1px solid #64748b; border-radius: 6px; break-inside: avoid; }
    .report-figure h4 { font-size: 1rem; margin: 0 0 12px; }
    .report-figure img, .report-figure svg { width: 100%; height: auto; display: block; background: white; }
    .report-figure figcaption { margin-top: 10px; font-size: 0.8rem; line-height: 1.5; }
    .meta-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin: 16px 0; }
    .meta-item { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 12px; }
    .meta-label { font-size: 0.75rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }
    .meta-value { font-size: 0.95rem; color: #172033; margin-top: 4px; }
    .hash { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 0.8rem; color: #15803d; word-break: break-all; }
    .node-card { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 16px; margin: 12px 0; }
    .node-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
    .node-type-badge { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
    .badge-data { background: rgba(59,130,246,0.2); color: #2563eb; }
    .badge-preprocess { background: rgba(168,85,247,0.2); color: #7e22ce; }
    .badge-model { background: rgba(34,197,94,0.2); color: #15803d; }
    .badge-output { background: rgba(251,146,60,0.2); color: #c2410c; }
    .badge-other { background: rgba(148,163,184,0.2); color: #475569; }
    .params-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
    .params-table th, .params-table td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #f8fafc; font-size: 0.85rem; }
    .params-table th { color: #64748b; font-weight: 500; }
    .params-table td { color: #334155; }
    .params-table code { background: #ffffff; padding: 1px 4px; border-radius: 3px; font-size: 0.8rem; }
    .connection-table { width: 100%; border-collapse: collapse; }
    .connection-table th, .connection-table td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #cbd5e1; font-size: 0.85rem; }
    .connection-table th { background: #f8fafc; color: #64748b; }
    .connection-table td { color: #334155; }
    .plot-gallery { display: grid; grid-template-columns: 1fr; gap: 16px; margin: 16px 0; }
    .plot-card { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; overflow: hidden; }
    .plot-card img { width: 100%; display: block; }
    .plot-card .plot-caption { padding: 8px 12px; font-size: 0.85rem; color: #475569; }
    .footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #cbd5e1; font-size: 0.8rem; color: #64748b; text-align: center; }
    .run-card { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 16px; margin: 12px 0; }
    .run-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
    .status-badge { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
    .status-completed { background: rgba(34,197,94,0.2); color: #15803d; }
    .status-error { background: rgba(239,68,68,0.2); color: #b91c1c; }
    .status-partial { background: rgba(251,191,36,0.2); color: #92400e; }
    .status-running { background: rgba(59,130,246,0.2); color: #2563eb; }
    .comparison-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
    .comparison-table th, .comparison-table td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #cbd5e1; font-size: 0.85rem; }
    .comparison-table th { background: #f8fafc; color: #64748b; font-weight: 500; }
    .comparison-table td { color: #334155; }
    .metric-best { color: #15803d; font-weight: 600; }
    .delta-positive { color: #2563eb; font-weight: 500; }
    .delta-negative { color: #b91c1c; font-weight: 500; }
    .narrative-section { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 20px 24px; margin: 16px 0; line-height: 1.8; font-size: 0.9rem; }
    .narrative-section p { margin-bottom: 12px; }
    .label-tag { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 0.7rem; background: rgba(59,130,246,0.2); color: #2563eb; margin-right: 4px; }
    @media print {
      @page { size: A4; margin: 14mm; }
      body {
        background: #fff;
        color: #111827;
        max-width: none;
        padding: 0;
        font-size: 10pt;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }
      h1, h2, h3, .meta-value, .params-table td, .connection-table td, .comparison-table td {
        color: #111827;
      }
      h2 { border-bottom-color: #d1d5db; page-break-after: avoid; break-after: avoid; }
      h3 { background: #eaf1fa; border-left-color: #2563eb; break-after: avoid; }
      .node-card, .meta-item, .plot-card, .run-card, .narrative-section {
        background: #fff;
        border-color: #d1d5db;
        page-break-inside: avoid;
        break-inside: avoid;
      }
      .params-table th, .connection-table th, .comparison-table th {
        background: #f3f4f6;
        color: #374151;
      }
      .params-table th, .params-table td, .connection-table th, .connection-table td,
      .comparison-table th, .comparison-table td {
        border-bottom-color: #e5e7eb;
      }
      .params-table code { background: #f3f4f6; color: #111827; }
      .footer { border-top-color: #d1d5db; color: #6b7280; }
      .hash { color: #16a34a; }
    }
  `;
}

function getBadgeClass(nodeType: string): string {
  const category = nodeType.split(".")[0];
  const map: Record<string, string> = {
    data: "badge-data",
    preprocess: "badge-preprocess",
    normalize: "badge-preprocess",
    baseline: "badge-preprocess",
    smooth: "badge-preprocess",
    derivative: "badge-preprocess",
    model: "badge-model",
    classification: "badge-model",
    analysis: "badge-model",
    output: "badge-output",
    stats: "badge-output",
    synthesis: "badge-data",
  };
  return map[category] || "badge-other";
}

function getStatusClass(status: string): string {
  const map: Record<string, string> = {
    completed: "status-completed",
    error: "status-error",
    partial: "status-partial",
    running: "status-running",
  };
  return map[status] || "status-partial";
}

function formatMetricValue(value: unknown): string {
  return formatReportValue(value);
}

function buildNodeSection(node: ReportNode, plotImage?: string): string {
  const badge = getBadgeClass(node.nodeType);
  const params = reportRows(node.parameters);

  let html = `<div class="node-card">
    <div class="node-header">
      <span class="node-type-badge ${badge}">${escapeHtml(node.nodeType)}</span>
      <strong>${escapeHtml(node.label)}</strong>
      <span style="margin-left:auto;font-size:0.75rem;color:#64748b">ID: ${escapeHtml(node.nodeId)}</span>
    </div>`;

  if (node.outputShape) {
    html += `<div style="font-size:0.8rem;color:#94a3b8;margin-bottom:8px">Output: ${node.outputType || "unknown"} [${node.outputShape.join(" x ")}]</div>`;
  }

  if (params.length > 0) {
    html += `<table class="params-table"><tr><th>Parameter</th><th>Value</th></tr>`;
    for (const [key, value] of params) {
      const displayValue = value;
      html += `<tr><td><code>${escapeHtml(key)}</code></td><td>${escapeHtml(displayValue)}</td></tr>`;
    }
    html += `</table>`;
  }

  if (plotImage) {
    html += `<div style="margin-top:12px"><img src="${plotImage}" alt="Plot for ${escapeHtml(node.label)}" style="width:100%;border-radius:4px" /></div>`;
  }

  html += `</div>`;
  return html;
}

function buildRunSection(run: RunReportEntry, nodes: ReportNode[]): string {
  const statusClass = getStatusClass(run.status);
  const dateStr = run.executed_at ? new Date(run.executed_at).toLocaleString() : "Unknown date";

  let html = `<div class="run-card">
    <div class="run-header">
      <strong>${escapeHtml(run.name)}</strong>
      <span class="status-badge ${statusClass}">${escapeHtml(run.status)}</span>
      <span style="margin-left:auto;font-size:0.8rem;color:#64748b">${escapeHtml(dateStr)}</span>
    </div>`;

  // Labels
  if (run.labels && run.labels.length > 0) {
    html += `<div style="margin-bottom:10px">`;
    for (const label of run.labels) {
      html += `<span class="label-tag">${escapeHtml(label)}</span>`;
    }
    html += `</div>`;
  }

  // Results summary as metrics table
  html += `<p>Saved run ${run.id}</p>`;
  if (run.validation_summary?.schema_version === 'spectrasherpa-readable-validation/1' && run.validation_summary.run_id === run.id) {
    html += '<h4>Validation summary</h4><table class="params-table">';
    for (const row of run.validation_summary.rows) {
      html += `<tr><th>${escapeHtml(row.label)}</th><td>${escapeHtml(row.value)}</td></tr>`;
    }
    html += '</table>';
  }
  html += reportNodePlotsHtml(run);
  if (run.workflow_identity) {
    const identity = run.workflow_identity;
    const origin = identity.source_origin === "example"
      ? "Bundled example"
      : identity.source_origin === "current"
        ? "Current project data"
        : "Not recorded";
    html += `<p>Run source: ${escapeHtml(identity.source_name || "Not recorded")} (${escapeHtml(origin)})</p>`;
  }
  if (run.evidence_notice) html += `<p>${escapeHtml(run.evidence_notice)}</p>`;
  if (run.evidence_gaps?.length) {
    html += `<h4>Incomplete durable evidence</h4><ul>`;
    for (const gap of run.evidence_gaps) {
      const node = nodes.find((item) => item.nodeId === gap.node_id);
      const label = `${node?.label || gap.node_id} · ${gap.role || gap.output}`;
      html += `<li><strong>${escapeHtml(label)}</strong> (${escapeHtml(gap.category.replace(/_/g, " "))}): ${escapeHtml(gap.reason)} ${escapeHtml(gap.recovery)}</li>`;
    }
    html += `</ul>`;
  }
  const provenance = run.selection_provenance;
  html += `<h4>Data selection and lineage</h4>`;
  if (!provenance || provenance.state !== "exact") {
    html += `<p>${escapeHtml(provenance?.reason || "Selection provenance is unavailable for this run.")}</p>`;
  } else {
    html += `<p>Workflow version ${escapeHtml(String(provenance.workflow_version_id ?? "unsaved"))}; executed by user ${escapeHtml(String(provenance.executor_user_id))}.</p>`;
    for (const revision of provenance.revisions) {
      const selection = revision.selection;
      const target = selection.target_authority
        ? `${selection.target_authority.column} (${selection.target_authority.target_type}${selection.target_authority.units ? `, ${selection.target_authority.units}` : ""})`
        : "None";
      const receipt = provenance.scientific_receipts.find(
        (item) => item.node_id === revision.source_node_id,
      );
      const output = receipt ? ` → shape ${receipt.shape.join(" × ")}` : "";
      html += `<div class="node-card"><strong>${escapeHtml(selection.dataset_name)}</strong>`;
      html += `<p>${escapeHtml(selection.dataset_name)} → selection revision ${revision.revision_number}${escapeHtml(output)} → run ${run.id} → report</p>`;
      html += `<table class="params-table">`;
      html += `<tr><th>Source node</th><td>${escapeHtml(revision.source_node_id)}</td></tr>`;
      html += `<tr><th>Selection author</th><td>User ${escapeHtml(String(revision.created_by))} at ${escapeHtml(revision.created_at)}</td></tr>`;
      html += `<tr><th>Files</th><td>${escapeHtml(selection.selected_file_ids?.join(", ") || "All admitted files")}</td></tr>`;
      html += `<tr><th>Target</th><td>${escapeHtml(target)}</td></tr>`;
      html += `<tr><th>Group</th><td>${escapeHtml(selection.group_column || "None")}</td></tr>`;
      html += `<tr><th>Scientific identity</th><td><code>${escapeHtml(selection.scientific_collection_sha256)}</code></td></tr>`;
      html += `<tr><th>Change reason</th><td>${escapeHtml(revision.reason || "No reason supplied")}</td></tr>`;
      html += `</table></div>`;
    }
    const filters = provenance.scientific_receipts.flatMap((receipt) =>
      (receipt.selection_lineage || []).map((lineage) => ({ receipt, lineage })),
    );
    if (filters.length) {
      html += `<h5>Executed sample filters</h5><table class="params-table"><tr><th>Node</th><th>Rule</th><th>Rows</th><th>Exact row receipt</th></tr>`;
      for (const { receipt, lineage } of filters) {
        const ranges = lineage.selected_index_ranges
          .map(([start, end]) => (start === end ? String(start + 1) : `${start + 1}-${end + 1}`))
          .join(", ");
        html += `<tr><td>${escapeHtml(lineage.node_id || receipt.node_id)}</td>`;
        html += `<td><code>${escapeHtml(JSON.stringify(lineage.parameters))}</code></td>`;
        html += `<td>${escapeHtml(ranges || "All input rows")}</td>`;
        html += `<td><code>${escapeHtml(lineage.selected_indices_sha256)}</code></td></tr>`;
      }
      html += `</table>`;
    }
  }
  const allMetrics: [string, string, unknown][] = [];
  for (const [nodeId, metrics] of reportGroups(run.results_summary)) {
    if (typeof metrics === "object" && metrics !== null) {
      for (const [key, value] of metrics) {
        const nodeLabel =
          run.saved_definition?.nodes.find((n) => n.node_id === nodeId)?.label || nodeId;
        allMetrics.push([nodeLabel, key, value]);
      }
    }
  }

  if (allMetrics.length > 0) {
    html += `<table class="params-table"><tr><th>Node</th><th>Metric</th><th>Value</th></tr>`;
    for (const [nodeLabel, key, value] of allMetrics) {
      html += `<tr><td>${escapeHtml(nodeLabel)}</td><td><code>${escapeHtml(key)}</code></td><td>${escapeHtml(formatMetricValue(value))}</td></tr>`;
    }
    html += `</table>`;
  }

  html += `</div>`;
  return html;
}

function buildDiagnosticsSection(run: RunReportEntry, nodes: ReportNode[]): string {
  const groups = reportGroups(run.diagnostics);
  if (!groups.length) return "";

  let html = `<h3>${escapeHtml(run.name)} — Diagnostics</h3>`;
  for (const [nodeId, diag] of groups) {
    const nodeLabel = nodes.find((n) => n.nodeId === nodeId)?.label || nodeId;
    html += `<div class="node-card"><strong>${escapeHtml(nodeLabel)}</strong>`;
    html += `<table class="params-table"><tr><th>Key</th><th>Value</th></tr>`;
    for (const [key, value] of diag) {
      html += `<tr><td><code>${escapeHtml(key)}</code></td><td>${escapeHtml(formatMetricValue(value))}</td></tr>`;
    }
    html += `</table></div>`;
  }
  return html;
}

const HIGHER_IS_BETTER = new Set(["r2", "accuracy", "explained_variance", "silhouette_score"]);

function buildComparisonSection(runs: RunReportEntry[], comparison: ReportComparison): string {
  if (!comparison.metric_keys.some((key) => runs.some((run) => formatMetricValue(comparison.diff[key]?.[String(run.id)])))) return "";

  let html = comparison.rankable_metrics?.length
    ? ""
    : "<p>Evaluation compatibility is not established. Results are not ranked.</p>";
  for (const pair of comparison.result_pairs ?? []) html += `<p>${escapeHtml(pair.reason)}</p>`;
  html += `<table class="comparison-table"><tr><th>Metric</th>`;
  for (const run of runs) {
    html += `<th>${escapeHtml(run.name)}</th>`;
  }
  if (runs.length === 2) html += `<th>Delta</th>`;
  html += `</tr>`;

  for (const key of comparison.metric_keys) {
    if (!runs.some((run) => formatMetricValue(comparison.diff[key]?.[String(run.id)]))) continue;
    const metricName = key.split(".").pop() || key;
    const values = comparison.diff[key] || {};
    const numericVals: { runId: string; val: number }[] = [];
    for (const [runId, val] of Object.entries(values)) {
      if (typeof val === "number" && Number.isFinite(val)) {
        numericVals.push({ runId, val });
      }
    }

    // Find best
    const higherBetter = HIGHER_IS_BETTER.has(metricName);
    const rankable = comparison.rankable_metrics?.includes(key) === true;
    let bestRunId: string | null = null;
    if (rankable && numericVals.length >= 2) {
      const sorted = [...numericVals].sort((a, b) =>
        higherBetter ? b.val - a.val : a.val - b.val,
      );
      bestRunId = sorted[0].runId;
    }

    html += `<tr><td><code>${escapeHtml(key)}</code></td>`;
    for (const run of runs) {
      const val = values[String(run.id)];
      const isBest = bestRunId === String(run.id);
      const cls = isBest ? ' class="metric-best"' : "";
      html += `<td${cls}>${escapeHtml(formatMetricValue(val))}</td>`;
    }

    // Delta for 2-run comparison
    if (rankable && runs.length === 2 && numericVals.length === 2) {
      const delta = Number(values[String(runs[1].id)]) - Number(values[String(runs[0].id)]);
      const sign = delta > 0 ? "+" : "";
      const improvement = higherBetter ? delta : -delta;
      const cls = improvement > 0 ? "delta-positive" : improvement < 0 ? "delta-negative" : "";
      const formatted = Number.isInteger(delta) ? String(delta) : delta.toFixed(4);
      html += `<td class="${cls}">${sign}${formatted}</td>`;
    } else if (runs.length === 2) {
      html += `<td>\u2014</td>`;
    }
    html += `</tr>`;
  }
  html += `</table>`;
  return html;
}

function markdownToSimpleHtml(md: string): string {
  return md
    .split("\n\n")
    .map((block) => {
      const trimmed = block.trim();
      if (!trimmed) return "";
      if (trimmed.startsWith("### ")) return `<h3>${escapeHtml(trimmed.slice(4))}</h3>`;
      if (trimmed.startsWith("## ")) return `<h3>${escapeHtml(trimmed.slice(3))}</h3>`;
      if (trimmed.startsWith("# ")) return `<h3>${escapeHtml(trimmed.slice(2))}</h3>`;
      // Bold/italic inline
      let html = escapeHtml(trimmed);
      html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
      return `<p>${html}</p>`;
    })
    .join("\n");
}

export function generateProvenanceReport(data: ReportData): string {
  const {
    workflowName,
    workflowDescription,
    integrityHash,
    generatedAt,
    nodes,
    edges,
    plotImages,
    terminalMetrics,
    technique,
    sampleType,
    runs,
    workflowIdentity,
    comparison,
    narrativeMarkdown,
    sections,
  } = data;

  // Section visibility (backward-compat: if sections not provided, show all original sections)
  const showPipeline = sections?.pipelineDetails ?? true;
  const showConnections = sections?.connections ?? true;
  const showResults = sections?.executionResults ?? true;
  const showDiagnostics = sections?.diagnostics ?? false;
  const showComparison = sections?.runComparison ?? false;
  const showNarrative = sections?.aiNarrative ?? false;

  // Topological sort for node ordering
  const sorted = topologicalSort(nodes, edges);

  let html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Report: ${escapeHtml(workflowName)}</title>
  <style>${buildStyleSheet()}</style>
</head>
<body>
  <h1>${escapeHtml(workflowName)}</h1>`;

  if (workflowDescription) {
    html += `<p style="color:#94a3b8;margin-bottom:16px">${escapeHtml(workflowDescription)}</p>`;
  }

  if (data.reportMode === "summary") {
    html += scientificSummaryHtml(data);
    html += projectEvidenceHtml(data.projectEvidence);
    html += (data.runs ?? []).map(reportNodePlotsHtml).join("");
    if (showNarrative && narrativeMarkdown) {
      html += `<h2>AI Summary (optional)</h2><div class="narrative-section">${markdownToSimpleHtml(narrativeMarkdown)}</div>`;
    }
    return html + `<div class="footer">Generated by SpectraSherpa — ${escapeHtml(generatedAt)}</div></body></html>`;
  }

  // AI Narrative (placed at top if available — executive summary)
  if (showNarrative && narrativeMarkdown) {
    html += `<h2>AI Summary</h2><div class="narrative-section">${markdownToSimpleHtml(narrativeMarkdown)}</div>`;
  }

  // Metadata grid
  html += `<h2>Metadata</h2><div class="meta-grid">
    <div class="meta-item"><div class="meta-label">Generated</div><div class="meta-value">${escapeHtml(generatedAt)}</div></div>
    <div class="meta-item"><div class="meta-label">Nodes</div><div class="meta-value">${nodes.length}</div></div>
    <div class="meta-item"><div class="meta-label">Connections</div><div class="meta-value">${edges.length}</div></div>`;

  if (workflowIdentity) {
    html += `<div class="meta-item"><div class="meta-label">Workflow sheet</div><div class="meta-value">#${escapeHtml(String(workflowIdentity.workflow_id))}</div></div>`;
    html += `<div class="meta-item"><div class="meta-label">Project</div><div class="meta-value">${escapeHtml(workflowIdentity.project_id == null ? "Not recorded" : `#${workflowIdentity.project_id}`)}</div></div>`;
    html += `<div class="meta-item"><div class="meta-label">Data source</div><div class="meta-value">${escapeHtml(workflowIdentity.source_name || "Not recorded")}</div></div>`;
    html += `<div class="meta-item"><div class="meta-label">Data origin</div><div class="meta-value">${escapeHtml(workflowIdentity.source_origin === "example" ? "Bundled example" : workflowIdentity.source_origin === "current" ? "Current project data" : "Not recorded")}</div></div>`;
  }

  if (technique) {
    html += `<div class="meta-item"><div class="meta-label">Technique</div><div class="meta-value">${escapeHtml(technique)}</div></div>`;
  }
  if (sampleType) {
    html += `<div class="meta-item"><div class="meta-label">Sample Type</div><div class="meta-value">${escapeHtml(sampleType)}</div></div>`;
  }
  if (integrityHash) {
    html += `<div class="meta-item" style="grid-column: 1/-1"><div class="meta-label">Integrity Hash (SHA-256)</div><div class="meta-value hash">${escapeHtml(integrityHash)}</div></div>`;
  }
  html += `</div>`;
  html += projectEvidenceHtml(data.projectEvidence);

  // Connections table
  if (showConnections && edges.length > 0) {
    html += `<h2>Connections</h2><table class="connection-table"><tr><th>From</th><th>To</th><th>Ports</th></tr>`;
    for (const edge of edges) {
      const fromNode = nodes.find((n) => n.nodeId === edge.fromNodeId);
      const toNode = nodes.find((n) => n.nodeId === edge.toNodeId);
      const fromLabel = fromNode?.label || edge.fromNodeId;
      const toLabel = toNode?.label || edge.toNodeId;
      html += `<tr><td>${escapeHtml(fromLabel)}</td><td>${escapeHtml(toLabel)}</td><td>${escapeHtml(edge.fromOutput)} &rarr; ${escapeHtml(edge.toInput)}</td></tr>`;
    }
    html += `</table>`;
  }

  // Node details in topological order
  if (showPipeline) {
    html += `<h2>Pipeline Steps</h2>`;
    if (hasUnresolvedReportConnections(nodes, edges)) {
      html += `<p>Some saved connections have no retained node definition. All available steps are shown; pipeline order is not fully verified.</p>`;
    }
    for (const node of sorted) {
      const plotImage = plotImages.get(node.nodeId);
      html += buildNodeSection(node, plotImage);
    }

    // Plot gallery for remaining images not covered in node sections
    const standalonePlots = Array.from(plotImages.entries()).filter(
      ([nodeId]) => !sorted.find((n) => n.nodeId === nodeId),
    );
    if (standalonePlots.length > 0) {
      html += `<h2>Additional Plots</h2><div class="plot-gallery">`;
      for (const [nodeId, image] of standalonePlots) {
        html += `<div class="plot-card"><img src="${image}" alt="Plot ${escapeHtml(nodeId)}" /><div class="plot-caption">Node: ${escapeHtml(nodeId)}</div></div>`;
      }
      html += `</div>`;
    }
  }

  // Terminal metrics (from live workflow execution — backward compat)
  const terminalGroups = reportGroups(terminalMetrics);
  if (showResults && terminalGroups.length) {
    html += `<h2>Results</h2>`;
    for (const [nodeId, rows] of terminalGroups) {
      const node = nodes.find((n) => n.nodeId === nodeId);
      html += `<h3>${escapeHtml(node?.label || nodeId)}</h3>`;
      html += `<table class="params-table"><tr><th>Metric</th><th>Value</th></tr>`;
      for (const [key, value] of rows) {
        const displayValue = value;
        html += `<tr><td><code>${escapeHtml(key)}</code></td><td>${escapeHtml(displayValue)}</td></tr>`;
      }
      html += `</table>`;
    }
  }

  // Execution run results (from Report page — saved runs)
  if (showResults && runs && runs.length > 0) {
    html += `<h2>Execution Runs</h2>`;
    for (const run of runs) {
      html += buildRunSection(run, nodes);
    }
  }

  // Diagnostics
  if (showDiagnostics && runs && runs.length > 0) {
    const hasDiagnostics = runs.some((r) => reportGroups(r.diagnostics).length > 0);
    if (hasDiagnostics) {
      html += `<h2>Diagnostics</h2>`;
      for (const run of runs) {
        html += buildDiagnosticsSection(run, nodes);
      }
    }
  }

  // Run comparison
  if (showComparison && comparison && runs && runs.length >= 2) {
    const comparisonHtml = buildComparisonSection(runs, comparison);
    if (comparisonHtml) html += `<h2>Run Comparison</h2>${comparisonHtml}`;
  }

  // Footer
  html += `<div class="footer">
    Generated by SpectraSherpa &mdash; ${escapeHtml(generatedAt)}
    ${integrityHash ? `<br/>Integrity Hash: <span class="hash">${escapeHtml(integrityHash)}</span>` : ""}
  </div>
</body>
</html>`;

  return html;
}

/** Topological sort using Kahn's algorithm */
export function hasUnresolvedReportConnections(nodes: ReportNode[], edges: ReportEdge[]): boolean {
  const ids = new Set(nodes.map((node) => node.nodeId));
  return edges.some((edge) => !ids.has(edge.fromNodeId) || !ids.has(edge.toNodeId));
}

export function topologicalSort(nodes: ReportNode[], edges: ReportEdge[]): ReportNode[] {
  const nodeMap = new Map(nodes.map((n) => [n.nodeId, n]));
  const inDegree = new Map<string, number>();
  const adjacency = new Map<string, string[]>();

  for (const node of nodes) {
    inDegree.set(node.nodeId, 0);
    adjacency.set(node.nodeId, []);
  }

  for (const edge of edges) {
    if (!nodeMap.has(edge.fromNodeId) || !nodeMap.has(edge.toNodeId)) continue;
    inDegree.set(edge.toNodeId, (inDegree.get(edge.toNodeId) || 0) + 1);
    adjacency.get(edge.fromNodeId)?.push(edge.toNodeId);
  }

  const queue: string[] = [];
  for (const [nodeId, degree] of inDegree) {
    if (degree === 0) queue.push(nodeId);
  }

  const result: ReportNode[] = [];
  while (queue.length > 0) {
    const nodeId = queue.shift()!;
    const node = nodeMap.get(nodeId);
    if (node) result.push(node);

    for (const dependent of adjacency.get(nodeId) || []) {
      const newDegree = (inDegree.get(dependent) || 1) - 1;
      inDegree.set(dependent, newDegree);
      if (newDegree === 0) queue.push(dependent);
    }
  }

  // Incomplete or cyclic historical definitions must not erase retained steps.
  const visited = new Set(result.map((node) => node.nodeId));
  return [...result, ...nodes.filter((node) => !visited.has(node.nodeId))];
}
