import type { NodeTypeMetadata } from "@/types";

export type NodeVisualCategory =
  | "data"
  | "synthesis"
  | "preprocess"
  | "selection"
  | "exploratory"
  | "regression"
  | "classify"
  | "clustering"
  | "validation"
  | "visualize"
  | "export"
  | "plugin"
  | "default";

const CATEGORY_TO_VISUAL: Record<string, NodeVisualCategory> = {
  data: "data",
  synthesis: "synthesis",
  preprocessing: "preprocess",
  selection: "selection",
  exploratory: "exploratory",
  modeling: "exploratory",
  regression: "regression",
  classification: "classify",
  clustering: "clustering",
  validation: "validation",
  diagnostics: "validation",
  analysis: "validation",
  stats: "validation",
  time_series: "validation",
  output: "visualize",
  deploy: "export",
};

const PREFIX_TO_VISUAL: Record<string, NodeVisualCategory> = {
  data: "data",
  synthesis: "synthesis",
  preprocess: "preprocess",
  normalize: "preprocess",
  baseline: "preprocess",
  smooth: "preprocess",
  derivative: "preprocess",
  transfer: "preprocess",
  selection: "selection",
  model: "exploratory",
  classification: "classify",
  analysis: "validation",
  diagnostics: "validation",
  stats: "validation",
  time_series: "validation",
  output: "visualize",
  deploy: "export",
};

export const NODE_VISUAL_COLOR_CLASS: Record<NodeVisualCategory, string> = {
  data: "node-data",
  synthesis: "node-synthesis",
  preprocess: "node-preprocess",
  selection: "node-selection",
  exploratory: "node-exploratory",
  regression: "node-regression",
  classify: "node-classify",
  clustering: "node-clustering",
  validation: "node-validation",
  visualize: "node-visualize",
  export: "node-export",
  plugin: "node-plugin",
  default: "node-plugin",
};

export const getNodeVisualCategory = (
  nodeType: string,
  metadata?: Pick<NodeTypeMetadata, "category" | "node_type"> | null,
): NodeVisualCategory => {
  if (metadata?.node_type === "output.export" || nodeType === "output.export") {
    return "export";
  }

  const metadataCategory = String(metadata?.category || "").toLowerCase();
  if (metadataCategory) {
    const mapped = CATEGORY_TO_VISUAL[metadataCategory];
    if (mapped) return mapped;
    return "plugin";
  }

  const prefix = nodeType.includes(".") ? nodeType.split(".")[0].toLowerCase() : nodeType.toLowerCase();
  return PREFIX_TO_VISUAL[prefix] || "default";
};

export const getNodeVisualColorClass = (
  nodeType: string,
  metadata?: Pick<NodeTypeMetadata, "category" | "node_type"> | null,
): string => NODE_VISUAL_COLOR_CLASS[getNodeVisualCategory(nodeType, metadata)];
