type UnknownRecord = Record<string, unknown>;

export interface SplitMethodOption {
  label: string;
  value: unknown;
  disabled?: boolean;
  [key: string]: unknown;
}

export interface GroupedSplitSummary {
  method: string;
  nGroups: number;
  heldOutGroups: string[];
  digest: string | null;
}

// These methods select individual samples by spectral distance and have no
// whole-group definition, so they never hold a group out. Selecting a grouping
// column names a validation authority; the method decides whether the partition
// is constrained by it. They stay selectable with groups active and are labelled
// so the scientist can see which behaviour they are choosing.
export const SPACE_FILLING_SPLIT_METHODS = new Set(["kennard_stone", "duplex", "spxy"]);

const asRecord = (value: unknown): UnknownRecord | null =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as UnknownRecord)
    : null;

const nonEmptyString = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value.trim() : null;

const datasetGroupColumn = (value: unknown): string | null => {
  const record = asRecord(value);
  if (!record) return null;

  const extra = asRecord(record.extra);
  const binding = asRecord(extra?.supervision_binding);
  const direct = nonEmptyString(binding?.group_column);
  if (direct) return direct;

  const wrapped = datasetGroupColumn(record.value);
  if (wrapped) return wrapped;

  const ports = asRecord(record.ports);
  if (!ports) return null;
  for (const port of Object.values(ports)) {
    const found = datasetGroupColumn(port);
    if (found) return found;
  }
  return null;
};

export const groupColumnFromInputs = (
  inputs: ReadonlyArray<{ data?: unknown }> | undefined,
): string | null => {
  for (const input of inputs ?? []) {
    const found = datasetGroupColumn(input.data);
    if (found) return found;
  }
  return null;
};

export const splitMethodOptions = (
  options: unknown[] | undefined,
  groupActive: boolean,
): SplitMethodOption[] | undefined => {
  if (!options) return undefined;
  return options.map((option) => {
    const record = asRecord(option);
    const normalized: SplitMethodOption =
      typeof option === "string"
        ? { label: option, value: option }
        : {
            ...(record ?? {}),
            label: String(record?.label ?? record?.value ?? ""),
            value: record?.value ?? "",
          };
    const method = nonEmptyString(normalized.value);
    if (!groupActive || !method || !SPACE_FILLING_SPLIT_METHODS.has(method)) {
      return normalized;
    }
    return {
      ...normalized,
      label: `${normalized.label || method} — covers spectral extremes, does not hold out groups`,
    };
  });
};

// Stratification preserves the proportions of a target's classes, so it is
// defined only on a categorical response. A continuous response such as a
// moisture concentration has no classes to preserve. The planner refuses it, and
// naming it here means the scientist learns before the run rather than from a
// mid-execution message.
export const STRATIFIED_NEEDS_A_CATEGORICAL_TARGET =
  "Stratified splitting requires a categorical target; this target is continuous. Use random, sequential, or group holdout splitting.";

export const splitMethodTargetConflict = (
  method: string | null | undefined,
  targetType: string | null | undefined,
): string | null => {
  if (nonEmptyString(method) !== "stratified") return null;
  return nonEmptyString(targetType) === "continuous" ? STRATIFIED_NEEDS_A_CATEGORICAL_TARGET : null;
};

const splitPlanFromDataset = (value: unknown): GroupedSplitSummary | null => {
  const record = asRecord(value);
  if (!record) return null;

  const provenance = Array.isArray(record.provenance) ? record.provenance : [];
  for (let index = provenance.length - 1; index >= 0; index -= 1) {
    const entry = asRecord(provenance[index]);
    if (entry?.op_id !== "data.train_test_split") continue;
    const parameters = asRecord(entry.parameters);
    const nGroups = parameters?.n_groups;
    const heldOut = parameters?.held_out_groups;
    if (
      typeof nGroups !== "number" ||
      !Number.isInteger(nGroups) ||
      nGroups < 2 ||
      !Array.isArray(heldOut) ||
      heldOut.length === 0
    ) {
      return null;
    }
    return {
      method: nonEmptyString(parameters?.method) ?? "group-aware",
      nGroups,
      heldOutGroups: heldOut.map((group) => String(group)),
      digest: nonEmptyString(parameters?.digest),
    };
  }

  const wrapped = splitPlanFromDataset(record.value);
  if (wrapped) return wrapped;
  const ports = asRecord(record.ports);
  if (!ports) return null;
  for (const port of Object.values(ports)) {
    const found = splitPlanFromDataset(port);
    if (found) return found;
  }
  return null;
};

export const groupedSplitSummary = (nodeOutput: unknown): GroupedSplitSummary | null =>
  splitPlanFromDataset(nodeOutput);
