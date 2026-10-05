import type { DatasetPlotMember, DatasetPlotSource, SherpaDatasetDict } from "@/types";

const LINE_DASHES = ["solid", "dash", "dot", "dashdot", "longdash", "longdashdot"];
const TRACE_COLORS = [
  "#2563eb",
  "#dc2626",
  "#16a34a",
  "#d97706",
  "#7c3aed",
  "#db2777",
  "#0891b2",
  "#ea580c",
  "#0f766e",
  "#4f46e5",
  "#be123c",
  "#65a30d",
  "#0284c7",
  "#c026d3",
  "#4d7c0f",
  "#0d9488",
  "#c2410c",
  "#6366f1",
  "#e11d48",
  "#059669",
];

export interface MultiDatasetOverlayResult {
  traces: Record<string, unknown>[];
  error: string | null;
  displayedSpectra: number;
  totalSpectra: number;
  xAxisTitle: string;
  yAxisTitle: string;
}

export interface ActivePlotCurve {
  experimentId: number;
  fileName: string;
}

interface AdmittedPlotSource {
  source: DatasetPlotSource;
  member: DatasetPlotMember;
  rows: Array<Array<number | null>>;
  x: number[];
  labels: string[];
  fileNames: string[];
  colorIdentities: string[];
  colorIdentityAuthority: "specimen_id" | "sample_label";
  xTitle: string;
  xUnits: string;
  xQuantity: string;
  yTitle: string;
  yUnits: string;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function nonemptyString(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function exactFileName(value: unknown): string {
  const path = nonemptyString(value);
  if (!path) return "";
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] ?? "";
}

/**
 * Project the collection's row-aligned source authority onto plotted spectra.
 * Collection assembly preserves source_member_metadata in the same order used
 * to concatenate sample labels and rows. We use it only when it is exactly
 * one-to-one with those rows; otherwise the already exact single-member name
 * remains the conservative fallback.
 */
export function alignedSourceFileNames(
  dataset: SherpaDatasetDict,
  rows: number,
  fallback: string,
): string[] {
  const metadata = record(dataset.metadata);
  const members = metadata?.source_member_metadata;
  if (Array.isArray(members) && members.length === rows) {
    const projected = members.map((value) => {
      const member = record(value);
      const memberMetadata = record(member?.metadata);
      return exactFileName(memberMetadata?.source_file) || exactFileName(member?.file_name);
    });
    if (projected.every(Boolean)) return projected;
  }
  const collection = record(metadata?.source_collection);
  const files = collection?.files;
  if (Array.isArray(files) && files.length === 1) {
    const fileName = exactFileName(record(files[0])?.file_name);
    if (fileName) return Array.from({ length: rows }, () => fileName);
  }
  return Array.from({ length: rows }, () => exactFileName(fallback) || fallback);
}

export interface AlignedSpectrumIdentity {
  sampleLabel: string;
  fileName: string;
}

/** Keep the visible sample label and its exact source file on one projection path. */
export function alignedSpectrumIdentities(
  dataset: SherpaDatasetDict,
  rows: number,
  fallbackFileName: string,
): AlignedSpectrumIdentity[] {
  const labels = alignedLabels(dataset, rows);
  const fileNames = alignedSourceFileNames(dataset, rows, fallbackFileName);
  return labels.map((sampleLabel, index) => ({
    sampleLabel,
    fileName: fileNames[index],
  }));
}

/** A local filter is allowed only when every retained row has an exact source. */
export function selectedDatasetRows(
  dataset: SherpaDatasetDict,
  fileNames: string[],
): number[] | null {
  if (!Array.isArray(dataset.data) || dataset.data.length !== dataset.n_samples) return null;
  const identities = alignedSourceFileNames(dataset, dataset.data.length, "");
  if (identities.some((name) => !name)) return null;
  const selected = new Set(fileNames.map(exactFileName));
  if (selected.size !== fileNames.length) return null;
  if ([...selected].some((name) => !identities.includes(name))) return null;
  return identities.flatMap((name, index) => (selected.has(name) ? [index] : []));
}

function normalizedScientificTerm(value: string): string {
  return value
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[⁻−–—]/g, "-")
    .replace(/¹/g, "1")
    .replace(/μ/g, "u")
    .replace(/[^a-z0-9%/.-]+/g, "")
    .replace(/^1\/cm$/, "cm-1");
}

