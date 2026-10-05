/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, expect, it } from "vitest";
import { effectScope, ref } from "vue";
import { mount } from "@vue/test-utils";
import { useQuickPlotProjection } from "@/composables/useScientificPlotProjection";
import { matrixColorEncoding, scientificNumber } from "@/utils/scientificEncoding";
import { projectActiveSpectralCohort } from "@/utils/scientificCohort";
import {
  buildRegressionComparisonPlot,
  buildSalientFeaturesPlot,
  buildVipPlot,
} from "@/utils/scientificPlots";
import DataTableModal from "@/views/workflow-builder/modals/DataTableModal.vue";
function output(kind: string, data: any, value: any = { data }) {
  return {
    data,
    presentation_value: value,
    metadata: {
      scientific_presentation: {
        schema_version: "spectrasherpa-node-presentation/1",
        contract_digest: "a".repeat(64),
        presentation_id: "result",
        source_port: "result",
        source_ports: ["result"],
        kind,
        modes: ["plot", "table"],
      },
    },
  };
}
const masked = () =>
  output(
    "spectral_dataset",
    [
      [1, 2, 3],
      [999, 999, 999],
      [4, 5, 6],
    ],
    {
      data: [
        [1, 2, 3],
        [999, 999, 999],
        [4, 5, 6],
      ],
      sample_axis: { labels: ["A", "excluded", "C"], include_mask: [true, false, true] },
      feature_axis: { data: [1000.01, 1000.02, 1000.03], include_mask: [true, false, true] },
    },
  );
