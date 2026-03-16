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

export interface RunReportEntry {
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
}

export interface ReportComparison {
  metric_keys: string[];
  diff: Record<string, Record<string, unknown>>;
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
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function buildStyleSheet(): string {
  return `
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #0f172a; color: #e2e8f0; line-height: 1.6;
      max-width: 1000px; margin: 0 auto; padding: 40px 24px;
    }
    h1 { font-size: 1.8rem; color: #f8fafc; margin-bottom: 8px; }
    h2 { font-size: 1.3rem; color: #f8fafc; margin: 32px 0 16px; border-bottom: 1px solid #334155; padding-bottom: 8px; }
    h3 { font-size: 1.05rem; color: #cbd5e1; margin: 20px 0 10px; }
    .meta-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin: 16px 0; }
    .meta-item { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 12px; }
    .meta-label { font-size: 0.75rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }
    .meta-value { font-size: 0.95rem; color: #f8fafc; margin-top: 4px; }
    .hash { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 0.8rem; color: #4ade80; word-break: break-all; }
    .node-card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 16px; margin: 12px 0; }
    .node-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
    .node-type-badge { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
    .badge-data { background: rgba(59,130,246,0.2); color: #60a5fa; }
    .badge-preprocess { background: rgba(168,85,247,0.2); color: #c084fc; }
    .badge-model { background: rgba(34,197,94,0.2); color: #4ade80; }
    .badge-output { background: rgba(251,146,60,0.2); color: #fb923c; }
    .badge-other { background: rgba(148,163,184,0.2); color: #94a3b8; }
    .params-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
    .params-table th, .params-table td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #1e293b; font-size: 0.85rem; }
    .params-table th { color: #64748b; font-weight: 500; }
    .params-table td { color: #e2e8f0; }
    .params-table code { background: #0f172a; padding: 1px 4px; border-radius: 3px; font-size: 0.8rem; }
    .connection-table { width: 100%; border-collapse: collapse; }
    .connection-table th, .connection-table td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #334155; font-size: 0.85rem; }
    .connection-table th { background: #1e293b; color: #64748b; }
    .connection-table td { color: #e2e8f0; }
    .plot-gallery { display: grid; grid-template-columns: 1fr; gap: 16px; margin: 16px 0; }
    .plot-card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; overflow: hidden; }
    .plot-card img { width: 100%; display: block; }
    .plot-card .plot-caption { padding: 8px 12px; font-size: 0.85rem; color: #94a3b8; }
    .footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #334155; font-size: 0.8rem; color: #64748b; text-align: center; }
    .run-card { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 16px; margin: 12px 0; }
    .run-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
    .status-badge { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
    .status-completed { background: rgba(34,197,94,0.2); color: #4ade80; }
    .status-error { background: rgba(239,68,68,0.2); color: #f87171; }
    .status-partial { background: rgba(251,191,36,0.2); color: #fbbf24; }
    .status-running { background: rgba(59,130,246,0.2); color: #60a5fa; }
    .comparison-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
    .comparison-table th, .comparison-table td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #334155; font-size: 0.85rem; }
    .comparison-table th { background: #1e293b; color: #64748b; font-weight: 500; }
    .comparison-table td { color: #e2e8f0; }
    .metric-best { color: #4ade80; font-weight: 600; }
    .delta-positive { color: #60a5fa; font-weight: 500; }
    .delta-negative { color: #f87171; font-weight: 500; }
    .narrative-section { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 20px 24px; margin: 16px 0; line-height: 1.8; font-size: 0.9rem; }
    .narrative-section p { margin-bottom: 12px; }
    .label-tag { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 0.7rem; background: rgba(59,130,246,0.2); color: #60a5fa; margin-right: 4px; }
    @media print {
      body { background: #fff; color: #1e293b; }
      .node-card, .meta-item, .plot-card, .run-card, .narrative-section { border-color: #d1d5db; }
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
  if (value === null || value === undefined) return "\u2014";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  if (Array.isArray(value)) {
    const preview = value.slice(0, 3).map((v) => (typeof v === "number" ? v.toFixed(2) : String(v)));
    return `[${preview.join(", ")}${value.length > 3 ? "..." : ""}]`;
  }
  return String(value);
}

function buildNodeSection(node: ReportNode, plotImage?: string): string {
  const badge = getBadgeClass(node.nodeType);
  const params = Object.entries(node.parameters || {});

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
      const displayValue = typeof value === "object" ? JSON.stringify(value) : String(value);
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
  const dateStr = run.executed_at
    ? new Date(run.executed_at).toLocaleString()
    : "Unknown date";

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
  const allMetrics: [string, string, unknown][] = [];
  for (const [nodeId, metrics] of Object.entries(run.results_summary)) {
    if (typeof metrics === "object" && metrics !== null) {
      for (const [key, value] of Object.entries(metrics)) {
        const nodeLabel =
          nodes.find((n) => n.nodeId === nodeId)?.label || nodeId;
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
  if (!run.diagnostics || Object.keys(run.diagnostics).length === 0) return "";

  let html = `<h3>${escapeHtml(run.name)} — Diagnostics</h3>`;
  for (const [nodeId, diag] of Object.entries(run.diagnostics)) {
    if (typeof diag !== "object" || diag === null || Object.keys(diag).length === 0) continue;
    const nodeLabel = nodes.find((n) => n.nodeId === nodeId)?.label || nodeId;
    html += `<div class="node-card"><strong>${escapeHtml(nodeLabel)}</strong>`;
    html += `<table class="params-table"><tr><th>Key</th><th>Value</th></tr>`;
    for (const [key, value] of Object.entries(diag)) {
      html += `<tr><td><code>${escapeHtml(key)}</code></td><td>${escapeHtml(formatMetricValue(value))}</td></tr>`;
    }
    html += `</table></div>`;
  }
  return html;
}

const HIGHER_IS_BETTER = new Set(["r2", "accuracy", "explained_variance", "silhouette_score"]);

function buildComparisonSection(
  runs: RunReportEntry[],
  comparison: ReportComparison
): string {
  if (comparison.metric_keys.length === 0) return "";

  let html = `<table class="comparison-table"><tr><th>Metric</th>`;
  for (const run of runs) {
    html += `<th>${escapeHtml(run.name)}</th>`;
  }
  if (runs.length === 2) html += `<th>Delta</th>`;
  html += `</tr>`;

  for (const key of comparison.metric_keys) {
    const metricName = key.split(".").pop() || key;
    const values = comparison.diff[key] || {};
    const numericVals: { runId: string; val: number }[] = [];
    for (const [runId, val] of Object.entries(values)) {
      if (typeof val === "number" && !isNaN(val)) {
        numericVals.push({ runId, val });
      }
    }

    // Find best
    const higherBetter = HIGHER_IS_BETTER.has(metricName);
    let bestRunId: string | null = null;
    if (numericVals.length >= 2) {
      const sorted = [...numericVals].sort((a, b) =>
        higherBetter ? b.val - a.val : a.val - b.val
      );
      bestRunId = sorted[0].runId;
    }

    html += `<tr><td><code>${escapeHtml(metricName)}</code></td>`;
    for (const run of runs) {
      const val = values[String(run.id)];
      const isBest = bestRunId === String(run.id);
      const cls = isBest ? ' class="metric-best"' : "";
      html += `<td${cls}>${escapeHtml(formatMetricValue(val))}</td>`;
    }

    // Delta for 2-run comparison
    if (runs.length === 2 && numericVals.length === 2) {
      const delta = numericVals[1].val - numericVals[0].val;
      const sign = delta > 0 ? "+" : "";
      const cls = delta > 0 ? "delta-positive" : delta < 0 ? "delta-negative" : "";
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

  // AI Narrative (placed at top if available — executive summary)
  if (showNarrative && narrativeMarkdown) {
    html += `<h2>Summary</h2><div class="narrative-section">${markdownToSimpleHtml(narrativeMarkdown)}</div>`;
  }

  // Metadata grid
  html += `<h2>Metadata</h2><div class="meta-grid">
    <div class="meta-item"><div class="meta-label">Generated</div><div class="meta-value">${escapeHtml(generatedAt)}</div></div>
    <div class="meta-item"><div class="meta-label">Nodes</div><div class="meta-value">${nodes.length}</div></div>
    <div class="meta-item"><div class="meta-label">Connections</div><div class="meta-value">${edges.length}</div></div>`;

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
    for (const node of sorted) {
      const plotImage = plotImages.get(node.nodeId);
      html += buildNodeSection(node, plotImage);
    }

    // Plot gallery for remaining images not covered in node sections
    const standalonePlots = Array.from(plotImages.entries()).filter(
      ([nodeId]) => !sorted.find((n) => n.nodeId === nodeId)
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
  if (Object.keys(terminalMetrics).length > 0) {
    html += `<h2>Results</h2>`;
    for (const [nodeId, metrics] of Object.entries(terminalMetrics)) {
      const node = nodes.find((n) => n.nodeId === nodeId);
      html += `<h3>${escapeHtml(node?.label || nodeId)}</h3>`;
      html += `<table class="params-table"><tr><th>Metric</th><th>Value</th></tr>`;
      for (const [key, value] of Object.entries(metrics as Record<string, any>)) {
        const displayValue = typeof value === "number" ? value.toFixed(6) : String(value);
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
    const hasDiagnostics = runs.some(
      (r) => r.diagnostics && Object.keys(r.diagnostics).length > 0
    );
    if (hasDiagnostics) {
      html += `<h2>Diagnostics</h2>`;
      for (const run of runs) {
        html += buildDiagnosticsSection(run, nodes);
      }
    }
  }

  // Run comparison
  if (showComparison && comparison && runs && runs.length >= 2) {
    html += `<h2>Run Comparison</h2>`;
    html += buildComparisonSection(runs, comparison);
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
export function topologicalSort(nodes: ReportNode[], edges: ReportEdge[]): ReportNode[] {
  const nodeMap = new Map(nodes.map((n) => [n.nodeId, n]));
  const inDegree = new Map<string, number>();
  const adjacency = new Map<string, string[]>();

  for (const node of nodes) {
    inDegree.set(node.nodeId, 0);
    adjacency.set(node.nodeId, []);
  }

  for (const edge of edges) {
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

  return result;
}
