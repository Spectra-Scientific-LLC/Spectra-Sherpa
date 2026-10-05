import { createCategoryColorMap } from "@/utils/colors";

export type MetadataGroupingState =
  | { kind: "absent" }
  | { kind: "invalid"; message: string }
  | {
      kind: "valid";
      sampleIds: string[];
      columns: Record<string, string[]>;
      columnLabels: Record<string, string[]>;
      colorOptions: { label: string; value: string }[];
      symbolOptions: { label: string; value: string }[];
    };

const BLOCK_SYMBOLS = ["circle", "diamond", "square", "cross", "triangle-up", "triangle-down"];

export type MetadataStyleProjection = {
  colorKey: string;
  colorValues: string[];
  colorLabels: string[];
  colorCategories: string[];
  colorMap: Map<string | number, string>;
  useStyles: boolean;
  styleKey: string;
  styleValues: string[];
  styleLabels: string[];
  styleCategories: string[];
  symbolMap: Map<string, string>;
};

function exactStrings(value: unknown, rows: number): string[] | null {
  if (!Array.isArray(value) || value.length !== rows) return null;
  if (!value.every((item) => typeof item === "string" && item.length > 0 && item.trim() === item))
    return null;
  return value as string[];
}

function scalarIdentity(value: unknown): string | null {
  if (typeof value === "string") return `string:${value}`;
  if (typeof value === "boolean") return `boolean:${value}`;
  if (typeof value === "number") {
    if (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value)))
      return null;
    return `number:${JSON.stringify(value)}`;
  }
  if (value === null) return "null:null";
  return null;
}

function scalarLabel(value: unknown): string {
  return value === null ? "Missing" : String(value);
}

