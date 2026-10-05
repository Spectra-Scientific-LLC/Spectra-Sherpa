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

export function parsePlateWell(
  value: string,
  format: PlateFormat,
): { row: number; column: number } {
  const normalized = value.trim().toUpperCase();
  const match = /^([A-Z]+)([0-9]+)$/.exec(normalized);
  const row = match ? format.rows.indexOf(match[1]) : -1;
  const column = match ? Number.parseInt(match[2], 10) - 1 : -1;
  if (
    !match ||
    row < 0 ||
    column < 0 ||
    column >= format.columns ||
    match[2] !== String(column + 1).padStart(2, "0")
  ) {
    throw new Error(
      `Well '${value}' is outside ${format.label} (${formatWell(format, 0, 0)} through ${formatWell(format, format.rows.length - 1, format.columns - 1)}).`,
    );
  }
  return { row, column };
}
