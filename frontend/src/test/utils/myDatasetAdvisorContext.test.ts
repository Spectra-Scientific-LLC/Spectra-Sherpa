import { describe, expect, it } from "vitest";
import { captureDatasetSelection, captureLoadedDatasetSelection } from "@/utils/myDatasetAdvisorContext";
import type { SherpaDatasetDict } from "@/types";

const dataset = {
  n_samples: 3,
  n_features: 2,
  data: [
    [1, 2],
    [3, 4],
    [5, 6],
  ],
  y_axis: { labels: ["A", "B", "C"], sample_table: { group: ["x", "y", "z"] } },
  metadata: { source_member_metadata: ["a", "b", "c"].map((file_name) => ({ file_name })) },
} as SherpaDatasetDict;

describe("Advisor dataset selection snapshot", () => {
  it("uses a loaded plot projection for a non-active dataset without inventing full-source counts", () => {
    const source = {
      experimentId: 2,
      name: "Second source",
      members: [{ fileId: 7, fileName: "matrix.npz", dataset }],
      selectedFileCount: 1,
      totalFileCount: 1,
    };
    expect(captureLoadedDatasetSelection(null, ["matrix.npz"], source)).toMatchObject({
      status: "exact", selected_samples: 3, source_samples: 3,
      row_mask: [true, true, true], projection_scope: "whole_source",
    });
    expect(captureLoadedDatasetSelection(null, ["matrix.npz"], { ...source, totalFileCount: 2 })).toMatchObject({
      status: "exact", selected_samples: 3, source_samples: null,
      projection_scope: "selected_files_only",
    });
    expect(captureLoadedDatasetSelection(dataset, ["b"], source).row_mask).toEqual([false, true, false]);
  });
  it("preserves all descriptors and exact selection without copying matrix values", () => {
    const state = captureDatasetSelection(dataset, ["b"]);
    expect(state).toMatchObject({
      status: "exact",
      row_mask: [false, true, false],
      selected_samples: 1,
      source_samples: 3,
    });
    expect(state.contents).not.toHaveProperty("data");
    expect(state.contents?.y_axis).toEqual(dataset.y_axis);
    expect(state.row_identities?.[1]).toEqual({ sampleLabel: "B", fileName: "b" });
    expect(captureDatasetSelection(dataset, ["a", "c"]).row_mask).toEqual([true, false, true]);
    expect(state.row_mask).toEqual([false, true, false]);
  });
  it("distinguishes all, none, unknown selection, and incomplete data", () => {
    expect(captureDatasetSelection(dataset, null).row_mask).toEqual([true, true, true]);
    expect(captureDatasetSelection(dataset, undefined).row_mask).toEqual([false, false, false]);
    expect(captureDatasetSelection(dataset, ["foreign"]).row_mask).toBeNull();
    expect(captureDatasetSelection({ ...dataset, n_samples: 99 }, null).row_mask).toBeNull();
  });
});
