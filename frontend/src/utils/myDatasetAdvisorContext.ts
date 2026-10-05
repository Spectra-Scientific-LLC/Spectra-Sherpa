import type { DatasetPlotSource, SherpaDatasetDict } from "@/types";
import { alignedSpectrumIdentities, selectedDatasetRows } from "@/utils/multiDatasetOverlay";

export function captureLoadedDatasetSelection(
  resident: SherpaDatasetDict | null,
  files: string[] | null | undefined,
  source?: DatasetPlotSource,
) {
  if (resident || !source || source.members.length !== 1) {
    return captureDatasetSelection(resident, files);
  }
  const snapshot = captureDatasetSelection(source.members[0].dataset, source.selectedFileNames ?? null);
  const wholeSource = source.selectedFileCount === source.totalFileCount;
  return {
    ...snapshot,
    selected_files: files ?? null,
    projection_scope: wholeSource ? "whole_source" : "selected_files_only",
    // A server-filtered projection proves the selected count, not the full source count.
    source_samples: wholeSource ? snapshot.source_samples : null,
  };
}

export function captureDatasetSelection(
  dataset: SherpaDatasetDict | null,
  files: string[] | null | undefined,
) {
  if (!dataset) return { status: "not_loaded", selected_files: files ?? null };
  const indexes =
    files === undefined
      ? []
      : files === null
        ? dataset.data.map((_, index) => index)
        : selectedDatasetRows(dataset, files);
  const complete = dataset.data.length === dataset.n_samples && indexes !== null;
  const included = new Set(indexes ?? []);
  // Keep the full scientific descriptors, not a second copy of the spectral matrix.
  // The source collection remains the server-side authority for numeric data.
  const { data: _matrix, ...contents } = dataset;
  return {
    status: complete ? "exact" : "incomplete_projection",
    contents,
    selected_files: files ?? null,
    selection_mode: files === undefined ? "none" : files === null ? "all" : "subset",
    row_identities: alignedSpectrumIdentities(dataset, dataset.data.length, ""),
    row_mask: complete ? dataset.data.map((_, index) => included.has(index)) : null,
    selected_samples: complete ? included.size : null,
    source_samples: dataset.n_samples,
    numeric_values: "server_source_not_embedded",
  };
}
