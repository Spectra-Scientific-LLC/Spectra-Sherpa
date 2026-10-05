export type AxisSetOption = { label: string; value: string };

export type AxisScaleSetWire = {
  name: string;
  values: number[];
  title?: string | null;
  units?: string | null;
  axis_type?: string | null;
  source_set_index: number;
};

export type AxisLabelSetWire = {
  name: string;
  values: string[];
  source_set_index: number;
};

export type AxisTitleSetWire = {
  name: string;
  title: string;
  source_set_index: number;
};

export type AxisClassLevelWire = { code: unknown; label: string };

export type AxisClassSetWire = {
  name: string;
  values: unknown[];
  levels?: AxisClassLevelWire[];
  source_set_index: number;
};

export type DatasetAxisWire = {
  axis_class?: string;
  data?: number[];
  labels?: string[];
  title?: string | null;
  units?: string | null;
  display_units?: string | null;
  quantity?: string | null;
  include_mask?: boolean[];
  primary_scale_name?: string | null;
  alternate_scales?: AxisScaleSetWire[];
  primary_label_name?: string | null;
  alternate_label_sets?: AxisLabelSetWire[];
  primary_title_name?: string | null;
  alternate_title_sets?: AxisTitleSetWire[];
  class_sets?: AxisClassSetWire[];
  primary_class_set_name?: string | null;
  sample_table?: Record<string, unknown[]>;
};

export type DatasetAxisDisplayState =
  | { kind: "absent" }
  | { kind: "invalid"; message: string }
  | {
      kind: "valid";
      axis: DatasetAxisWire;
      length: number;
      scaleOptions: AxisSetOption[];
      labelOptions: AxisSetOption[];
      titleOptions: AxisSetOption[];
      classOptions: AxisSetOption[];
    };

export type DatasetAxisDisplayProjection = {
  values: number[];
  labels: string[];
  title: string;
  units: string;
  quantity: string | null;
  axisType: string | null;
  scaleName: string | null;
  labelSetName: string | null;
  titleSetName: string | null;
};

const PRIMARY = "__primary__";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exactText(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.trim() === value;
}

