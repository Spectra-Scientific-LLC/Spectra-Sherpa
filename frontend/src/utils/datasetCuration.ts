export interface CurationObservation {
  sample_id: string;
  file_name: string;
  sha256: string;
  prepared_data_sha256: string;
  asset_id: string;
  source_row: number;
}
export interface SampleInclusionRow {
  sampleId: string;
  included: boolean;
  editable: boolean;
}
export interface SampleInclusionState {
  rows: SampleInclusionRow[];
  loading: boolean;
}

/** Decode the verified, little-endian inclusion receipt used by curated portfolios. */
export function savedPortfolioInclusion(selection: unknown): SampleInclusionState | null {
  if (!selection || typeof selection !== "object") return null;
  const receipt = selection as Record<string, unknown>;
  if (receipt.schema_version !== "spectrasherpa-dataset-view/2" ||
      !Array.isArray(receipt.observations) ||
      !Number.isInteger(receipt.n_samples) ||
      receipt.n_samples !== receipt.observations.length ||
      typeof receipt.included_sample_mask_hex !== "string") return null;
  const source = receipt.source_selection as Record<string, unknown> | undefined;
  const mask = receipt.included_sample_mask_hex;
  const sourceMask = source?.included_sample_mask_hex;
  if (typeof sourceMask !== "string" || mask.length !== Math.ceil(receipt.n_samples / 8) * 2 ||
      sourceMask.length !== mask.length || !/^(?:[0-9a-f]{2})+$/i.test(mask) ||
      !/^(?:[0-9a-f]{2})+$/i.test(sourceMask)) return null;
  const seen = new Set<string>();
  const rows: SampleInclusionRow[] = [];
  for (let index = 0; index < receipt.n_samples; index += 1) {
    const observation = receipt.observations[index];
    const sampleId = observation?.sample_id;
    if (typeof sampleId !== "string" || !sampleId || seen.has(sampleId)) return null;
    seen.add(sampleId);
    const byte = Math.floor(index / 8) * 2;
    const bit = 1 << (index % 8);
    rows.push({
      sampleId,
      included: (Number.parseInt(mask.slice(byte, byte + 2), 16) & bit) !== 0,
      editable: (Number.parseInt(sourceMask.slice(byte, byte + 2), 16) & bit) !== 0,
    });
  }
  return { rows, loading: false };
}
export interface CurationSource {
  experiment_id: number;
  stage: "raw" | "preprocessed" | "synthetic";
  selected_file_ids: number[] | null;
  asset_id: string | null;
  target_authority: unknown;
  group_column: string | null;
  parent_view_id?: number | null;
  parent_sha256?: string | null;
  source_manifest_sha256?: string | null;
  collection_definition_sha256?: string | null;
  scientific_collection_sha256?: string | null;
  review_origin?: { workflow_id: number; run_id: number; node_id: string; revision: number };
  seed_observations?: CurationObservation[];
}
export type ReviewCurationSource = CurationSource & { observations: CurationObservation[] };
