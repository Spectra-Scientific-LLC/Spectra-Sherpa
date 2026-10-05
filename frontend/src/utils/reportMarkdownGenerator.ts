import { reportNodePlotsMarkdown } from "./reportNodePlots";
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
import { topologicalSort, hasUnresolvedReportConnections } from "./reportGenerator";
import { reportRows, reportGroups, formatReportValue, reportMarkdownText } from "./reportValues";
import { scientificSummaryMarkdown } from "./scientificReportSummary";

function formatValue(value: unknown): string {
  return reportMarkdownText(formatReportValue(value));
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
  if (data.workflowIdentity) {
    lines.push(`- **Workflow sheet**: #${data.workflowIdentity.workflow_id}`);
    lines.push(`- **Project**: ${data.workflowIdentity.project_id == null ? "Not recorded" : `#${data.workflowIdentity.project_id}`}`);
    lines.push(`- **Data source**: ${data.workflowIdentity.source_name || "Not recorded"}`);
    lines.push(`- **Data origin**: ${data.workflowIdentity.source_origin === "example" ? "Bundled example" : data.workflowIdentity.source_origin === "current" ? "Current project data" : "Not recorded"}`);
  }
  return lines.join("\n");
}

function projectEvidenceMarkdown(data: ReportData): string {
  const snapshot = data.projectEvidence;
  if (!snapshot) return "";
  const lines = [
    "\n## Project evidence at generation\n",
    "These are the current project records captured for context, not proof that each belongs to the selected report runs.",
    `- **Captured**: ${reportMarkdownText(snapshot.capturedAt)}`,
    `- **Project**: ${snapshot.projectId ?? "unavailable"}`,
  ];
  if (snapshot.state !== "available") {
    lines.push(`- **Evidence**: ${reportMarkdownText(snapshot.reason ?? "Unavailable")}`);
  } else {
    lines.push("| Record | State | Active name | Digest |", "|---|---|---|---|");
    for (const record of snapshot.records) {
      lines.push(`| ${reportMarkdownText(record.label)} | ${record.state} | ${reportMarkdownText(record.name ?? "Not recorded")} | ${reportMarkdownText(record.digest ?? "—")} |`);
    }
  }
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
        lines.push(
          `- **Output**: ${node.outputType || "unknown"} [${node.outputShape.join(" x ")}]`,
        );
      }
      const params = reportRows(node.parameters);
      if (params.length > 0) {
        lines.push("- **Parameters**:");
        for (const [key, value] of params) {
          lines.push(`  - ${reportMarkdownText(key)}: ${formatValue(value)}`);
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
    const dateStr = run.executed_at ? new Date(run.executed_at).toLocaleString() : "Unknown date";
    lines.push(`### ${run.name}\n`);
    lines.push(`- **Status**: ${run.status}`);
    lines.push(`- **Executed**: ${dateStr}`);
    lines.push(`- **Saved run**: ${run.id}`);
    if (run.validation_summary?.schema_version === 'spectrasherpa-readable-validation/1' && run.validation_summary.run_id === run.id) {
      lines.push('\n#### Validation summary\n');
      const plain = (text: string) => text.replace(/[\\`*_{}[\]()#+.!<>|]/g, '\\$&').replace(/\r?\n/g, ' ');
      for (const row of run.validation_summary.rows) lines.push(`- **${plain(row.label)}**: ${plain(row.value)}`);
    }
    lines.push("", reportNodePlotsMarkdown(run));
    if (run.workflow_identity) {
      const origin = run.workflow_identity.source_origin === "example"
        ? "Bundled example"
        : run.workflow_identity.source_origin === "current"
          ? "Current project data"
          : "Not recorded";
      lines.push(`- **Run source**: ${run.workflow_identity.source_name || "Not recorded"} (${origin})`);
    }
    if (run.evidence_notice) lines.push(`- **Evidence**: ${run.evidence_notice}`);
    if (run.evidence_gaps?.length) {
      lines.push("\n#### Incomplete durable evidence\n");
      for (const gap of run.evidence_gaps) {
        const node = nodes.find((item) => item.nodeId === gap.node_id);
        const label = `${node?.label || gap.node_id} · ${gap.role || gap.output}`;
        lines.push(`- **${label}** (${gap.category.replace(/_/g, " ")}): ${gap.reason} ${gap.recovery}`);
      }
    }
    if (run.labels && run.labels.length > 0) {
      lines.push(`- **Labels**: ${run.labels.join(", ")}`);
    }
    if (run.integrity_hash) {
      lines.push(`- **Hash**: \`${run.integrity_hash}\``);
    }
    const provenance = run.selection_provenance;
    lines.push("\n#### Data selection and lineage\n");
    if (!provenance || provenance.state !== "exact") {
      lines.push(provenance?.reason || "Selection provenance is unavailable for this run.");
    } else {
      lines.push(`- **Workflow version**: ${provenance.workflow_version_id ?? "unsaved"}`);
      lines.push(`- **Executor**: User ${provenance.executor_user_id}`);
      for (const revision of provenance.revisions) {
        const selection = revision.selection;
        const target = selection.target_authority
          ? `${selection.target_authority.column} (${selection.target_authority.target_type}${selection.target_authority.units ? `, ${selection.target_authority.units}` : ""})`
          : "None";
        const receipt = provenance.scientific_receipts.find(
          (item) => item.node_id === revision.source_node_id,
        );
        lines.push(
          `\n##### ${selection.dataset_name} — selection revision ${revision.revision_number}\n`,
        );
        lines.push(`- **Selection author**: User ${revision.created_by} at ${revision.created_at}`);
        lines.push(`- **Source node**: \`${revision.source_node_id}\``);
        lines.push(
          `- **Files**: ${selection.selected_file_ids?.join(", ") || "All admitted files"}`,
        );
        lines.push(`- **Target**: ${target}`);
        lines.push(`- **Group**: ${selection.group_column || "None"}`);
        lines.push(`- **Scientific identity**: \`${selection.scientific_collection_sha256}\``);
        if (receipt) lines.push(`- **Executed output shape**: ${receipt.shape.join(" × ")}`);
        lines.push(`- **Change reason**: ${revision.reason || "No reason supplied"}`);
      }
      const filters = provenance.scientific_receipts.flatMap((receipt) =>
        (receipt.selection_lineage || []).map((lineage) => ({ receipt, lineage })),
      );
      if (filters.length) {
        lines.push("\n##### Executed sample filters\n");
        for (const { receipt, lineage } of filters) {
          const ranges = lineage.selected_index_ranges
            .map(([start, end]) => (start === end ? String(start + 1) : `${start + 1}-${end + 1}`))
            .join(", ");
          lines.push(`- **${lineage.node_id || receipt.node_id}**: ${ranges || "All input rows"}`);
          lines.push(`  - Rule: \`${JSON.stringify(lineage.parameters)}\``);
          lines.push(`  - Exact row receipt: \`${lineage.selected_indices_sha256}\``);
        }
      }
    }

    // Results summary
    const allMetrics: [string, string, unknown][] = [];
    for (const [nodeId, metrics] of reportGroups(run.results_summary)) {
      if (typeof metrics === "object" && metrics !== null) {
        for (const [key, value] of metrics) {
          const label =
            run.saved_definition?.nodes.find((n) => n.node_id === nodeId)?.label || nodeId;
          allMetrics.push([label, key, value]);
        }
      }
    }

    if (allMetrics.length > 0) {
      lines.push("\n| Node | Metric | Value |");
      lines.push("|------|--------|-------|");
      for (const [nodeLabel, key, value] of allMetrics) {
        lines.push(`| ${reportMarkdownText(nodeLabel)} | ${reportMarkdownText(key)} | ${formatValue(value)} |`);
      }
    }
    lines.push("");
  }
  return lines.join("\n");
}

function buildDiagnosticsSection(runs: RunReportEntry[], nodes: ReportNode[]): string {
  const hasDiag = runs.some((r) => reportGroups(r.diagnostics).length > 0);
  if (!hasDiag) return "";
  const lines: string[] = ["\n## Diagnostics\n"];

  for (const run of runs) {
    const groups = reportGroups(run.diagnostics);
    if (!groups.length) continue;
    lines.push(`### ${run.name}\n`);
    for (const [nodeId, diag] of groups) {
      const label = nodes.find((n) => n.nodeId === nodeId)?.label || nodeId;
      lines.push(`#### ${label}\n`);
      lines.push("| Key | Value |");
      lines.push("|-----|-------|");
      for (const [key, value] of diag) {
        lines.push(`| ${reportMarkdownText(key)} | ${formatValue(value)} |`);
      }
      lines.push("");
    }
  }
  return lines.join("\n");
}

const HIGHER_IS_BETTER = new Set(["r2", "accuracy", "explained_variance", "silhouette_score"]);

function buildComparisonSection(runs: RunReportEntry[], comparison: ReportComparison): string {
  if (!comparison.metric_keys.some((key) => runs.some((run) => formatReportValue(comparison.diff[key]?.[String(run.id)])))) return "";
  const lines: string[] = ["\n## Run Comparison\n"];
  if (!comparison.rankable_metrics?.length)
    lines.push("Evaluation compatibility is not established. Results are not ranked.\n");
  for (const pair of comparison.result_pairs ?? []) lines.push(`${pair.reason}\n`);

  // Header row
  const headers = ["Metric", ...runs.map((r) => r.name)];
  if (runs.length === 2) headers.push("Delta");
  lines.push(`| ${headers.join(" | ")} |`);
  lines.push(`|${headers.map(() => "------").join("|")}|`);

  for (const key of comparison.metric_keys) {
    if (!runs.some((run) => formatReportValue(comparison.diff[key]?.[String(run.id)]))) continue;
    const metricName = key.split(".").pop() || key;
    const values = comparison.diff[key] || {};
    const cells = [reportMarkdownText(key)];

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

    for (const run of runs) {
      const val = values[String(run.id)];
      const formatted = formatValue(val);
      const isBest = bestRunId === String(run.id);
      cells.push(isBest ? `**${formatted}**` : formatted);
    }

    if (rankable && runs.length === 2 && numericVals.length === 2) {
      const delta = Number(values[String(runs[1].id)]) - Number(values[String(runs[0].id)]);
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
  if (data.reportMode === "summary") {
    const ai = data.sections?.aiNarrative && data.narrativeMarkdown
      ? `\n## AI Summary (optional)\n${data.narrativeMarkdown}\n` : "";
    return `# ${reportMarkdownText(data.workflowName)}\n\n${scientificSummaryMarkdown(data)}\n${projectEvidenceMarkdown(data)}\n${(data.runs ?? []).map(reportNodePlotsMarkdown).join("\n")}${ai}\n---\nGenerated by SpectraSherpa — ${reportMarkdownText(data.generatedAt)}`;
  }
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
    parts.push("## AI Summary\n");
    parts.push(data.narrativeMarkdown);
    parts.push("");
  }

  // Metadata
  parts.push(buildMetadataSection(data));
  parts.push(projectEvidenceMarkdown(data));

  // Connections
  if (showConnections) {
    parts.push(buildConnectionsSection(data.nodes, data.edges));
  }

  // Pipeline steps
  if (showPipeline) {
    if (hasUnresolvedReportConnections(data.nodes, data.edges)) {
      parts.push(
        "Some saved connections have no retained node definition. All available steps are shown; pipeline order is not fully verified.\n",
      );
    }
    parts.push(buildPipelineSection(data.nodes, data.edges));
  }

  // Execution results
  if (showResults) {
    for (const [nodeId, rows] of reportGroups(data.terminalMetrics)) {
      parts.push(`\n## Results — ${reportMarkdownText(data.nodes.find((node) => node.nodeId === nodeId)?.label || nodeId)}\n`);
      parts.push("| Metric | Value |\n|--------|-------|");
      for (const [key, value] of rows) parts.push(`| ${reportMarkdownText(key)} | ${formatValue(value)} |`);
    }
  }
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
