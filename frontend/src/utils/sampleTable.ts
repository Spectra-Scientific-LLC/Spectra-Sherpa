import {
  defaultPlateFormatId,
  formatWell,
  getPlateFormat,
  parsePlateWell,
} from "@/utils/plateFormats";
import type { AcquisitionPlan } from "@/types";

export type SampleTargetType = "continuous" | "categorical";
export type PlateTraversalDirection = "rows" | "columns";

export interface SampleTargetDefinition {
  name: string;
  type: SampleTargetType;
}

export interface SampleTableRow {
  row_index: number;
  source_file_id: number;
  sample_id: string;
  include: boolean;
  targets: Record<string, string>;
  plate_id: string;
  well: string;
  annotations: Record<string, string>;
}

export interface PlateAssignmentOptions {
  formatId?: string;
  startWell: string;
  endWell: string;
  direction: PlateTraversalDirection;
  serpentine: boolean;
}

export interface SampleTableValidation {
  valid: boolean;
  errors: string[];
}

export interface AcquisitionPlanComparison {
  planned: number;
  assigned: number;
  matched: number;
  unmeasured: number;
  outsidePlan: number;
}

export interface AcquisitionPlanDifference {
  rowIndex: number;
  field: "sample_id" | "well" | "annotations";
  before: string;
  after: string;
}

export interface AcquisitionPlanProposal {
  rows: SampleTableRow[];
  differences: AcquisitionPlanDifference[];
  status: AcquisitionPlanComparison;
}

export const SAMPLE_TABLE_SCHEMA_COLUMN = "target_schema";

const RESERVED_COLUMNS = new Set([
  "row_index",
  "source_file_id",
  "sample_id",
  "include",
  SAMPLE_TABLE_SCHEMA_COLUMN,
  "plate_id",
  "well",
  "plate_format",
]);