function exactIndex(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function numericValues(value: unknown, length: number | null): number[] | null {
  if (!Array.isArray(value) || (length !== null && value.length !== length)) return null;
  if (!value.every((item) => typeof item === "number" && Number.isFinite(item))) return null;
  return value as number[];
}

function textValues(value: unknown, length: number | null): string[] | null {
  if (!Array.isArray(value) || (length !== null && value.length !== length)) return null;
  if (!value.every(exactText)) return null;
  return value as string[];
}

function alignedLength(axis: Record<string, unknown>): number | null {
  const direct = [axis.data, axis.labels, axis.include_mask].find(Array.isArray) as
    | unknown[]
    | undefined;
  if (direct) return direct.length;
  for (const key of ["alternate_scales", "alternate_label_sets", "class_sets"] as const) {
    const sets = axis[key];
    if (Array.isArray(sets) && sets.length && isRecord(sets[0]) && Array.isArray(sets[0].values)) {
      return sets[0].values.length;
    }
  }
  return 0;
}

function uniqueSetNames(items: unknown, kind: string): string | null {
  if (items == null) return null;
  if (!Array.isArray(items) || items.length > 64) return `Axis ${kind} sets are malformed.`;
  const names = new Set<string>();
  const indices = new Set<number>();
  for (const item of items) {
    if (!isRecord(item) || !exactText(item.name) || !exactIndex(item.source_set_index)) {
      return `Axis ${kind} sets are malformed.`;
    }
    if (names.has(item.name) || indices.has(item.source_set_index)) {
      return `Axis ${kind} sets contain duplicate identities.`;
    }
    names.add(item.name);
    indices.add(item.source_set_index);
  }
  return null;
}

function optionLabel(name: string, suffix: string): string {
  return suffix ? `${name} · ${suffix}` : name;
}

export function datasetAxisDisplayState(
  rawAxis: unknown,
  expectedLength?: number,
): DatasetAxisDisplayState {
  if (rawAxis == null) return { kind: "absent" };
  if (!isRecord(rawAxis)) return { kind: "invalid", message: "Axis metadata is malformed." };
  const length = alignedLength(rawAxis);
  if (length === null || (expectedLength != null && length !== expectedLength)) {
    return { kind: "invalid", message: "Axis metadata does not match its dataset dimension." };
  }
  if (rawAxis.data != null && numericValues(rawAxis.data, length) === null) {
    return { kind: "invalid", message: "The primary axis scale is malformed." };
  }
  if (rawAxis.labels != null && textValues(rawAxis.labels, length) === null) {
    return { kind: "invalid", message: "The primary axis labels are malformed." };
  }
  if (
    rawAxis.include_mask != null &&
    (!Array.isArray(rawAxis.include_mask) ||
      rawAxis.include_mask.length !== length ||
      !rawAxis.include_mask.every((item) => typeof item === "boolean"))
  ) {
    return { kind: "invalid", message: "The axis include mask is malformed." };
  }

  for (const [field, kind] of [
    ["alternate_scales", "scale"],
    ["alternate_label_sets", "label"],
    ["alternate_title_sets", "title"],
    ["class_sets", "class"],
  ] as const) {
    const problem = uniqueSetNames(rawAxis[field], kind);
    if (problem) return { kind: "invalid", message: problem };
  }

  const scales = (rawAxis.alternate_scales ?? []) as unknown[];
  for (const item of scales) {
    const set = item as Record<string, unknown>;
    if (
      numericValues(set.values, length) === null ||
      (set.title != null && !exactText(set.title)) ||
      (set.units != null && !exactText(set.units)) ||
      (set.axis_type != null && !exactText(set.axis_type))
    ) {
      return { kind: "invalid", message: "An alternate axis scale is malformed." };
    }
  }
  const labelSets = (rawAxis.alternate_label_sets ?? []) as unknown[];
  for (const item of labelSets) {
    if (textValues((item as Record<string, unknown>).values, length) === null) {
      return { kind: "invalid", message: "An alternate axis label set is malformed." };
    }
  }
  const titleSets = (rawAxis.alternate_title_sets ?? []) as unknown[];
  for (const item of titleSets) {
    if (!exactText((item as Record<string, unknown>).title)) {
      return { kind: "invalid", message: "An alternate axis title is malformed." };
    }
  }
  const classSets = (rawAxis.class_sets ?? []) as unknown[];
  for (const item of classSets) {
    const set = item as Record<string, unknown>;
    if (!Array.isArray(set.values) || set.values.length !== length) {
      return { kind: "invalid", message: "An axis class set is not aligned to its dimension." };
    }
    if (set.levels != null && !Array.isArray(set.levels)) {
      return { kind: "invalid", message: "An axis class-level lookup is malformed." };
    }
  }

  const primaryScale = rawAxis.primary_scale_name;
  const primaryLabel = rawAxis.primary_label_name;
  const primaryTitle = rawAxis.primary_title_name;
  if (
    (primaryScale != null && !exactText(primaryScale)) ||
    (primaryLabel != null && !exactText(primaryLabel)) ||
    (primaryTitle != null && !exactText(primaryTitle))
  ) {
    return { kind: "invalid", message: "The primary axis-set identity is malformed." };
  }

  const scaleOptions: AxisSetOption[] = [];
  if (Array.isArray(rawAxis.data)) {
    scaleOptions.push({
      label: optionLabel(String(primaryScale ?? "Primary scale"), String(rawAxis.units ?? "")),
      value: PRIMARY,
    });
  }
  for (const item of scales as Array<Record<string, unknown>>) {
    scaleOptions.push({
      label: optionLabel(String(item.name), String(item.units ?? item.axis_type ?? "")),
      value: `scale:${item.name}`,
    });
  }
  const labelOptions: AxisSetOption[] = [];
  if (Array.isArray(rawAxis.labels)) {
    labelOptions.push({ label: String(primaryLabel ?? "Primary labels"), value: PRIMARY });
  }
  for (const item of labelSets as Array<Record<string, unknown>>) {
    labelOptions.push({ label: String(item.name), value: `labels:${item.name}` });
  }
  const titleOptions: AxisSetOption[] = [];
  if (exactText(rawAxis.title)) {
    titleOptions.push({ label: String(primaryTitle ?? rawAxis.title), value: PRIMARY });
  }
  for (const item of titleSets as Array<Record<string, unknown>>) {
    titleOptions.push({ label: String(item.name), value: `title:${item.name}` });
  }
  const classOptions = (classSets as Array<Record<string, unknown>>).map((item) => ({
    label: String(item.name),
    value: `class:${item.name}`,
  }));
  return {
    kind: "valid",
    axis: rawAxis as DatasetAxisWire,
    length,
    scaleOptions,
    labelOptions,
    titleOptions,
    classOptions,
  };
}

export function projectDatasetAxisDisplay(
  state: DatasetAxisDisplayState,
  scaleChoice = PRIMARY,
  labelChoice = PRIMARY,
  titleChoice = PRIMARY,
): DatasetAxisDisplayProjection | null {
  if (state.kind !== "valid") return null;
  const { axis } = state;
  let values = Array.isArray(axis.data) ? axis.data : [];
  let title = axis.title ?? "";
  let units = axis.units ?? "";
  let quantity = axis.quantity ?? null;
  let axisType: string | null = null;
  let scaleName = axis.primary_scale_name ?? null;
  if (scaleChoice.startsWith("scale:")) {
    const name = scaleChoice.slice("scale:".length);
    const scale = axis.alternate_scales?.find((item) => item.name === name);
    if (scale) {
      values = scale.values;
      title = scale.title ?? title;
      units = scale.units ?? units;
      quantity = null;
      axisType = scale.axis_type ?? null;
      scaleName = scale.name;
    }
  }
  let labels = Array.isArray(axis.labels) ? axis.labels : [];
  let labelSetName = axis.primary_label_name ?? null;
  if (labelChoice.startsWith("labels:")) {
    const name = labelChoice.slice("labels:".length);
    const labelSet = axis.alternate_label_sets?.find((item) => item.name === name);
    if (labelSet) {
      labels = labelSet.values;
      labelSetName = labelSet.name;
    }
  }
  let titleSetName = axis.primary_title_name ?? null;
  if (titleChoice.startsWith("title:")) {
    const name = titleChoice.slice("title:".length);
    const titleSet = axis.alternate_title_sets?.find((item) => item.name === name);
    if (titleSet) {
      title = titleSet.title;
      titleSetName = titleSet.name;
    }
  }
  return { values, labels, title, units, quantity, axisType, scaleName, labelSetName, titleSetName };
}

export const PRIMARY_AXIS_SET = PRIMARY;
