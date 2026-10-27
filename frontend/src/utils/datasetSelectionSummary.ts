/** View projection for a selection whose full matrix is loaded downstream. */
export interface DatasetSelectionSummary {
  files: string[];
  acquisition: {label: string; value: string; detail?: string}[];
  columns: string[];
  samples: Record<string, string | number>[];
  metadata: {label: string; value: string; detail?: string}[];
}