function exactNumericAxis(dataset: SherpaDatasetDict): number[] | null {
  const axis = dataset.x_axis?.data;
  if (
    Array.isArray(axis) &&
    axis.length === dataset.n_features &&
    axis.every((value) => typeof value === "number" && Number.isFinite(value))
  ) {
    return [...axis];
  }
  const metadata = record(dataset.metadata);
  const wavenumbers = metadata?.wavenumbers;
  if (
    Array.isArray(wavenumbers) &&
    wavenumbers.length === dataset.n_features &&
    wavenumbers.every((value) => typeof value === "number" && Number.isFinite(value))
  ) {
    return [...wavenumbers] as number[];
  }
  return null;
}

function alignedLabels(dataset: SherpaDatasetDict, rows: number): string[] {
  const labels = dataset.y_axis?.labels;
  if (Array.isArray(labels) && labels.length >= rows) {
    return labels
      .slice(0, rows)
      .map((value, index) =>
        typeof value === "string" && value.trim() ? value : `Spectrum ${index + 1}`,
      );
  }
  return Array.from({ length: rows }, (_, index) => `Spectrum ${index + 1}`);
}

interface ColorIdentityProjection {
  identities: string[];
  authority: "specimen_id" | "sample_label";
  error: string | null;
}

function alignedColorIdentities(
  dataset: SherpaDatasetDict,
  labels: string[],
): ColorIdentityProjection {
  const table = record(dataset.y_axis?.sample_table);
  const specimenIds = table?.specimen_id;
  if (specimenIds === undefined) {
    return { identities: labels, authority: "sample_label", error: null };
  }
  if (!Array.isArray(specimenIds) || specimenIds.length !== labels.length) {
    return {
      identities: [],
      authority: "specimen_id",
      error: `declares specimen_id without exactly ${labels.length} row-aligned values.`,
    };
  }
  const invalidIndex = specimenIds.findIndex(
    (value) =>
      !(
        (typeof value === "string" && value.trim().length > 0) ||
        (typeof value === "number" && Number.isFinite(value))
      ),
  );
  if (invalidIndex >= 0) {
    return {
      identities: [],
      authority: "specimen_id",
      error: `declares a blank or invalid specimen_id at plotted row ${invalidIndex + 1}.`,
    };
  }
  return {
    identities: specimenIds.map((value) =>
      typeof value === "string" ? value.trim() : String(value),
    ),
    authority: "specimen_id",
    error: null,
  };
}

function admitSource(
  source: DatasetPlotSource,
  member: DatasetPlotMember,
): AdmittedPlotSource | string {
  const dataset = member.dataset;
  const sourceName =
    source.selectedFileCount === source.totalFileCount
      ? source.name
      : `${source.name} · ${member.fileName}`;
  const metadata = record(dataset.metadata);
  const declaredSpectra =
    dataset.data_role === "X_spectra" ||
    metadata?.data_role === "X_spectra" ||
    metadata?.is_spectra === true;
  if (!declaredSpectra) {
    return `${sourceName} is not declared as spectral data.`;
  }
  const rank = dataset.ndim ?? dataset.shape?.length ?? 2;
  if (rank !== 2 || !Array.isArray(dataset.data) || dataset.data.length === 0) {
    return `${sourceName} is not an inspectable two-dimensional spectral matrix.`;
  }
  const x = exactNumericAxis(dataset);
  if (!x) {
    return `${sourceName} has no complete finite feature axis for spectral overlay.`;
  }
  const rows: Array<Array<number | null>> = [];
  for (const rawRow of dataset.data) {
    if (
      !Array.isArray(rawRow) ||
      rawRow.length !== x.length ||
      !rawRow.every(
        (value) => value === null || (typeof value === "number" && Number.isFinite(value)),
      )
    ) {
      return `${sourceName} contains a row that cannot be represented faithfully in the overlay.`;
    }
    rows.push(rawRow as Array<number | null>);
  }
  const domain = record(dataset.domain);
  const identities = alignedSpectrumIdentities(dataset, rows.length, member.fileName);
  const labels = identities.map(({ sampleLabel }) => sampleLabel);
  const fileNames = identities.map(({ fileName }) => fileName);
  const colorIdentityProjection = alignedColorIdentities(dataset, labels);
  if (colorIdentityProjection.error) {
    return `${sourceName} ${colorIdentityProjection.error}`;
  }
  const xTitle =
    nonemptyString(dataset.x_axis?.title) || nonemptyString(metadata?.x_title) || "Feature";
  const xUnits = nonemptyString(dataset.x_axis?.units) || nonemptyString(metadata?.x_units);
  const xQuantity = nonemptyString(dataset.x_axis?.quantity);
  const yTitle =
    nonemptyString(domain?.data_quantity) ||
    nonemptyString(metadata?.data_quantity) ||
    nonemptyString(metadata?.y_title);
  const yUnits = nonemptyString(dataset.units) || nonemptyString(metadata?.value_units);
  const selectedIndexes = source.selectedFileNames
    ? selectedDatasetRows(dataset, source.selectedFileNames)
    : null;
  if (source.selectedFileNames && selectedIndexes === null) {
    return `${sourceName} has no exact row-to-file projection for this selection.`;
  }
  const selected = <T>(values: T[]): T[] =>
    selectedIndexes ? selectedIndexes.map((i) => values[i]) : values;
  return {
    source,
    member,
    rows: selected(rows),
    x,
    labels: selected(labels),
    fileNames: selected(fileNames),
    colorIdentities: selected(colorIdentityProjection.identities),
    colorIdentityAuthority: colorIdentityProjection.authority,
    xTitle,
    xUnits,
    xQuantity,
    yTitle,
    yUnits,
  };
}