export function metadataGroupingState(yAxis: unknown, rows: number): MetadataGroupingState {
  if (!yAxis || typeof yAxis !== "object") return { kind: "absent" };
  const axis = yAxis as Record<string, unknown>;
  const table = axis.sample_table;
  const classSets = axis.class_sets;
  if (table == null && classSets == null) return { kind: "absent" };
  if (table != null && (!table || typeof table !== "object" || Array.isArray(table))) {
    return {
      kind: "invalid",
      message: "Metadata grouping refused: the sample table is malformed.",
    };
  }
  if (classSets != null && !Array.isArray(classSets)) {
    return {
      kind: "invalid",
      message: "Metadata grouping refused: the axis class sets are malformed.",
    };
  }
  const values = (table ?? {}) as Record<string, unknown>;
  const labels = exactStrings(axis.labels, rows);
  if (!labels) {
    return {
      kind: "invalid",
      message: "Metadata grouping refused: aligned exact sample labels are required.",
    };
  }
  // Axis labels are the row-identity authority. Native readers may expose
  // additional aligned metadata without redundantly materializing sample_id.
  // If a producer does supply sample_id, it must still match labels exactly.
  const sampleIds =
    table == null || values.sample_id == null ? labels : exactStrings(values.sample_id, rows);
  if (!sampleIds) {
    return {
      kind: "invalid",
      message: "Metadata grouping refused: sample_id and aligned score-row labels are required.",
    };
  }
  if (
    new Set(sampleIds).size !== rows ||
    sampleIds.some((value, index) => value !== labels[index])
  ) {
    return {
      kind: "invalid",
      message: "Metadata grouping refused: sample IDs do not exactly match score-row labels.",
    };
  }
  const columns: Record<string, string[]> = {};
  const columnLabels: Record<string, string[]> = {};
  const colorOptions: { label: string; value: string }[] = [];
  const symbolOptions: { label: string; value: string }[] = [{ label: "None", value: "__none__" }];
  const admittedColumns: Array<{ name: string; raw: unknown[]; labels?: string[] }> =
    Object.entries(values).map(([name, raw]) => ({ name, raw: Array.isArray(raw) ? raw : [] }));
  const seenClassNames = new Set<string>();
  const seenClassIndices = new Set<number>();
  for (const item of (classSets ?? []) as unknown[]) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      return {
        kind: "invalid",
        message: "Metadata grouping refused: an axis class set is malformed.",
      };
    }
    const set = item as Record<string, unknown>;
    if (
      typeof set.name !== "string" ||
      !set.name ||
      set.name.trim() !== set.name ||
      !Number.isSafeInteger(set.source_set_index) ||
      Number(set.source_set_index) < 0 ||
      seenClassNames.has(set.name) ||
      seenClassIndices.has(Number(set.source_set_index)) ||
      !Array.isArray(set.values) ||
      set.values.length !== rows ||
      set.name in values
    ) {
      return {
        kind: "invalid",
        message: "Metadata grouping refused: an axis class-set identity is malformed or ambiguous.",
      };
    }
    seenClassNames.add(set.name);
    seenClassIndices.add(Number(set.source_set_index));
    const levels = set.levels ?? [];
    if (!Array.isArray(levels)) {
      return {
        kind: "invalid",
        message: `Metadata grouping refused: ${set.name} has a malformed class-level lookup.`,
      };
    }
    const levelLabels = new Map<string, string>();
    for (const level of levels) {
      if (!level || typeof level !== "object" || Array.isArray(level)) {
        return {
          kind: "invalid",
          message: `Metadata grouping refused: ${set.name} has a malformed class level.`,
        };
      }
      const record = level as Record<string, unknown>;
      const identity = scalarIdentity(record.code);
      if (
        identity === null ||
        typeof record.label !== "string" ||
        !record.label ||
        record.label.trim() !== record.label ||
        levelLabels.has(identity)
      ) {
        return {
          kind: "invalid",
          message: `Metadata grouping refused: ${set.name} has a malformed class level.`,
        };
      }
      levelLabels.set(identity, record.label);
    }
    const raw = set.values as unknown[];
    const identities = raw.map(scalarIdentity);
    if (identities.some((value) => value === null)) {
      return {
        kind: "invalid",
        message: `Metadata grouping refused: ${set.name} contains a non-lossless class value.`,
      };
    }
    if (
      levelLabels.size &&
      identities.some((identity) => identity !== "null:null" && !levelLabels.has(identity!))
    ) {
      return {
        kind: "invalid",
        message: `Metadata grouping refused: ${set.name} contains a class absent from its level lookup.`,
      };
    }
    admittedColumns.push({
      name: set.name,
      raw,
      labels: identities.map(
        (identity, index) => levelLabels.get(identity!) ?? scalarLabel(raw[index]),
      ),
    });
  }
  for (const { name, raw, labels: declaredLabels } of admittedColumns) {
    if (!Array.isArray(raw) || raw.length !== rows) {
      return {
        kind: "invalid",
        message: `Metadata grouping refused: ${name} does not contain one value per sample.`,
      };
    }
    const identities = raw.map(scalarIdentity);
    if (identities.some((item) => item === null)) {
      return {
        kind: "invalid",
        message: `Metadata grouping refused: ${name} contains a non-lossless scalar value.`,
      };
    }
    const projected = identities as string[];
    const rawLabels = declaredLabels ?? raw.map(scalarLabel);
    const identitiesByLabel = new Map<string, Set<string>>();
    rawLabels.forEach((label, index) => {
      const seen = identitiesByLabel.get(label) ?? new Set<string>();
      seen.add(projected[index]);
      identitiesByLabel.set(label, seen);
    });
    const labels = rawLabels.map((label, index) =>
      (identitiesByLabel.get(label)?.size ?? 0) > 1
        ? `${label} (${projected[index].split(":", 1)[0]})`
        : label,
    );
    const categories = new Set(projected);
    columns[name] = projected;
    columnLabels[name] = labels;
    if (categories.size < 2 || categories.size > 20) continue;
    const label = name.replace(/_/g, " ").replace(/^./, (value: string) => value.toUpperCase());
    colorOptions.push({ label, value: name });
    if (categories.size <= BLOCK_SYMBOLS.length) symbolOptions.push({ label, value: name });
  }
  return {
    kind: "valid",
    sampleIds,
    columns,
    columnLabels,
    colorOptions,
    symbolOptions,
  };
}

export function projectMetadataStyle(
  grouping: Extract<MetadataGroupingState, { kind: "valid" }>,
  colorField: string,
  styleField: string,
): MetadataStyleProjection | null {
  const colorKey = grouping.columns[colorField] ? colorField : grouping.colorOptions[0]?.value;
  if (!colorKey || !grouping.columns[colorKey]) return null;
  const colorValues = grouping.columns[colorKey];
  const colorLabels = grouping.columnLabels[colorKey];
  const colorCategories = Array.from(new Set(colorValues));
  const useStyles = styleField !== "__none__" && Boolean(grouping.columns[styleField]);
  const styleValues = useStyles
    ? grouping.columns[styleField]
    : Array(colorValues.length).fill("style:none");
  const styleLabels = useStyles
    ? grouping.columnLabels[styleField]
    : Array(colorValues.length).fill("None");
  const styleCategories = useStyles ? Array.from(new Set(styleValues)) : [];
  return {
    colorKey,
    colorValues,
    colorLabels,
    colorCategories,
    colorMap: createCategoryColorMap(colorValues, colorCategories),
    useStyles,
    styleKey: styleField,
    styleValues,
    styleLabels,
    styleCategories,
    symbolMap: new Map(styleCategories.map((value, index) => [value, BLOCK_SYMBOLS[index]])),
  };
}

