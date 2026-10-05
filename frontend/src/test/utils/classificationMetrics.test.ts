import { describe, expect, it } from "vitest";
import {
  collectCanonicalClassificationMetrics,
  flattenClassificationMetricsContract,
  primaryClassificationMetricSummary,
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

  it("summarizes the declared primary classification split", () => {
    const summary = primaryClassificationMetricSummary({
      task_type: "classification",
      primary_split: "train",
      n_classes: 3,
      classes: ["setosa", "versicolor", "virginica"],
      splits: { train: {
        accuracy: 0.82,
        balanced_accuracy: 0.81,
        precision_macro: 0.83,
        recall_macro: 0.81,
        specificity_macro: 0.9,
        f1_macro: 0.8,
      } },
      confusion_matrices: { train: [[38, 0, 0], [0, 25, 13], [0, 7, 30]] },
    });

    expect(summary).toEqual({
      task_type: "classification",
      primary_split: "train",
      n_classes: 3,
      classes: ["setosa", "versicolor", "virginica"],
      n_samples: 113,
      accuracy: 0.82,
      balanced_accuracy: 0.81,
      macro_precision: 0.83,
      macro_recall: 0.81,
      macro_specificity: 0.9,
      macro_f1: 0.8,
    });
  });
});
