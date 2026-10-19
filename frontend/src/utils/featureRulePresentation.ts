import type { NodeOutput, PortOutput } from "@/utils/nodeOutput";

/** Variable-rule masks/scores are ordered on the rule's full X feature axis. */
export function featureRulePresentation(output: NodeOutput | null, input: PortOutput | NodeOutput | null | undefined): NodeOutput | null {
  if (!output) return null;
  const value = input && "value" in input ? input.value : input && "presentation_value" in input ? input.presentation_value : null;
  if (!value || typeof value !== "object") return output;
  const payload = value as Record<string, any>;
  const axis = payload.feature_axis ?? payload.x_axis;
  const count = output.data.length;
  const width = Array.isArray(payload.data?.[0]) ? payload.data[0].length : 0;
  if (width !== count || count === 0) return output;
  const labels = [axis?.labels, axis?.data].find(candidate => Array.isArray(candidate) && candidate.length === count);
  if (!labels) return output;
  return { ...output,
    metadata: { ...output.metadata, feature_names: labels.map(String), feature_coordinate_units: axis?.units },
    descriptor: output.descriptor ? { ...output.descriptor,
      dimensions: [{ role: "feature", size: count }, ...output.descriptor.dimensions.slice(1)] } : output.descriptor,
  };
}

/** Canonical K-means centroid row i is cluster i (zero-based). */
export function centroidPresentation(output: NodeOutput | null, input: PortOutput | NodeOutput | null | undefined): NodeOutput | null {
  if (!output || !output.descriptor || !Array.isArray(output.data[0])) return output;
  const clusters = (output.metadata.diagnostics as Record<string, unknown> | undefined)?.n_clusters;
  if (typeof clusters !== "number" || clusters !== output.data.length) return output;
  const value = input && "value" in input ? input.value : input && "presentation_value" in input ? input.presentation_value : null;
  const payload = value && typeof value === "object" ? value as Record<string, any> : null;
  const axis = payload?.feature_axis ?? payload?.x_axis;
  const width = output.data[0].length;
  const labels = Array.isArray(payload?.data?.[0]) && payload.data[0].length === width
    ? [axis?.labels, axis?.data].find(candidate => Array.isArray(candidate) && candidate.length === width) : null;
  return { ...output, metadata: { ...output.metadata,
    cluster_labels: Array.from({ length: clusters }, (_, index) => `Cluster ${index}`),
    ...(labels ? { feature_names: labels.map(String) } : {}),
  }, descriptor: { ...output.descriptor, dimensions: [{ role: "cluster", size: clusters }, { role: "feature", size: width }] } };
}

/** Canonical single-repeat OOF evidence preserves the full X observation order. */
export function outOfFoldIdentityPresentation(output: NodeOutput | null, input: PortOutput | NodeOutput | null | undefined): NodeOutput | null {
  if (!output) return null;
  const value = input && "value" in input ? input.value : input && "presentation_value" in input ? input.presentation_value : null;
  const payload = value && typeof value === "object" ? value as Record<string, any> : null;
  const labels = payload?.sample_axis?.labels ?? payload?.y_axis?.labels;
  if (!Array.isArray(labels) || labels.length !== output.data.length || payload?.data?.length !== labels.length) return output;
  return { ...output, data: output.data.map((row, index) => ({ Sample: String(labels[index]), ...(row as Record<string, unknown>) })),
    metadata: { ...output.metadata, sample_labels: labels.map(String) } };
}
