type RecordValue = Record<string, unknown>;

const FIELDS: ReadonlyArray<[string, string]> = [
  ["scan_count", "sample scans"],
  ["background_scan_count", "background scans"],
  ["point_count", "spectral points"],
  ["first_x", "range start"],
  ["last_x", "range end"],
  ["x_code", "spectral axis"],
  ["y_code", "signal type"],
  ["reference_frequency_cm-1", "reference frequency"],
  ["optical_velocity", "optical velocity"],
];

function record(value: unknown): RecordValue | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as RecordValue
    : null;
}

export function acquisitionVarianceWarning(sourceMembers: unknown): string | null {
  if (!Array.isArray(sourceMembers) || sourceMembers.length < 2) return null;
  const acquisitions = sourceMembers
    .map((member) => record(record(member)?.metadata)?.["omnic.acquisition"])
    .map(record)
    .filter((item): item is RecordValue => item !== null);
  if (acquisitions.length < 2) return null;
  const differences = FIELDS.flatMap(([field, label]) => {
    const values = acquisitions
      .map((item) => item[field])
      .filter((value) => typeof value === "string" || typeof value === "number")
      .map(String);
    return values.length >= 2 && new Set(values).size > 1 ? [label] : [];
  });
  return differences.length
    ? `Acquisition settings differ across files: ${differences.join(", ")}. Review before modeling.`
    : null;
}
