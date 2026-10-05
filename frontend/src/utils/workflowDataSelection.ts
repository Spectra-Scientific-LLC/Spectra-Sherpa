import type { TargetAuthority, TemplateDataBinding } from "@/stores/workflow-types";
import type { DatasetAnalysisReadiness, ExperimentStage } from "@/types";

export type DataSelectionReceipt = {
  schema_version: "spectra-my-dataset-workflow-selection/3";
  /** One navigation-scoped identity. A later tab or selection cannot reuse it. */
  receipt_id: string;
  project_id: number | null;
  datasets: Array<{
    experiment_id: number;
    dataset_name: string;
    selection: "all" | "subset";
    selected_file_count: number;
    file_ids: number[] | null;
    file_paths?: string[] | null;
    asset_id?: string | null;
    stage: ExperimentStage;
  }>;
  target_authority: TargetAuthority | null;
  group: string | null;
  analysis_readiness?: DatasetAnalysisReadiness | null;
  analysis_readiness_experiment_id?: number | null;
};

export const DATA_SELECTION_RECEIPT_LEGACY_KEY =
  "spectra-my-dataset-workflow-selection-v3";
const DATA_SELECTION_RECEIPT_KEY_PREFIX = `${DATA_SELECTION_RECEIPT_LEGACY_KEY}:`;
const DATA_SELECTION_RECEIPT_INDEX_KEY = `${DATA_SELECTION_RECEIPT_LEGACY_KEY}:index`;
const MAX_RETAINED_DATA_SELECTION_RECEIPTS = 8;

export function dataSelectionReceiptStorageKey(receiptId: string): string {
  return `${DATA_SELECTION_RECEIPT_KEY_PREFIX}${encodeURIComponent(receiptId)}`;
}

function readReceiptIndex(storage: Storage): string[] {
  try {
    const value = JSON.parse(storage.getItem(DATA_SELECTION_RECEIPT_INDEX_KEY) || "[]");
    return Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string" && item.length > 0)
      : [];
  } catch {
    return [];
  }
}

function writeReceiptIndex(storage: Storage, receiptIds: string[]): void {
  storage.setItem(DATA_SELECTION_RECEIPT_INDEX_KEY, JSON.stringify(receiptIds));
}

export function storeDataSelectionReceipt(
  receipt: DataSelectionReceipt,
  storage: Storage = window.sessionStorage,
): void {
  storage.setItem(dataSelectionReceiptStorageKey(receipt.receipt_id), JSON.stringify(receipt));
  const retained = [
    receipt.receipt_id,
    ...readReceiptIndex(storage).filter((receiptId) => receiptId !== receipt.receipt_id),
  ];
  const current = retained.slice(0, MAX_RETAINED_DATA_SELECTION_RECEIPTS);
  for (const receiptId of retained.slice(MAX_RETAINED_DATA_SELECTION_RECEIPTS)) {
    storage.removeItem(dataSelectionReceiptStorageKey(receiptId));
  }
  writeReceiptIndex(storage, current);
  storage.removeItem(DATA_SELECTION_RECEIPT_LEGACY_KEY);
}

export function loadDataSelectionReceipt(
  receiptId: string | null = null,
  storage: Storage = window.sessionStorage,
): DataSelectionReceipt | null {
  const parse = (raw: string | null): DataSelectionReceipt | null => {
    if (!raw) return null;
    try {
      return JSON.parse(raw) as DataSelectionReceipt;
    } catch {
      return null;
    }
  };
  if (receiptId) {
    const exact = parse(storage.getItem(dataSelectionReceiptStorageKey(receiptId)));
    if (exact) return exact;
    const legacy = parse(storage.getItem(DATA_SELECTION_RECEIPT_LEGACY_KEY));
    if (legacy?.receipt_id === receiptId) {
      storeDataSelectionReceipt(legacy, storage);
      return legacy;
    }
    return null;
  }
  // Scoped receipts are navigation capabilities, not a global "last data"
  // preference. Without the exact route identity, only the retired singleton
  // format may be read for compatibility with a handoff created by an older
  // frontend build.
  return parse(storage.getItem(DATA_SELECTION_RECEIPT_LEGACY_KEY));
}

export function consumeDataSelectionReceipt(
  receiptId: string,
  storage: Storage = window.sessionStorage,
): void {
  storage.removeItem(dataSelectionReceiptStorageKey(receiptId));
  writeReceiptIndex(
    storage,
    readReceiptIndex(storage).filter((candidateId) => candidateId !== receiptId),
  );
  try {
    const legacy = JSON.parse(
      storage.getItem(DATA_SELECTION_RECEIPT_LEGACY_KEY) || "null",
    ) as DataSelectionReceipt | null;
    if (legacy?.receipt_id === receiptId) storage.removeItem(DATA_SELECTION_RECEIPT_LEGACY_KEY);
  } catch {
    storage.removeItem(DATA_SELECTION_RECEIPT_LEGACY_KEY);
  }
}

export function createDataSelectionReceiptId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `selection-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function bindingFromSelectionReceipt(
  receipt: DataSelectionReceipt | null | undefined,
  experimentId: number | null,
): TemplateDataBinding | null {
  if (!receipt) return null;
  const selected =
    receipt.datasets.find((dataset) => dataset.experiment_id === experimentId) ??
    receipt.datasets[0];
  if (!selected) return null;
  const targetAuthority =
    receipt.analysis_readiness_experiment_id === selected.experiment_id
      ? receipt.target_authority
      : null;
  return {
    source: "experiment",
    experimentId: selected.experiment_id,
    displayName: selected.dataset_name,
    fileIds: selected.file_ids,
    allFiles: selected.selection === "all",
    assetId: selected.asset_id ?? null,
    targetAuthority,
    groupColumn: targetAuthority ? receipt.group : null,
    stage: selected.stage,
  };
}

/**
 * Add an optional separate target source without erasing the target authority
 * already chosen in My Dataset.
 *
 * Unsupervised starters such as PCA do not declare a separate target role, but
 * the scientist may still carry a categorical or continuous metadata choice
 * into the collection source. The server requires that selected target and
 * target type to remain an inseparable pair.
 */
export function bindingForTemplateSource(
  primaryBinding: TemplateDataBinding,
  separateTargetType: string | null,
  targetBinding: TemplateDataBinding | null,
): TemplateDataBinding | null {
  if (separateTargetType) {
    if (
      primaryBinding.targetAuthority ||
      primaryBinding.groupColumn ||
      !targetBinding?.targetAuthority ||
      targetBinding.targetAuthority.target_type !== separateTargetType
    ) {
      return null;
    }
    return {
      ...primaryBinding,
      targetBinding,
    };
  }
  if (primaryBinding.groupColumn && !primaryBinding.targetAuthority) {
    return null;
  }
  return {
    ...primaryBinding,
    targetBinding: undefined,
  };
}
