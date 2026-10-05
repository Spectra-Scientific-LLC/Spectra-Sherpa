import { describe, expect, it } from "vitest";
import { nextTick, ref } from "vue";
import { useQuickPlotProjection } from "@/composables/useScientificPlotProjection";
import type { NodeOutput } from "@/utils/nodeOutput";

describe("regression per-response metrics without aggregate fields", () => {
  it("uses the selected response's metrics and permits unavailable R²", async () => {
    const output = ref({
      data: [[1, 2], [2, 3], [3, 4]],
      metadata: {
        type: "PCR", output_type: "regression", n_targets: 2,
        target_names: ["CN", "Density"],
        y_true: [[1, .8], [2, .8], [3, .8]],
        y_pred: [[1.2, .801], [1.8, .799], [3.2, .8]],
        r2_per_target: [.94, null], rmse_per_target: [.2, .001],
        metric_summary_scope: "per_response_only",
        quality_summary: { n_targets: 2, metric_summary_scope: "per_response_only" },
      },
    } as unknown as NodeOutput);
    const projection = useQuickPlotProjection(output, ref("model.pcr"));
    projection.selectedPlotKey.value = "regression";
    expect(JSON.stringify(projection.plotLayout.value.title)).toContain("CN");
    expect(JSON.stringify(projection.plotLayout.value.title)).toContain("0.94");
    projection.regressionTargetIdx.value = 1;
    await nextTick();
    const title = JSON.stringify(projection.plotLayout.value.title);
    expect(title).toContain("Density");
    expect(title).toContain("0.001");
    expect(title).not.toContain("0.94");
    expect(title).not.toMatch(/R²\s*=\s*0/);
    expect(projection.plotData.value.length).toBeGreaterThan(0);
  });
});