export function normalizeAnnotationColumnName(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export function createSampleTableRows(
  sampleCount: number,
  sourceFileId: number,
  labels: readonly string[] = [],
  targetNames: readonly string[] = ["target"],
): SampleTableRow[] {
  return Array.from({ length: sampleCount }, (_, index) => ({
    row_index: index,
    source_file_id: sourceFileId,
    sample_id: labels[index]?.trim() || `sample-${String(index + 1).padStart(4, "0")}`,
    include: true,
    targets: Object.fromEntries(targetNames.map((name) => [name, ""])),
    plate_id: "",
    well: "",
    annotations: {},
  }));
}

export function wellForOrdinal(ordinal: number, formatId = defaultPlateFormatId): string {
  const format = getPlateFormat(formatId);
  if (!Number.isInteger(ordinal) || ordinal < 0 || ordinal >= format.capacity) {
    throw new Error(
      `${format.label} ordinal must be an integer from 0 through ${format.capacity - 1}`,
    );
  }
  return formatWell(format, Math.floor(ordinal / format.columns), ordinal % format.columns);
}

export function wellsForRectangle(options: PlateAssignmentOptions): string[] {
  const format = getPlateFormat(options.formatId);
  const start = parsePlateWell(options.startWell, format);
  const end = parsePlateWell(options.endWell, format);
  if (start.row > end.row || start.column > end.column) {
    throw new Error("Start must be the upper-left corner and End the lower-right corner.");
  }

  const wells: string[] = [];
  if (options.direction === "rows") {
    for (let row = start.row; row <= end.row; row += 1) {
      const columns = Array.from(
        { length: end.column - start.column + 1 },
        (_, index) => start.column + index,
      );
      if (options.serpentine && (row - start.row) % 2 === 1) columns.reverse();
      for (const column of columns) {
        wells.push(formatWell(format, row, column));
      }
    }
  } else {
    for (let column = start.column; column <= end.column; column += 1) {
      const rows = Array.from({ length: end.row - start.row + 1 }, (_, index) => start.row + index);
      if (options.serpentine && (column - start.column) % 2 === 1) rows.reverse();
      for (const row of rows) {
        wells.push(formatWell(format, row, column));
      }
    }
  }
  return wells;
}

export function assignPlateCoordinates(
  rows: SampleTableRow[],
  options: PlateAssignmentOptions,
): void {
  const wells = wellsForRectangle(options);
  if (wells.length === 0) throw new Error("The selected plate region contains no wells.");
  rows.forEach((row, index) => {
    row.plate_id = `plate-${Math.floor(index / wells.length) + 1}`;
    row.well = wells[index % wells.length];
  });
}

export function assignSequential96WellCoordinates(rows: SampleTableRow[]): void {
  const format = getPlateFormat();
  assignPlateCoordinates(rows, {
    formatId: format.id,
    startWell: "A01",
    endWell: formatWell(format, format.rows.length - 1, format.columns - 1),
    direction: "rows",
    serpentine: false,
  });
}

export function compareAcquisitionPlan(
  rows: readonly SampleTableRow[],
  plannedWells: readonly string[],
): AcquisitionPlanComparison {
  const format = getPlateFormat();
  const normalizeWell = (well: string): string => {
    const coordinate = parsePlateWell(well, format);
    return formatWell(format, coordinate.row, coordinate.column);
  };
  const planned = new Set(plannedWells.map(normalizeWell));
  const assigned = rows
    .filter((row) => row.plate_id.trim() && row.well.trim())
    .map((row) => {
      try {
        return { plateId: row.plate_id.trim(), well: normalizeWell(row.well) };
      } catch {
        return { plateId: row.plate_id.trim(), well: null };
      }
    });
  const matched = assigned.filter(
    ({ plateId, well }) => plateId === "plate-1" && well !== null && planned.has(well),
  ).length;
  return {
    planned: planned.size,
    assigned: assigned.length,
    matched,
    unmeasured: Math.max(0, planned.size - matched),
    outsidePlan: assigned.length - matched,
  };
}

export function applyAcquisitionPlan(
  rows: SampleTableRow[],
  plannedWells: readonly string[],
): void {
  if (plannedWells.length !== rows.length) {
    throw new Error(
      `Exact assignment requires one planned well for each measured row (${plannedWells.length} planned, ${rows.length} measured).`,
    );
  }
  const format = getPlateFormat();
  const normalized = plannedWells.map((well) => {
    const coordinate = parsePlateWell(well, format);
    return formatWell(format, coordinate.row, coordinate.column);
  });
  if (new Set(normalized).size !== normalized.length) {
    throw new Error("The acquisition plan contains duplicate wells.");
  }
  rows.forEach((row, index) => {
    row.plate_id = "plate-1";
    row.well = normalized[index];
  });
}

export function proposeMeasuredSamples(
  rows: readonly SampleTableRow[],
  plan: AcquisitionPlan,
): AcquisitionPlanProposal {
  const proposed = rows.map((row) => ({
    ...row,
    targets: { ...row.targets },
    annotations: { ...row.annotations },
  }));
  const orderedMatches = [...plan.matching.matches].sort(
    (left, right) => left.sequence_order - right.sequence_order,
  );
  const wellByPosition = new Map(plan.wells.map((well) => [well.well_position, well]));
  const differences: AcquisitionPlanDifference[] = [];
  proposed.forEach((row, index) => {
    const match = orderedMatches[index];
    const plannedWell = match?.well_position
      ? wellByPosition.get(match.well_position)
      : plan.wells[index];
    const nextWell = match?.well_position || plannedWell?.well_position || "";
    const nextSample = match?.sample_id || plannedWell?.sample_id || row.sample_id;
    const factorValues = {
      ...(plannedWell?.factor_values ?? {}),
      ...(match?.factor_values ?? {}),
    };
    if (nextWell && (row.plate_id !== "plate-1" || row.well !== nextWell)) {
      differences.push({
        rowIndex: row.row_index,
        field: "well",
        before: row.plate_id && row.well ? `${row.plate_id}:${row.well}` : "unassigned",
        after: `plate-1:${nextWell}`,
      });
      row.plate_id = "plate-1";
      row.well = nextWell;
    }
    if (nextSample !== row.sample_id) {
      differences.push({
        rowIndex: row.row_index,
        field: "sample_id",
        before: row.sample_id,
        after: nextSample,
      });
      row.sample_id = nextSample;
    }
    for (const [name, value] of Object.entries(factorValues)) {
      const column = normalizeAnnotationColumnName(name);
      const nextValue = value == null ? "" : String(value);
      if (column && row.annotations[column] !== nextValue) {
        differences.push({
          rowIndex: row.row_index,
          field: "annotations",
          before: row.annotations[column] || "",
          after: `${column}=${nextValue}`,
        });
        row.annotations[column] = nextValue;
      }
    }
  });
  return {
    rows: proposed,
    differences,
    status: compareAcquisitionPlan(
      proposed,
      plan.wells.map((well) => well.well_position),
    ),
  };
}

function normalizedTargets(targets: readonly SampleTargetDefinition[]): SampleTargetDefinition[] {
  return targets.map((target) => ({
    name: normalizeAnnotationColumnName(target.name),
    type: target.type,
  }));
}

export function validateSampleTable(
  rows: readonly SampleTableRow[],
  targets: readonly SampleTargetDefinition[],
  selectedTarget: string,
  annotationColumns: readonly string[],
  plateFormatId = defaultPlateFormatId,
): SampleTableValidation {
  const errors: string[] = [];
  const definitions = normalizedTargets(targets);
  const targetNames = definitions.map((target) => target.name);
  const selectedName = normalizeAnnotationColumnName(selectedTarget);
  if (definitions.length === 0) errors.push("At least one target column is required.");
  if (targetNames.some((name) => !name)) errors.push("Every target column requires a name.");
  if (new Set(targetNames).size !== targetNames.length) {
    errors.push("Target column names must be unique.");
  }
  for (const name of targetNames) {
    if (RESERVED_COLUMNS.has(name)) {
      errors.push(`Target column '${name}' conflicts with a structural column.`);
    }
  }
  const selected = definitions.find((target) => target.name === selectedName);
  if (!selected) errors.push("Select one defined target before saving.");

  const normalizedAnnotations = annotationColumns.map(normalizeAnnotationColumnName);
  const allNames = [...targetNames, ...normalizedAnnotations].filter(Boolean);
  if (new Set(allNames).size !== allNames.length) {
    errors.push("Target and annotation column names must be unique.");
  }
  for (const name of normalizedAnnotations) {
    if (RESERVED_COLUMNS.has(name)) {
      errors.push(`Annotation column '${name}' conflicts with a structural column.`);
    }
  }

  const sampleIds = rows.map((row) => row.sample_id.trim());
  if (sampleIds.some((value) => !value)) errors.push("Every row requires a sample ID.");
  if (new Set(sampleIds).size !== sampleIds.length) errors.push("Sample IDs must be unique.");
  if (!rows.some((row) => row.include)) errors.push("At least one sample must be included.");

  const occupiedWells = new Map<string, number>();
  const plateFormat = getPlateFormat(plateFormatId);
  for (const row of rows) {
    const plateId = row.plate_id.trim();
    const well = row.well.trim().toUpperCase();
    if (well) {
      try {
        parsePlateWell(well, plateFormat);
      } catch (error: unknown) {
        errors.push(
          `Row ${row.row_index + 1} has invalid well '${row.well}'. ${error instanceof Error ? error.message : "Unknown plate coordinate."}`,
        );
        break;
      }
    }
    if (well && !plateId) {
      errors.push(`Row ${row.row_index + 1} has a well but no plate ID.`);
      break;
    }
    if (well) {
      const coordinate = `${plateId}\u0000${well}`;
      const previousRow = occupiedWells.get(coordinate);
      if (previousRow !== undefined) {
        errors.push(
          `Rows ${previousRow + 1} and ${row.row_index + 1} both assign ${plateId}/${well}. ` +
            "Each physical well may contain only one sample.",
        );
        break;
      }
      occupiedWells.set(coordinate, row.row_index);
    }
    if (!row.include || !selected) continue;
    const value = row.targets[selected.name]?.trim() ?? "";
    if (!value) {
      errors.push(`Included sample '${row.sample_id}' requires a ${selected.name} value.`);
      break;
    }
    if (selected.type === "continuous" && !Number.isFinite(Number(value))) {
      errors.push(`Continuous target ${selected.name} for '${row.sample_id}' must be numeric.`);
      break;
    }
  }
  return { valid: errors.length === 0, errors };
}

function csvCell(value: unknown): string {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function serializeSampleTableCsv(
  rows: readonly SampleTableRow[],
  targets: readonly SampleTargetDefinition[],
  annotationColumns: readonly string[],
  plateFormatId = defaultPlateFormatId,
): string {
  const plateFormat = getPlateFormat(plateFormatId);
  const definitions = normalizedTargets(targets);
  const annotationNames = annotationColumns.map(normalizeAnnotationColumnName).filter(Boolean);
  const targetSchema = JSON.stringify(
    Object.fromEntries(definitions.map((target) => [target.name, target.type])),
  );
  const header = [
    "row_index",
    "source_file_id",
    "sample_id",
    "include",
    SAMPLE_TABLE_SCHEMA_COLUMN,
    ...definitions.map((target) => target.name),
    "plate_format",
    "plate_id",
    "well",
    ...annotationNames,
  ];
  const lines = rows.map((row) =>
    [
      row.row_index,
      row.source_file_id,
      row.sample_id,
      row.include ? "true" : "false",
      targetSchema,
      ...definitions.map((target) => row.targets[target.name] ?? ""),
      plateFormat.id,
      row.plate_id,
      row.well.toUpperCase(),
      ...annotationNames.map((name) => row.annotations[name] ?? ""),
    ]
      .map(csvCell)
      .join(","),
  );
  return `${header.map(csvCell).join(",")}\n${lines.join("\n")}\n`;
}

export function isReservedSampleTableColumn(value: string): boolean {
  return RESERVED_COLUMNS.has(normalizeAnnotationColumnName(value));
}
