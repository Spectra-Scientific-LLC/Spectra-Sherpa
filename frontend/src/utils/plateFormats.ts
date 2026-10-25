import registryWire from "../../../src/spectra_sherpa/data/plate_formats_v1.json";

export interface PlateFormat {
  id: string;
  label: string;
  rows: readonly string[];
  columns: number;
  capacity: number;
}

interface PlateFormatWire {
  id: string;
  label: string;
  rows: string[];
  columns: number;
}

const registry = registryWire as {
  schema_version: string;
  default_format_id: string;
  formats: PlateFormatWire[];
};

if (registry.schema_version !== "spectrasherpa.plate-formats/1") {
  throw new Error("Plate-format registry schema is unsupported");
}

export const plateFormats: readonly PlateFormat[] = Object.freeze(
  registry.formats.map((format) =>
    Object.freeze({
      ...format,
      rows: Object.freeze([...format.rows]),
      capacity: format.rows.length * format.columns,
    }),
  ),
);

export const defaultPlateFormatId = registry.default_format_id;

export function getPlateFormat(formatId: string = defaultPlateFormatId): PlateFormat {
  const format = plateFormats.find((candidate) => candidate.id === formatId);
  if (!format) throw new Error(`Unknown plate format '${formatId}'`);
  return format;
}

export function formatWell(format: PlateFormat, row: number, column: number): string {
  return `${format.rows[row]}${String(column + 1).padStart(2, "0")}`;
}

// Syntax is checked once per distinct coordinate, independently of geometry.
function wellCoordinate(value: string): { row: string; column: number } | null {
  const match = /^([A-Z]+)([0-9]+)$/.exec(value.trim().toUpperCase());
  const column = match ? Number.parseInt(match[2], 10) - 1 : -1;
  return match && column >= 0 && match[2] === String(column + 1).padStart(2, "0")
    ? { row: match[1], column }
    : null;
}

/** Shared admission for measured assignments and planned/retained match wells. */
export function plateWellFormatAdmissions(
  wells: readonly string[],
  formats: readonly PlateFormat[] = plateFormats,
) {
  const coordinates = [...new Set(wells)].filter(value => value.trim()).map(value => ({
    value, coordinate: wellCoordinate(value),
  }));
  return formats.map(format => {
    const invalid = coordinates.find(({ coordinate }) => !coordinate
      || !format.rows.includes(coordinate.row) || coordinate.column >= format.columns);
    return {
      format,
      error: invalid
        ? `Well ${invalid.value} is outside ${format.label}. Reassign or clear it before changing format.`
        : null,
    };
  });
}

export function parsePlateWell(
  value: string,
  format: PlateFormat,
): { row: number; column: number } {
  const coordinate = wellCoordinate(value);
  const row = coordinate ? format.rows.indexOf(coordinate.row) : -1;
  const column = coordinate?.column ?? -1;
  if (
    !coordinate ||
    row < 0 ||
    column < 0 ||
    column >= format.columns
  ) {
    throw new Error(
      `Well '${value}' is outside ${format.label} (${formatWell(format, 0, 0)} through ${formatWell(format, format.rows.length - 1, format.columns - 1)}).`,
    );
  }
  return { row, column };
}