function compatibleAxisQuantity(sources: AdmittedPlotSource[]): string | null {
  if (!sources.some((source) => source.xQuantity)) return null;
  const identities = new Set(sources.map((source) => source.xQuantity || "undeclared"));
  if (identities.size <= 1) return null;
  const detail = sources
    .map((source) => {
      const sourceName =
        source.source.members.length > 1
          ? `${source.source.name} · ${source.member.fileName}`
          : source.source.name;
      return `${sourceName}: ${source.xQuantity || "undeclared"}`;
    })
    .join("; ");
  return `Selected datasets declare incompatible feature-axis quantities (${detail}).`;
}

function compatibleAuthority(
  sources: AdmittedPlotSource[],
  field: "xTitle" | "xUnits" | "yTitle" | "yUnits",
  label: string,
): string | null {
  const declared = sources
    .map((source) => ({
      source:
        source.source.members.length > 1
          ? `${source.source.name} · ${source.member.fileName}`
          : source.source.name,
      value: source[field],
    }))
    .filter((item) => item.value);
  const identities = new Map<string, Array<{ source: string; value: string }>>();
  for (const item of declared) {
    const identity = normalizedScientificTerm(item.value);
    identities.set(identity, [...(identities.get(identity) ?? []), item]);
  }
  if (identities.size <= 1) return null;
  const detail = declared.map((item) => `${item.source}: ${item.value}`).join("; ");
  return `Selected datasets declare incompatible ${label} (${detail}).`;
}

function displayAxisTitle(title: string, units: string): string {
  if (title && units && normalizedScientificTerm(title) === normalizedScientificTerm(units)) {
    return title;
  }
  if (title && units) return `${title} (${units})`;
  return title || units;
}

