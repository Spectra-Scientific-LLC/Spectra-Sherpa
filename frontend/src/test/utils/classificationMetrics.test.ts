import { describe, expect, it } from "vitest";
import {
  collectCanonicalClassificationMetrics,
  flattenClassificationMetricsContract,
} from "@/utils/classificationMetrics";

describe("classification metric utilities", () => {
  it("flattens canonical train and CV classification splits", () => {
    const flat = flattenClassificationMetricsContract({
      task_type: "classification",
      n_classes: 3,
      splits: {
        train: { accuracy: 0.9, f1_macro: 0.88 },
        cv: { accuracy: 0.82, balanced_accuracy: 0.8 },
      },
    });

    expect(flat).toEqual({
      train_accuracy: 0.9,
      train_f1_macro: 0.88,
      cv_accuracy: 0.82,
      cv_balanced_accuracy: 0.8,
      n_classes: 3,
    });
  });

  it("collects nested canonical metrics from model artifacts and report outputs", () => {
    const out: Record<string, unknown> = {};
    collectCanonicalClassificationMetrics(
      {
        metrics: {
          classification_metrics: {
            task_type: "classification",
            splits: { cv: { accuracy: 0.71, sensitivity_macro: 0.69 } },
          },
        },
      },
      out,
    );

    expect(out).toMatchObject({
      cv_accuracy: 0.71,
      cv_sensitivity_macro: 0.69,
    });
  });
});