describe("scientific encoding and population regimes", () => {
  it.each(["pca_scores", "pls_scores", "plsda_scores"])(
    "%s preserves equal units in anisotropic and degenerate score clouds",
    (kind) => {
      const scope = effectScope();
      scope.run(() => {
        for (const data of [
          [
            [-100, -1],
            [0, 0],
            [100, 1],
          ],
          [[2, 2]],
          [
            [1, 1],
            [1 + 1e-9, 1],
          ],
        ]) {
          const source = ref(output(kind, data));
          const plot = useQuickPlotProjection(source, ref(""));
          expect(plot.plotLayout.value.yaxis).toMatchObject({
            scaleanchor: "x",
            scaleratio: 1,
            constrain: "range",
          });
          expect(plot.plotData.value[0].x).toEqual(data.map((row) => row[0]));
          expect(plot.plotLayout.value.annotations[0].text).toContain("fit-specific");
        }
      });
      scope.stop();
    },
  );
  it("uses zero-centered balanced color for signed values and sequential nonnegative values", () => {
    expect(matrixColorEncoding([[-2, 0, 2]], "signed_zero_centered").trace).toMatchObject({
      colorscale: "RdBu",
      zmin: -2,
      zmid: 0,
      zmax: 2,
    });
    expect(matrixColorEncoding([[0, 1, 2]], "nonnegative").trace.colorscale).toBe("Viridis");
    expect(matrixColorEncoding([[-1, 0, 1]]).notice).toContain("Physical baseline unspecified");
    expect(matrixColorEncoding([[-1, 0]], "nonnegative").error).toBeTruthy();
  });
  it("retains small nonzero residuals, nearby channels and small variance labels", () => {
    expect(scientificNumber(1e-6)).not.toBe("0");
    expect(scientificNumber(1000.01)).not.toBe(scientificNumber(1000.02));
    const scope = effectScope();
    scope.run(() => {
      const source = ref({
        ...output("pca_scores", [
          [1, 2],
          [2, 1],
        ]),
        metadata: {
          ...output("pca_scores", []).metadata,
          explained_variance_ratio: [0.0004, 0.0002],
        },
      });
      const scores = useQuickPlotProjection(source, ref(""));
      expect(scores.plotLayout.value.xaxis.title).toContain("4.0e-2%");
      expect(scores.plotLayout.value.yaxis.title).toContain("2.0e-2%");
      const residual = useQuickPlotProjection(
        ref(output("spectral_dataset", [[-1e-6, 0, 2e-6]])),
        ref(""),
      );
      residual.selectedPlotKey.value = "scientific_spectral_heatmap";
      expect(residual.plotData.value[0].hovertemplate).toContain("%{z:.15g}");
      expect(residual.plotData.value[0].z).toEqual([[-1e-6, 0, 2e-6]]);
    });
    scope.stop();
  });
  it.each([false, true])(
    "keeps masks/coordinates identical in overlay, heatmap and table (reopen=%s)",
    (reopen) => {
      const input = reopen ? JSON.parse(JSON.stringify(masked())) : masked();
      const original = JSON.stringify(input);
      const scope = effectScope();
      scope.run(() => {
        const plot = useQuickPlotProjection(ref(input), ref(""));
        expect(plot.plotData.value.map((trace) => trace.y)).toEqual([
          [1, 3],
          [4, 6],
        ]);
        expect(plot.plotData.value[1].meta.source_row_index).toBe(2);
        plot.selectedPlotKey.value = "scientific_spectral_heatmap";
        expect(plot.plotData.value[0].z).toEqual([
          [1, 3],
          [4, 6],
        ]);
        expect(plot.plotData.value[0].x).toEqual([1000.01, 1000.03]);
        expect(plot.plotLayout.value.meta.display_population).toMatchObject({
          total: 2,
          available: 3,
          excluded: 1,
          shown_features: 2,
          excluded_features: 1,
        });
      });
      scope.stop();
      const w = mount(DataTableModal, {
        props: {
          modelValue: true,
          nodeType: "data.file_load",
          nodeLabel: "Cohort",
          nodeOutput: input,
        },
        global: {
          stubs: {
            Dialog: { template: "<div><slot/></div>" },
            Dropdown: true,
            InputText: true,
            Button: true,
            DataTable: true,
            Column: true,
          },
        },
      });
      expect((w.vm as any).displayedData).toEqual([
        [1, 3],
        [4, 6],
      ]);
      expect(w.text()).toContain("2 of 3 retained rows; 1 excluded");
      expect((w.vm as any).previewTableData[1]._index).toBe(3);
      expect(JSON.stringify(input)).toBe(original);
      w.unmount();
    },
  );
  it.each([[false, false, false], [true], [true, 1, true]])(
    "refuses empty or malformed masks %j",
    (mask) => {
      const input = masked();
      input.presentation_value.sample_axis.include_mask = mask;
      expect(projectActiveSpectralCohort(input).error).toBeTruthy();
    },
  );
  it("slices every aligned axis field and preserves typed class identity", () => {
    const input: any = masked();
    Object.assign(input.presentation_value.sample_axis, {
      classes: [1, "1", false],
      exclusion_reasons: [null, "rejected", null],
      sample_table: { id: ["A", "B", "C"], batch: [1, 2, 3] },
      alternate_scales: [{ name: "time", values: [10, 20, 30] }],
      alternate_label_sets: [{ name: "names", values: ["a", "b", "c"] }],
      class_sets: [
        { name: "class", values: [1, "1", false], levels: [{ value: 1, label: "one" }] },
      ],
    });
    input.presentation_value.feature_axis.selection_scores = [0.1, 0.2, 0.3];
    const active = projectActiveSpectralCohort(input);
    const axis = active.output.presentation_value.sample_axis;
    expect(axis.classes).toEqual([1, false]);
    expect(axis.exclusion_reasons).toEqual([null, null]);
    expect(axis.sample_table).toEqual({ id: ["A", "C"], batch: [1, 3] });
    expect(axis.alternate_scales[0].values).toEqual([10, 30]);
    expect(axis.alternate_label_sets[0].values).toEqual(["a", "c"]);
    expect(axis.class_sets[0].values).toEqual([1, false]);
    expect(active.output.presentation_value.feature_axis.selection_scores).toEqual([0.1, 0.3]);
    input.presentation_value.sample_axis.sample_table.id = ["short"];
    expect(projectActiveSpectralCohort(input).error).toContain("aligned metadata");
  });
  it("uses explicit unmasked feature coordinates and preserves paired component signs", () => {
    const scope = effectScope();
    scope.run(() => {
      const p = useQuickPlotProjection(
        ref(
          output("spectral_dataset", [[1e-6, 2e-6]], {
            data: [[1e-6, 2e-6]],
            feature_axis: { data: [1000.01, 1000.02] },
          }),
        ),
        ref(""),
      );
      expect(p.plotData.value[0].x).toEqual([1000.01, 1000.02]);
      p.selectedPlotKey.value = "scientific_spectral_heatmap";
      expect(p.plotData.value[0].x).toEqual([1000.01, 1000.02]);
      for (const sign of [1, -1]) {
        const scores = useQuickPlotProjection(
          ref(
            output("pca_scores", [
              [2, sign],
              [-2, -sign],
            ]),
          ),
          ref(""),
        );
        expect(scores.plotData.value[0].y).toEqual([sign, -sign]);
        const pairedLoading = [3 * sign, 4 * sign];
        expect(pairedLoading.map((v) => v * sign)).toEqual([3, 4]);
      }
    });
    scope.stop();
  });
  it.each(["pca_loadings", "pls_loadings", "plsda_loadings"])(
    "%s discloses fit-specific orientation",
    (kind) => {
      const scope = effectScope();
      scope.run(() => {
        const p = useQuickPlotProjection(
          ref(
            output(kind, [
              [1, 2],
              [3, 4],
            ]),
          ),
          ref(""),
        );
        expect(JSON.stringify(p.plotLayout.value.annotations)).toContain("fit-specific");
      });
      scope.stop();
    },
  );
  it("refuses partial invalid scientific records and labels unavailable VIP stability", () => {
    const feature = buildSalientFeaturesPlot({
      features: [
        { position: 1, importance: 0.5 },
        { position: 2, importance: null },
      ],
    });
    expect(feature.data).toEqual([]);
    expect(feature.layout.meta.refusal_reason).toContain("1 of 2");
    const comparison = buildRegressionComparisonPlot([
      { sample: "A", target: "y", reference: 1, predicted: 2, residual: -1, role: "held_out_test" },
      null,
    ]);
    expect(comparison.data).toEqual([]);
    expect(comparison.layout.meta.refusal_reason).toContain("1 of 2");
    expect(buildVipPlot({ scores: [0.2, 1.1] }).layout.annotations[0].text).toContain(
      "stability is not displayed",
    );
  });
});
