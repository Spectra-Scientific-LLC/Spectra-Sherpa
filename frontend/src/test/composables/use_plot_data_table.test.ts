/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, expect, it } from "vitest";
import { ref } from "vue";

import { usePlotData } from "@/composables/usePlotData";

describe("usePlotData data table", () => {
  it("does not synthesize quick plots for output.data_table nodes", () => {
    const nodeOutput = ref({
      data: [[0.1], [0.2], [0.3]],
      metadata: {
        type: "array",
        show_index: true,
        column_names: ["Value"],
      },
    } as any);
    const plot = usePlotData(nodeOutput, ref("output.data_table"));

    expect(plot.availablePlots.value).toEqual([]);
    expect(plot.plotData.value).toEqual([]);
  });

  it("does not plot row-dict table payloads", () => {
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
    const plot = usePlotData(nodeOutput, ref("output.data_table"));

    expect(plot.availablePlots.value).toEqual([]);
    expect(plot.plotData.value).toEqual([]);
  });
});
