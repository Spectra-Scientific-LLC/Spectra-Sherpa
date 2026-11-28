import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ModelSummaryCard from "@/components/ModelSummaryCard.vue";
import ValidationLedger from "@/components/ValidationLedger.vue";
import { buildModelSummary } from "@/utils/modelSummary";
import { repeatedText } from "@/test/utils/noDuplicateText";

const definition = { schema_version: 1, nodes: [
  { node_id: "model_1", node_type: "model.fitted_pls", label: "PLS", parameters: { n_components: 3, scale: false } },
  { node_id: "eval_1", node_type: "diagnostics.regression_evaluator", label: "Evaluate", parameters: {} },
], edges: [{ source: "model_1", target: "eval_1" }] };
const comparison = (role: string, rmse: number) => ({
  schema_version: "spectrasherpa-regression-comparison/1", metadata: { role, target_units: ["%"] }, data: [],
  statistics: { targets: [{ target: "Moisture", metrics: { n_samples: role === "calibration" ? 60 : 20, rmse, r2: 0.99, bias: 1e-14, sep: rmse, slope: 1 } }] },
});

describe("no text is repeated on a page", () => {
  it("model summary card states each statistic and unit once", () => {
    const summary = buildModelSummary(definition as never, null, [
      { source: { nodeId: "model_1", port: "calibration_comparison", kind: "regression_comparison" }, value: comparison("calibration", 0.0147) },
      { source: { nodeId: "eval_1", port: "comparison", kind: "regression_comparison" }, value: comparison("held_out_test", 0.0283) },
    ]);
    const card = mount(ModelSummaryCard, { props: { summary, display: "full" } });
    expect(repeatedText(card)).toEqual([]);
  });

  it("per-sample table names one target and one population once", () => {
    const rows = Array.from({ length: 5 }, (_, index) => ({
      sample: `corn-${index}`, target: "Moisture", reference: 10 + index / 10, predicted: 10.01 + index / 10,
      residual: -0.01, role: "held_out_test",
    }));
    const ledger = mount(ValidationLedger, { props: { rows }, global: { stubs: { Button: true } } });
    expect(repeatedText(ledger, 6)).toEqual([]);
  });
});
