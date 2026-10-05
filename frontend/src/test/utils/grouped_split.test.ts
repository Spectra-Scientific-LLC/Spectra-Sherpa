import { describe, expect, it } from "vitest";
import {
  groupColumnFromInputs,
  groupedSplitSummary,
  splitMethodOptions,
  splitMethodTargetConflict,
} from "@/utils/groupedSplit";

describe("grouped split presentation authority", () => {
  it("finds the validation group on a connected SherpaDataset", () => {
    expect(
      groupColumnFromInputs([
        {
          data: {
            value: {
              type: "SherpaDataset",
              extra: { supervision_binding: { group_column: "batch" } },
            },
          },
        },
      ]),
    ).toBe("batch");
  });

  it("keeps every method selectable with groups active and labels the space-filling ones", () => {
    const options = splitMethodOptions(
      ["random", "stratified", "sequential", "group_holdout", "kennard_stone", "duplex", "spxy"],
      true,
    );

    // No method is withheld: the grouping column names a validation authority,
    // and the method decides whether the partition is constrained by it.
    expect(options?.some((option) => option.disabled)).toBe(false);
    expect(
      options
        ?.filter((option) => option.label !== String(option.value))
        .map((option) => option.value),
    ).toEqual(["kennard_stone", "duplex", "spxy"]);
    expect(options?.find((option) => option.value === "kennard_stone")?.label).toContain(
      "does not hold out groups",
    );
    expect(options?.find((option) => option.value === "random")?.label).toBe("random");
    // Named group holdout partitions by the grouping column, so it carries no
    // space-filling caveat.
    expect(options?.find((option) => option.value === "group_holdout")?.label).toBe(
      "group_holdout",
    );
  });

  it("names a continuous target that stratification cannot preserve", () => {
    // The staging case: Moisture is a concentration, not a class.
    expect(splitMethodTargetConflict("stratified", "continuous")).toContain(
      "requires a categorical target",
    );
    // Every other combination is admitted; only stratification needs classes.
    expect(splitMethodTargetConflict("stratified", "categorical")).toBeNull();
    expect(splitMethodTargetConflict("random", "continuous")).toBeNull();
    expect(splitMethodTargetConflict("kennard_stone", "continuous")).toBeNull();
    expect(splitMethodTargetConflict("sequential", "continuous")).toBeNull();
    // An unknown target type is not evidence of a conflict.
    expect(splitMethodTargetConflict("stratified", null)).toBeNull();
    expect(splitMethodTargetConflict("stratified", "")).toBeNull();
  });

  it("projects held-out group evidence from the executed split provenance", () => {
    const summary = groupedSplitSummary({
      ports: {
        X_test: {
          value: {
            type: "SherpaDataset",
            provenance: [
              {
                op_id: "data.train_test_split",
                parameters: {
                  method: "stratified",
                  n_groups: 6,
                  held_out_groups: ["batch_C", "batch_F"],
                  digest: "a".repeat(64),
                },
              },
            ],
          },
        },
      },
    });

    expect(summary).toEqual({
      method: "stratified",
      nGroups: 6,
      heldOutGroups: ["batch_C", "batch_F"],
      digest: "a".repeat(64),
    });
  });

  it("does not invent grouped evidence from malformed provenance", () => {
    expect(
      groupedSplitSummary({
        value: {
          provenance: [
            {
              op_id: "data.train_test_split",
              parameters: { n_groups: 1, held_out_groups: [] },
            },
          ],
        },
      }),
    ).toBeNull();
  });
});
