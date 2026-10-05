/** Same exact label-or-one-based-column rule as the canonical Select Columns node. */
export function featureColumnOptions(input: unknown): string[] {
  if (!input || typeof input !== "object") return [];
  let dataset = input as Record<string, unknown>;
  if (dataset.value && typeof dataset.value === "object") dataset = dataset.value as Record<string, unknown>;
  if (dataset.default && typeof dataset.default === "object") dataset = dataset.default as Record<string, unknown>;
  const axis = (dataset.feature_axis ?? dataset.x_axis) as Record<string, unknown> | undefined;
  if (Array.isArray(axis?.labels)) return axis.labels.map(String);
  const shape = dataset.shape;
  const width = Number(dataset.n_features ?? (Array.isArray(shape) ? shape[shape.length - 1] : 0));
  const metadata = dataset.metadata as Record<string, unknown> | undefined;
  const extra = dataset.extra as Record<string, unknown> | undefined;
  const retained = metadata?.feature_names ?? extra?.feature_names;
  if (Array.isArray(retained) && retained.length === width) return retained.map(String);
  return Number.isInteger(width) && width > 0 && width <= 100000
    ? Array.from({ length: width }, (_, i) => `Column ${i + 1}`) : [];
}
