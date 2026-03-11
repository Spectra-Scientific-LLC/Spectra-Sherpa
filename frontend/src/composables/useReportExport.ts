/**
 * Composable for exporting provenance reports from the workflow builder.
 *
 * Captures Plotly chart images via Plotly.toImage(), assembles report data
 * from the workflow store, and triggers an HTML file download.
 */

import { useWorkflowStore } from "@/stores/workflow";
import {
  generateProvenanceReport,
  type ReportData,
  type ReportNode,
  type ReportEdge,
} from "@/utils/reportGenerator";
import type { NodeOutput } from "@/utils/nodeOutput";

declare const Plotly: {
  toImage: (el: HTMLElement, opts: { format: string; width: number; height: number }) => Promise<string>;
};

export function useReportExport() {
  const workflowStore = useWorkflowStore();

  async function exportReport(
    nodeOutputs: Map<string, NodeOutput>,
    plotRefs?: Map<string, HTMLElement>
  ): Promise<void> {
    // 1. Capture plot images from Plotly chart containers
    const plotImages = new Map<string, string>();

    if (plotRefs && typeof Plotly !== "undefined") {
      for (const [nodeId, el] of plotRefs) {
        try {
          const dataUrl = await Plotly.toImage(el, {
            format: "png",
            width: 800,
            height: 400,
          });
          plotImages.set(nodeId, dataUrl);
        } catch {
          // Skip if Plotly.toImage fails for this element
        }
      }
    }

    // 2. Build report nodes from workflow store
    const reportNodes: ReportNode[] = workflowStore.nodes.map((n) => {
      const metadata = workflowStore.getNodeMetadata(n.type);
      return {
        nodeId: String(n.id),
        nodeType: n.type,
        label: metadata?.label || n.type,
        parameters: n.params || {},
        positionX: n.x,
        positionY: n.y,
        status: n.executionState?.status,
        outputShape: n.executionState?.output_shape || null,
        outputType: n.executionState?.output_type || null,
      };
    });

    // 3. Build report edges
    const reportEdges: ReportEdge[] = workflowStore.edges.map((e) => ({
      fromNodeId: String(e.from),
      toNodeId: String(e.to),
      fromOutput: e.fromPort || "default",
      toInput: e.toPort || "default",
    }));

    // 4. Extract terminal metrics from execution results
    const terminalMetrics: Record<string, any> = {};
    const outgoing = new Set(workflowStore.edges.map((e) => e.from));
    for (const node of workflowStore.nodes) {
      if (!outgoing.has(node.id)) {
        // Terminal node — no outgoing edges
        const output = nodeOutputs.get(node.id);
        if (output && typeof output === "object") {
          // Extract numeric metrics from the output
          const metrics: Record<string, any> = {};
          const raw = output as any;
          for (const key of ["explained_variance_ratio", "r2", "rmse", "accuracy", "n_components", "n_clusters"]) {
            if (raw[key] !== undefined) metrics[key] = raw[key];
          }
          // Also look inside ports.default or the raw data
          if (raw.ports?.default) {
            const defaultPort = raw.ports.default;
            for (const key of Object.keys(defaultPort)) {
              if (typeof defaultPort[key] === "number") {
                metrics[key] = defaultPort[key];
              }
            }
          }
          if (Object.keys(metrics).length > 0) {
            terminalMetrics[String(node.id)] = metrics;
          }
        }
      }
    }

    // 5. Assemble report data
    const reportData: ReportData = {
      workflowName: workflowStore.workflowName,
      workflowDescription: workflowStore.workflowDescription || null,
      integrityHash: workflowStore.workflowHash,
      generatedAt: new Date().toISOString().replace("T", " ").slice(0, 19) + " UTC",
      nodes: reportNodes,
      edges: reportEdges,
      plotImages,
      terminalMetrics,
    };

    // 6. Generate HTML and trigger download
    const html = generateProvenanceReport(reportData);
    const blob = new Blob([html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${workflowStore.workflowName.replace(/\s+/g, "_").toLowerCase()}_report.html`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return { exportReport };
}
