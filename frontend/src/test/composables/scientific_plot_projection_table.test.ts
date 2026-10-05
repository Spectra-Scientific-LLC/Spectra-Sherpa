/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, expect, it } from "vitest";
import { ref } from "vue";

import { useQuickPlotProjection } from "@/composables/useScientificPlotProjection";

describe("canonical scientific projection data table", () => {
  it("labels salient rows as groups, not spectra, and preserves positions and fractions", () => {
    const plot = useQuickPlotProjection(ref({
      data: [{ consensus_group: 1, position: 1206, detection_fraction: 1, label: "155/155" }],
      metadata: { type: "salient_features", method: "peak_finding", n_rows: 1, n_cols: 4,
        column_units: { position: "nm" } },
    } as any), ref("output.data_table"));
    expect(plot.dataShape.value).toMatchObject({ rows: 1, cols: 4, rowLabel: "consensus groups" });
    plot.selectedPlotKey.value = "table_column:1";
    expect(plot.plotData.value[0].y).toEqual([1206]);
    expect(plot.plotLayout.value.yaxis.title).toBe("position (nm)");
    plot.selectedPlotKey.value = "table_column:2";
    expect(plot.plotData.value[0].y).toEqual([1]);
  });
  it("plots a selected numeric table column without recomputation", () => {
    const nodeOutput = ref({
      data: [[0.1], [0.2], [0.3]],
      metadata: {
        type: "array",
        show_index: true,
        column_names: ["Value"],
      },
    } as any);
    const plot = useQuickPlotProjection(nodeOutput, ref("output.data_table"));

    expect(plot.availablePlots.value).toEqual([{ key: "table_column:0", label: "Value" }]);
    plot.selectedPlotKey.value = "table_column:0";
    expect(plot.plotData.value[0].y).toEqual([0.1, 0.2, 0.3]);
  });

  it("offers numeric record columns without plotting identifiers", () => {
    const nodeOutput = ref({
      data: [
        { class: "malignant", sensitivity: 0.91, specificity: 0.96 },
        { class: "benign", sensitivity: 0.96, specificity: 0.91 },
      ],
      metadata: {
        type: "metrics",
        show_index: true,
        column_names: ["class", "sensitivity", "specificity"],
      },
    } as any);
    const plot = useQuickPlotProjection(nodeOutput, ref("output.data_table"));

    expect(plot.availablePlots.value.map(item => item.label)).toEqual(["class", "sensitivity", "specificity"]);
    plot.selectedPlotKey.value = "table_column:1";
    expect(plot.plotData.value[0].y).toEqual([0.91, 0.96]);
  });
});
