import type { ReferenceValueEvidence } from "@/types";

/** Accept only a complete, bounded server-retained reference summary for display. */
export function readReferenceEvidence(value: unknown): ReferenceValueEvidence | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (record.schema_version !== "spectrasherpa.reference-value-evidence/1"
    || typeof record.target_name !== "string"
    || !["continuous", "categorical"].includes(String(record.target_type))
    || !Number.isSafeInteger(record.source_included_count)
    || !Number.isSafeInteger(record.missing_excluded_count)
    || !Array.isArray(record.qualification_gaps)
    || !record.qualification_gaps.every((gap: unknown) => typeof gap === "string")) return null;
  return record as unknown as ReferenceValueEvidence;
}

export function applicationReferenceEvidence(
  output: unknown,
  population: "training" | "evaluation",
): ReferenceValueEvidence | null {
  if (!output || typeof output !== "object" || Array.isArray(output)) return null;
  const metadata = (output as Record<string, unknown>).metadata;
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) return null;
  return readReferenceEvidence(
    (metadata as Record<string, unknown>)[`${population}_reference_value_evidence`],
  );
}