export function buildMultiDatasetOverlay(
  sources: DatasetPlotSource[],
  traceLimit = 50,
  activeCurve: ActivePlotCurve | null = null,
): MultiDatasetOverlayResult {
  if (sources.length === 0) {
    return {
      traces: [],
      error: null,
      displayedSpectra: 0,
      totalSpectra: 0,
      xAxisTitle: "",
      yAxisTitle: "",
    };
  }
  const admitted: AdmittedPlotSource[] = [];
  for (const source of sources) {
    for (const member of source.members) {
      const result = admitSource(source, member);
      if (typeof result === "string") {
        return {
          traces: [],
          error: result,
          displayedSpectra: 0,
          totalSpectra: 0,
          xAxisTitle: "",
          yAxisTitle: "",
        };
      }
      admitted.push(result);
    }
  }
  if (admitted.length === 0) {
    return {
      traces: [],
      error: "The selected datasets contain no inspectable spectra.",
      displayedSpectra: 0,
      totalSpectra: 0,
      xAxisTitle: "",
      yAxisTitle: "",
    };
  }
  const quantityError = compatibleAxisQuantity(admitted);
  if (quantityError) {
    return {
      traces: [],
      error: quantityError,
      displayedSpectra: 0,
      totalSpectra: admitted.reduce(
        (total, source) => total + Number(source.member.dataset.n_samples || source.rows.length),
        0,
      ),
      xAxisTitle: "",
      yAxisTitle: "",
    };
  }
  for (const [field, label] of [
    ["xTitle", "feature-axis quantities"],
    ["xUnits", "feature-axis units"],
    ["yTitle", "ordinate quantities"],
    ["yUnits", "ordinate units"],
  ] as const) {
    const error = compatibleAuthority(admitted, field, label);
    if (error) {
      return {
        traces: [],
        error,
        displayedSpectra: 0,
        totalSpectra: admitted.reduce(
          (total, source) => total + Number(source.member.dataset.n_samples || source.rows.length),
          0,
        ),
        xAxisTitle: "",
        yAxisTitle: "",
      };
    }
  }

  const identityColors = new Map<string, string>();
  const traces: Record<string, unknown>[] = [];
  let displayedSpectra = 0;
  const boundedLimit = Math.max(1, Math.min(Math.trunc(traceLimit), 50));
  // Share the display budget so the first large source cannot hide later sources.
  const rowBudgets = admitted.map(() => 0);
  let remainingBudget = boundedLimit;
  while (remainingBudget > 0) {
    let allocated = false;
    for (const [index, source] of admitted.entries()) {
      if (rowBudgets[index] >= source.rows.length) continue;
      rowBudgets[index] += 1;
      remainingBudget -= 1;
      allocated = true;
      if (remainingBudget === 0) break;
    }
    if (!allocated) break;
  }
  for (const [admittedIndex, admittedSource] of admitted.entries()) {
    const sourceIndex = sources.findIndex(
      (candidate) => candidate.experimentId === admittedSource.source.experimentId,
    );
    const dash = LINE_DASHES[Math.max(0, sourceIndex) % LINE_DASHES.length];
    for (const [rowIndex, row] of admittedSource.rows.entries()) {
      if (rowIndex >= rowBudgets[admittedIndex]) break;
      const label = admittedSource.labels[rowIndex];
      const fileName = admittedSource.fileNames[rowIndex];
      const colorIdentity = admittedSource.colorIdentities[rowIndex];
      // Only declared specimen IDs establish cross-dataset color identity.
      const colorKey = admittedSource.colorIdentityAuthority === "specimen_id"
        ? `specimen:${colorIdentity}`
        : `dataset:${admittedSource.source.experimentId}:sample:${colorIdentity}`;
      const active =
        activeCurve?.experimentId === admittedSource.source.experimentId &&
        exactFileName(activeCurve.fileName) === fileName;
      if (!identityColors.has(colorKey)) {
        identityColors.set(colorKey, TRACE_COLORS[identityColors.size % TRACE_COLORS.length]);
      }
      traces.push({
        type: "scatter",
        mode: "lines",
        x: admittedSource.x,
        y: row,
        name: label,
        showlegend: false,
        legendgroup: `dataset-${admittedSource.source.experimentId}`,
        customdata: admittedSource.x.map(() => [
          label,
          admittedSource.source.name,
          fileName,
          colorIdentity,
        ]),
        line: {
          width: active ? 3.2 : 1.4,
          color: identityColors.get(colorKey),
          dash,
        },
        opacity: 0.84,
        hovertemplate:
          "<b>%{customdata[0]}</b><br>Dataset: %{customdata[1]}<br>" +
          "Filename: %{customdata[2]}<br>Sample identity: %{customdata[3]}<br>" +
          "X: %{x}<br>Value: %{y:.15g}<extra></extra>",
      });
      displayedSpectra += 1;
    }
  }
  const first = admitted[0];
  return {
    traces,
    error: null,
    displayedSpectra,
    totalSpectra: admitted.reduce((total, source) => total + source.rows.length, 0),
    xAxisTitle: displayAxisTitle(first.xTitle, first.xUnits),
    yAxisTitle: displayAxisTitle(first.yTitle, first.yUnits),
  };
}
