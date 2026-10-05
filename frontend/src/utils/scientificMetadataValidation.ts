/** Numeric fields exposed by the Inspector's source metadata editor. */
export const numericMetadataFields = [
  { group: "conditions", name: "temperature_c" },
  { group: "conditions", name: "pressure_atm" },
  { group: "conditions", name: "ambient_humidity_percent", min: 0, max: 100 },
  { group: "acquisition", name: "resolution_cm" },
  { group: "acquisition", name: "n_scans", min: 1, integer: true },
  { group: "acquisition", name: "wavenumber_min" },
  { group: "acquisition", name: "wavenumber_max" },
  { group: "cell", name: "pathlength_mm" },
  { group: "cell", name: "cell_volume_ml" },
] as const;

export function validateScientificMetadata(
  metadata: unknown,
): Array<{ param_name: string; message: string }> {
  const errors: Array<{ param_name: string; message: string }> = [];
  if (!metadata || typeof metadata !== "object") return errors;
  for (const field of numericMetadataFields) {
    const group = (metadata as Record<string, unknown>)[field.group];
    if (!group || typeof group !== "object") continue;
    const value = (group as Record<string, unknown>)[field.name];
    if (value == null || value === "") continue;
    const param_name = `metadata.${field.group}.${field.name}`;
    if (typeof value !== "number" || !Number.isFinite(value)) {
      errors.push({ param_name, message: `${field.name} must be a finite number` });
    } else if ("integer" in field && !Number.isInteger(value)) {
      errors.push({ param_name, message: `${field.name} must be a whole number` });
    } else if ("min" in field && value < field.min) {
      errors.push({ param_name, message: `${field.name} must be ≥ ${field.min}` });
    } else if ("max" in field && value > field.max) {
      errors.push({ param_name, message: `${field.name} must be ≤ ${field.max}` });
    }
  }
  return errors;
}
