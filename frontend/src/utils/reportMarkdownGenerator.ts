/**
 * Markdown report generator — produces clean markdown from the same
 * ReportData used by the HTML generator. Keeps both export formats
 * perfectly synchronized.
 */

import type {
  ReportData,
  ReportNode,
  ReportEdge,
  RunReportEntry,
  ReportComparison,
} from "./reportGenerator";
import { topologicalSort } from "./reportGenerator";

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "\u2014";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  if (Array.isArray(value)) {
    const preview = value.slice(0, 3).map((v) => (typeof v === "number" ? v.toFixed(2) : String(v)));
    return `[${preview.join(", ")}${value.length > 3 ? "..." : ""}]`;
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function getBadgeLabel(nodeType: string): string {
  const category = nodeType.split(".")[0];
  return category.charAt(0).toUpperCase() + category.slice(1);
}

function buildMetadataSection(data: ReportData): string {
  const lines: string[] = ["## Metadata\n"];
  lines.push(`- **Generated**: ${data.generatedAt}`);
  lines.push(`- **Nodes**: ${data.nodes.length}`);
  lines.push(`- **Connections**: ${data.edges.length}`);
  if (data.technique) lines.push(`- **Technique**: ${data.technique}`);
  if (data.sampleType) lines.push(`- **Sample Type**: ${data.sampleType}`);
  if (data.integrityHash) lines.push(`- **Integrity Hash**: \`${data.integrityHash}\``);
  return lines.join("\n");
}

function buildConnectionsSection(nodes: ReportNode[], edges: ReportEdge[]): string {
  if (edges.length === 0) return "";
  const lines: string[] = ["\n## Connections\n"];
  lines.push("| From | To | Ports |");
  lines.push("|------|-----|-------|");
  for (const edge of edges) {
    const from = nodes.find((n) => n.nodeId === edge.fromNodeId)?.label || edge.fromNodeId;
    const to = nodes.find((n) => n.nodeId === edge.toNodeId)?.label || edge.toNodeId;
    lines.push(`| ${from} | ${to} | ${edge.fromOutput} \u2192 ${edge.toInput} |`);
  }
  return lines.join("\n");
}

function buildPipelineSection(nodes: ReportNode[], edges: ReportEdge[]): string {
  const sorted = topologicalSort(nodes, edges);
  const lines: string[] = ["\n## Pipeline Steps\n"];

  // Group by category
  const groups: Record<string, ReportNode[]> = {};
  for (const node of sorted) {
    const category = getBadgeLabel(node.nodeType);
    if (!groups[category]) groups[category] = [];
    groups[category].push(node);
  }

  for (const [category, categoryNodes] of Object.entries(groups)) {
    lines.push(`### ${category}\n`);
    for (const node of categoryNodes) {
      lines.push(`#### ${node.label}\n`);
      lines.push(`- **Type**: \`${node.nodeType}\``);
      lines.push(`- **ID**: \`${node.nodeId}\``);
      if (node.status) lines.push(`- **Status**: ${node.status}`);
      if (node.outputShape) {
        lines.push(`- **Output**: ${node.outputType || "unknown"} [${node.outputShape.join(" x ")}]`);
      }
      const params = Object.entries(node.parameters || {});
      if (params.length > 0) {
        lines.push("- **Parameters**:");
        for (const [key, value] of params) {
          lines.push(`  - \`${key}\`: ${formatValue(value)}`);
        }
      }
      lines.push("");
    }
  }
  return lines.join("\n");
}

function buildRunsSection(runs: RunReportEntry[], nodes: ReportNode[]): string {
  if (!runs || runs.length === 0) return "";
  const lines: string[] = ["\n## Execution Runs\n"];

  for (const run of runs) {
    const dateStr = run.executed_at
      ? new Date(run.executed_at).toLocaleString()
      : "Unknown date";
    lines.push(`### ${run.name}\n`);
    lines.push(`- **Status**: ${run.status}`);
    lines.push(`- **Executed**: ${dateStr}`);
    if (run.labels && run.labels.length > 0) {
      lines.push(`- **Labels**: ${run.labels.join(", ")}`);
    }
    if (run.integrity_hash) {
      lines.push(`- **Hash**: \`${run.integrity_hash}\``);
    }

    // Results summary
    const allMetrics: [string, string, unknown][] = [];
    for (const [nodeId, metrics] of Object.entries(run.results_summary)) {
      if (typeof metrics === "object" && metrics !== null) {
        for (const [key, value] of Object.entries(metrics)) {
          const label = nodes.find((n) => n.nodeId === nodeId)?.label || nodeId;
          allMetrics.push([label, key, value]);
        }
      }
    }

    if (allMetrics.length > 0) {
      lines.push("\n| Node | Metric | Value |");
      lines.push("|------|--------|-------|");
      for (const [nodeLabel, key, value] of allMetrics) {
        lines.push(`| ${nodeLabel} | \`${key}\` | ${formatValue(value)} |`);
      }
    }
    lines.push("");
  }
  return lines.join("\n");
}

function buildDiagnosticsSection(runs: RunReportEntry[], nodes: ReportNode[]): string {
  const hasDiag = runs.some((r) => r.diagnostics && Object.keys(r.diagnostics).length > 0);
  if (!hasDiag) return "";
  const lines: string[] = ["\n## Diagnostics\n"];

  for (const run of runs) {
    if (!run.diagnostics || Object.keys(run.diagnostics).length === 0) continue;
    lines.push(`### ${run.name}\n`);
    for (const [nodeId, diag] of Object.entries(run.diagnostics)) {
      if (typeof diag !== "object" || diag === null || Object.keys(diag).length === 0) continue;
      const label = nodes.find((n) => n.nodeId === nodeId)?.label || nodeId;
      lines.push(`#### ${label}\n`);
      lines.push("| Key | Value |");
      lines.push("|-----|-------|");
      for (const [key, value] of Object.entries(diag)) {
        lines.push(`| \`${key}\` | ${formatValue(value)} |`);
      }
      lines.push("");
    }
  }
  return lines.join("\n");
}

const HIGHER_IS_BETTER = new Set(["r2", "accuracy", "explained_variance", "silhouette_score"]);

function buildComparisonSection(
  runs: RunReportEntry[],
  comparison: ReportComparison
): string {
  if (comparison.metric_keys.length === 0) return "";
  const lines: string[] = ["\n## Run Comparison\n"];

  // Header row
  const headers = ["Metric", ...runs.map((r) => r.name)];
  if (runs.length === 2) headers.push("Delta");
  lines.push(`| ${headers.join(" | ")} |`);
  lines.push(`|${headers.map(() => "------").join("|")}|`);

  for (const key of comparison.metric_keys) {
    const metricName = key.split(".").pop() || key;
    const values = comparison.diff[key] || {};
    const cells = [`\`${metricName}\``];

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

    for (const run of runs) {
      const val = values[String(run.id)];
      const formatted = formatValue(val);
      const isBest = bestRunId === String(run.id);
      cells.push(isBest ? `**${formatted}**` : formatted);
    }

    if (runs.length === 2 && numericVals.length === 2) {
      const delta = numericVals[1].val - numericVals[0].val;
      const sign = delta > 0 ? "+" : "";
      const formatted = Number.isInteger(delta) ? String(delta) : delta.toFixed(4);
      cells.push(`${sign}${formatted}`);
    } else if (runs.length === 2) {
      cells.push("\u2014");
    }

    lines.push(`| ${cells.join(" | ")} |`);
  }
  return lines.join("\n");
}

export function generateMarkdownReport(data: ReportData): string {
  const sections = data.sections;
  const showPipeline = sections?.pipelineDetails ?? true;
  const showConnections = sections?.connections ?? true;
  const showResults = sections?.executionResults ?? true;
  const showDiagnostics = sections?.diagnostics ?? false;
  const showComparison = sections?.runComparison ?? false;
  const showNarrative = sections?.aiNarrative ?? false;

  const parts: string[] = [];

  // Title
  parts.push(`# ${data.workflowName}\n`);
  if (data.workflowDescription) {
    parts.push(`${data.workflowDescription}\n`);
  }

  // AI Narrative (executive summary at top)
  if (showNarrative && data.narrativeMarkdown) {
    parts.push("## Summary\n");
    parts.push(data.narrativeMarkdown);
    parts.push("");
  }

  // Metadata
  parts.push(buildMetadataSection(data));

  // Connections
  if (showConnections) {
    parts.push(buildConnectionsSection(data.nodes, data.edges));
  }

  // Pipeline steps
  if (showPipeline) {
    parts.push(buildPipelineSection(data.nodes, data.edges));
  }

  // Execution results
  if (showResults && data.runs) {
    parts.push(buildRunsSection(data.runs, data.nodes));
  }

  // Diagnostics
  if (showDiagnostics && data.runs) {
    parts.push(buildDiagnosticsSection(data.runs, data.nodes));
  }

  // Comparison
  if (showComparison && data.comparison && data.runs && data.runs.length >= 2) {
    parts.push(buildComparisonSection(data.runs, data.comparison));
  }

  // Footer
  parts.push(`\n---\n*Generated by SpectraSherpa \u2014 ${data.generatedAt}*`);
  if (data.integrityHash) {
    parts.push(`\n*Integrity Hash: \`${data.integrityHash}\`*`);
  }

  return parts.filter(Boolean).join("\n");
}