export function buildMetadataScoreTraces(
  scores: number[][],
  grouping: Extract<MetadataGroupingState, { kind: "valid" }>,
  colorField: string,
  symbolField: string,
  pcX: number,
  pcY: number,
  pcXLabel: string,
  pcYLabel: string,
): Record<string, unknown>[] {
  const style = projectMetadataStyle(grouping, colorField, symbolField);
  if (!style) return [];
  const {
    colorKey,
    colorValues,
    colorLabels,
    colorCategories,
    colorMap,
    useStyles,
    styleValues,
    styleLabels,
    styleCategories,
    symbolMap,
  } = style;
  const traces: Record<string, unknown>[] = [];
  for (const category of colorCategories) {
    const indices = colorValues
      .map((value, index) => (value === category ? index : -1))
      .filter((index) => index >= 0);
    traces.push({
      type: "scatter",
      mode: "markers",
      name: colorLabels[colorValues.indexOf(category)],
      legendgroup: `color-${colorKey}`,
      x: indices.map((index) => Number(scores[index]?.[pcX])),
      y: indices.map((index) => Number(scores[index]?.[pcY])),
      customdata: indices.map((index) => [
        grouping.sampleIds[index],
        colorLabels[index],
        styleLabels[index],
      ]),
      marker: {
        size: 10,
        color: colorMap.get(category),
        symbol: useStyles ? indices.map((index) => symbolMap.get(styleValues[index])) : "circle",
        opacity: 0.82,
        line: { width: 1, color: "rgba(15, 23, 42, 0.55)" },
      },
      hovertemplate:
        `%{customdata[0]}<br>${colorKey.replace(/_/g, " ")}: %{customdata[1]}<br>` +
        (useStyles ? `${symbolField.replace(/_/g, " ")}: %{customdata[2]}<br>` : "") +
        `${pcXLabel}: %{x:.15g}<br>${pcYLabel}: %{y:.15g}<extra></extra>`,
    });
  }
  styleCategories.forEach((symbol, index) => {
    traces.push({
      type: "scatter",
      mode: "markers",
      name: `${symbolField.replace(/_/g, " ")}: ${styleLabels[styleValues.indexOf(symbol)]}`,
      legendgroup: `symbol-${symbolField}`,
      x: [null],
      y: [null],
      marker: { size: 10, color: "#94a3b8", symbol: BLOCK_SYMBOLS[index] },
      hoverinfo: "skip",
    });
  });
  return traces;
}

const LINE_DASHES = ["solid", "dash", "dot", "dashdot", "longdash", "longdashdot"];

export function buildMetadataLineTraces(
  x: number[],
  rows: number[][],
  grouping: Extract<MetadataGroupingState, { kind: "valid" }>,
  colorField: string,
  styleField: string,
  limit = 50,
): Record<string, unknown>[] {
  const style = projectMetadataStyle(grouping, colorField, styleField);
  if (!style) return [];
  const {
    colorKey,
    colorValues,
    colorLabels,
    colorCategories,
    colorMap,
    useStyles,
    styleValues,
    styleLabels,
    styleCategories,
  } = style;
  const dashMap = new Map(styleCategories.map((value, index) => [value, LINE_DASHES[index]]));
  const traces: Record<string, unknown>[] = rows.slice(0, limit).map((row, index) => ({
    type: "scatter",
    mode: "lines",
    x,
    y: row,
    name: grouping.sampleIds[index],
    showlegend: false,
    legendgroup: `color-${colorKey}-${colorValues[index]}`,
    customdata: x.map(() => [grouping.sampleIds[index], colorLabels[index], styleLabels[index]]),
    line: {
      width: 1.5,
      color: colorMap.get(colorValues[index]),
      dash: useStyles ? dashMap.get(styleValues[index]) : "solid",
    },
    opacity: 0.82,
    hovertemplate:
      "%{customdata[0]}<br>" +
      `${colorKey.replace(/_/g, " ")}: %{customdata[1]}<br>` +
      (useStyles ? `${styleField.replace(/_/g, " ")}: %{customdata[2]}<br>` : "") +
      "X: %{x}<br>Value: %{y:.15g}<extra></extra>",
  }));
  colorCategories.forEach((category) => {
    traces.push({
      type: "scatter",
      mode: "lines",
      name: `${colorKey.replace(/_/g, " ")}: ${colorLabels[colorValues.indexOf(category)]}`,
      legendgroup: `color-${colorKey}`,
      x: [null],
      y: [null],
      line: { width: 2, color: colorMap.get(category) },
      hoverinfo: "skip",
    });
  });
  styleCategories.forEach((category) => {
    traces.push({
      type: "scatter",
      mode: "lines",
      name: `${styleField.replace(/_/g, " ")}: ${styleLabels[styleValues.indexOf(category)]}`,
      legendgroup: `style-${styleField}`,
      x: [null],
      y: [null],
      line: { width: 2, color: "#94a3b8", dash: dashMap.get(category) },
      hoverinfo: "skip",
    });
  });
  return traces;
}
