/**
 * Provenance report generator — produces self-contained HTML from workflow
 * execution data. All plots are embedded as base64 PNG (no external deps).
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

export interface ReportData {
  workflowName: string;
  workflowDescription: string | null;
  integrityHash: string | null;
  generatedAt: string;
  nodes: ReportNode[];
  edges: ReportEdge[];
  plotImages: Map<string, string>; // nodeId -> base64 PNG data URL
  terminalMetrics: Record<string, any>;
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
    @media print {
      body { background: #fff; color: #1e293b; }
      .node-card, .meta-item, .plot-card { border-color: #d1d5db; }
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

export function generateProvenanceReport(data: ReportData): string {
  const { workflowName, workflowDescription, integrityHash, generatedAt, nodes, edges, plotImages, terminalMetrics } = data;

  // Topological sort for node ordering
  const sorted = topologicalSort(nodes, edges);

  let html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Provenance Report: ${escapeHtml(workflowName)}</title>
  <style>${buildStyleSheet()}</style>
</head>
<body>
  <h1>${escapeHtml(workflowName)}</h1>`;

  if (workflowDescription) {
    html += `<p style="color:#94a3b8;margin-bottom:16px">${escapeHtml(workflowDescription)}</p>`;
  }

  // Metadata grid
  html += `<h2>Metadata</h2><div class="meta-grid">
    <div class="meta-item"><div class="meta-label">Generated</div><div class="meta-value">${escapeHtml(generatedAt)}</div></div>
    <div class="meta-item"><div class="meta-label">Nodes</div><div class="meta-value">${nodes.length}</div></div>
    <div class="meta-item"><div class="meta-label">Connections</div><div class="meta-value">${edges.length}</div></div>`;

  if (integrityHash) {
    html += `<div class="meta-item" style="grid-column: 1/-1"><div class="meta-label">Integrity Hash (SHA-256)</div><div class="meta-value hash">${escapeHtml(integrityHash)}</div></div>`;
  }
  html += `</div>`;

  // Connections table
  if (edges.length > 0) {
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

  // Terminal metrics
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

  // Footer
  html += `<div class="footer">
    Generated by SpectraSherpa Lite &mdash; ${escapeHtml(generatedAt)}
    ${integrityHash ? `<br/>Integrity Hash: <span class="hash">${escapeHtml(integrityHash)}</span>` : ""}
  </div>
</body>
</html>`;

  return html;
}

/** Topological sort using Kahn's algorithm */
function topologicalSort(nodes: ReportNode[], edges: ReportEdge[]): ReportNode[] {
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
