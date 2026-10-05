import { beforeEach, describe, expect, it } from "vitest";
import {
  bindingForTemplateSource,
  bindingFromSelectionReceipt,
  consumeDataSelectionReceipt,
  dataSelectionReceiptStorageKey,
  loadDataSelectionReceipt,
  storeDataSelectionReceipt,
  type DataSelectionReceipt,
} from "@/utils/workflowDataSelection";

const receipt: DataSelectionReceipt = {
  schema_version: "spectra-my-dataset-workflow-selection/3",
  receipt_id: "selection-test",
  project_id: 7,
  datasets: [
    {
      experiment_id: 11,
      dataset_name: "First",
      selection: "all",
      selected_file_count: 3,
      file_ids: null,
      stage: "raw",
    },
    {
      experiment_id: 12,
      dataset_name: "Second",
      selection: "subset",
      selected_file_count: 2,
      file_ids: [41, 43],
      asset_id: "m5spec",
      stage: "preprocessed",
    },
  ],
  target_authority: {
    schema_version: "spectrasherpa-target-authority/1",
    column: "claimed_botanical_group",
    target_type: "categorical",
    units: null,
    source_digest: "a".repeat(64),
  },
  group: "block",
  analysis_readiness_experiment_id: 12,
};

describe("workflow data selection binding", () => {
  beforeEach(() => sessionStorage.clear());

  it("retains independent route-scoped receipts and consumes only the opened one", () => {
    const first = { ...receipt, receipt_id: "receipt-first" };
    const second = {
      ...receipt,
      receipt_id: "receipt-second",
      datasets: [{ ...receipt.datasets[0], experiment_id: 99, dataset_name: "Other" }],
    };

    storeDataSelectionReceipt(first);
    storeDataSelectionReceipt(second);

    expect(loadDataSelectionReceipt("receipt-first")?.datasets[0].dataset_name).toBe("First");
    expect(loadDataSelectionReceipt("receipt-second")?.datasets[0].dataset_name).toBe("Other");
    expect(loadDataSelectionReceipt()).toBeNull();
    consumeDataSelectionReceipt("receipt-first");
    expect(loadDataSelectionReceipt("receipt-first")).toBeNull();
    expect(loadDataSelectionReceipt("receipt-second")?.datasets[0].dataset_name).toBe("Other");
  });

  it("bounds retained pending receipts", () => {
    for (let index = 0; index < 10; index += 1) {
      storeDataSelectionReceipt({ ...receipt, receipt_id: `receipt-${index}` });
    }

    expect(sessionStorage.getItem(dataSelectionReceiptStorageKey("receipt-0"))).toBeNull();
    expect(sessionStorage.getItem(dataSelectionReceiptStorageKey("receipt-1"))).toBeNull();
    expect(loadDataSelectionReceipt("receipt-2")).not.toBeNull();
    expect(loadDataSelectionReceipt()).toBeNull();
  });

  it("preserves the selected dataset's exact members, target, and group", () => {
    expect(bindingFromSelectionReceipt(receipt, 12)).toEqual({
      source: "experiment",
      experimentId: 12,
      displayName: "Second",
      fileIds: [41, 43],
      allFiles: false,
      assetId: "m5spec",
      targetAuthority: receipt.target_authority,
      groupColumn: "block",
      stage: "preprocessed",
    });
  });

  it("represents an all-members selection without inventing file identities", () => {
    expect(bindingFromSelectionReceipt(receipt, 11)).toMatchObject({
      experimentId: 11,
      fileIds: null,
      allFiles: true,
    });
  });

  it("preserves a categorical My Dataset target for a PCA-style source role", () => {
    const primary = bindingFromSelectionReceipt(receipt, 12);
    expect(primary).not.toBeNull();

    const binding = bindingForTemplateSource(primary!, null, null);

    expect(binding).toEqual(
      expect.objectContaining({
        targetAuthority: receipt.target_authority,
        groupColumn: "block",
        fileIds: [41, 43],
      }),
    );
  });

  it("uses an explicit separate-target role type when one is declared", () => {
    const primary = {
      ...bindingFromSelectionReceipt(receipt, 12)!,
      targetAuthority: null,
      groupColumn: null,
    };
    const separateTarget = {
      source: "experiment" as const,
      experimentId: 13,
      fileId: 51,
      targetAuthority: {
        schema_version: "spectrasherpa-target-authority/1" as const,
        column: "moisture",
        target_type: "continuous" as const,
        units: "%",
        source_digest: "b".repeat(64),
      },
    };

    const binding = bindingForTemplateSource(primary, "continuous", separateTarget);

    expect(binding?.targetAuthority).toBeNull();
    expect(binding?.targetBinding).toEqual(separateTarget);
  });

  it("refuses a separate-target role that contradicts the selected target authority", () => {
    const primary = bindingFromSelectionReceipt(receipt, 12)!;
    const separateTarget = {
      source: "experiment" as const,
      experimentId: 13,
      fileId: 51,
      targetAuthority: {
        schema_version: "spectrasherpa-target-authority/1" as const,
        column: "cultivar",
        target_type: "categorical" as const,
        units: null,
        source_digest: "c".repeat(64),
      },
    };

    expect(bindingForTemplateSource(primary, "continuous", separateTarget)).toBeNull();
  });

  it("drops an orphan group when a receipt has no coherent target pair", () => {
    const malformed: DataSelectionReceipt = {
      ...receipt,
      target_authority: null,
      group: "block",
    };

    expect(bindingFromSelectionReceipt(malformed, 12)).toMatchObject({
      targetAuthority: null,
      groupColumn: null,
    });
  });

  it("preserves an explicitly continuous numeric target", () => {
    const continuous: DataSelectionReceipt = {
      ...receipt,
      target_authority: {
        schema_version: "spectrasherpa-target-authority/1",
        column: "moisture",
        target_type: "continuous",
        units: "%",
        source_digest: "d".repeat(64),
      },
      group: null,
    };

    expect(bindingFromSelectionReceipt(continuous, 12)).toMatchObject({
      targetAuthority: continuous.target_authority,
    });
  });
});
