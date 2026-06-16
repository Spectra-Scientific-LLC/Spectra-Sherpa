/* eslint-disable @typescript-eslint/no-explicit-any -- report export extracts ad hoc numeric metrics from arbitrary terminal node outputs. */
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
import { collectCanonicalClassificationMetrics } from "@/utils/classificationMetrics";
import { downloadBlob } from "@/utils/download";
import type { NodeOutput } from "@/utils/nodeOutput";

declare const Plotly: {
  toImage: (el: HTMLElement, opts: { format: string; width: number; height: number }) => Promise<string>;
};

function isRecord(value: unknown): value is Record<string, any> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function numericShape(value: unknown): number[] | null {
  if (!isRecord(value)) return null;
  if (Array.isArray(value.shape) && value.shape.every((item) => typeof item === "number")) {
    return value.shape;
  }
  if (typeof value.n_samples === "number" && typeof value.n_features === "number") {
    return [value.n_samples, value.n_features];
  }
  return null;
}

function deriveTrueOutputShape(output: NodeOutput | undefined, fallback: number[] | null | undefined): number[] | null {
  if (!output) return fallback || null;
  const primaryPort = output.primary_port ? output.ports?.[output.primary_port] : undefined;
  const candidates = [
    primaryPort?.value,
    primaryPort?.metadata,
    output.metadata,
    output,
  ];
  for (const candidate of candidates) {
    const shape = numericShape(candidate);
    if (shape) return shape;
  }
  return fallback || null;
}

const REPORT_METRIC_KEYS = [
  "explained_variance_ratio",
  "r2",
  "R2",
  "r2_cv",
  "rmse",
  "RMSE",
  "rmsecv",
  "rmsep",
  "bias",
  "sep",
  "accuracy",
  "n_components",
  "n_clusters",
  "n_samples",
  "n_features",
  "n_targets",
  "n_evaluated",
  "selected_target",
  "target_mode",
];

function collectReportMetrics(source: unknown, metrics: Record<string, any>) {
  if (!isRecord(source)) return;
  for (const key of REPORT_METRIC_KEYS) {
    const value = source[key];
    if (typeof value === "number" || typeof value === "string" || Array.isArray(value)) {
      metrics[key] = value;
    }
  }
  collectCanonicalClassificationMetrics(source, metrics);
}

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
      const output = nodeOutputs.get(String(n.id)) ?? nodeOutputs.get(n.id as any);
      return {
        nodeId: String(n.id),
        nodeType: n.type,
        label: metadata?.label || n.type,
        parameters: n.params || {},
        positionX: n.x,
        positionY: n.y,
        status: n.executionState?.status,
        outputShape: deriveTrueOutputShape(output, n.executionState?.output_shape),
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
          collectReportMetrics(raw, metrics);
          collectReportMetrics(raw.metadata, metrics);
          // Also look inside ports.default or the raw data
          if (raw.ports?.default) {
            const defaultPort = raw.ports.default;
            collectReportMetrics(defaultPort, metrics);
            collectReportMetrics(defaultPort.metadata, metrics);
            collectReportMetrics(defaultPort.value, metrics);
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
    downloadBlob(blob, `${workflowStore.workflowName.replace(/\s+/g, "_").toLowerCase()}_report.html`);
  }

  return { exportReport };
}
