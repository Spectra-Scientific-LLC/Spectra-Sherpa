/* eslint-disable @typescript-eslint/no-explicit-any */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import QuickPlotModal from "@/views/workflow-builder/modals/QuickPlotModal.vue";
import { buildOutOfFoldEvidencePlot } from "@/utils/scientificPlots";
import oof from "../fixtures/oof-scientific-surface.json";
const stubs = {
  Dialog: { template: "<div><slot /></div>" },
  Dropdown: true,
  InputText: true,
  Button: true,
  PlotlyChart: true,
  DataTableModal: true,
  TabView: true,
  TabPanel: true,
};
function output(kind: string, data: any, value: any = data) {
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
        modes: ["plot", "table"],
        kind,
      },
    },
  };
}
describe("Scientific plotted populations", () => {
  it.each([false, true])(
    "GSC-07 retains OOF claim, folds and receipt identity on live/reopened surface (embedded=%s)",
    (embedded) => {
      const saved = JSON.parse(JSON.stringify(oof));
      const w = mount(QuickPlotModal, {
        props: {
          modelValue: true,
          embedded,
          nodeType: "selection.nested_cv",
          nodeLabel: "Saved nested CV",
          nodeOutput: output("out_of_fold_evidence", saved, saved),
        },
        global: { stubs },
      });
      const vm = w.vm as any;
      expect(vm.plotData[0].x).toEqual(saved.observations);
      expect(vm.plotData[0].y).toEqual(saved.predictions);
      expect(vm.plotData[0].customdata).toEqual([
        [0, 0],
        [1, 0],
        [2, 1],
        [3, 1],
      ]);
      expect(vm.plotData[0].hovertemplate).toContain("Validation fold (0-based)");
      expect(vm.plotLayout.title.text).toContain("Out-of-fold");
      expect(vm.plotLayout.title.text).toContain("2 validation folds · selection.nested_cv / audit_nested_cv");
      expect(vm.plotLayout.meta).toMatchObject({
        claim_scope: "out_of_fold",
        producer: oof.producer,
        evidence_sha256: oof.evidence_sha256,
        split_plan_digest: oof.split_plan_digest,
      });
      w.unmount();
    },
  );
  it.each([undefined, [0], [0, 0, -1, 1]])(
    "GSC-07 refuses missing or misaligned folds: %j",
    (fold_assignments) => {
      const result = buildOutOfFoldEvidencePlot({ ...oof, fold_assignments });
      expect(result.data).toEqual([]);
      expect((result.layout.title as any).text).toContain("fold assignments");
    },
  );
  it.each([
    { producer: undefined },
    {observations:[[1],[2],[3],[4]]},
    { evidence_sha256: "invalid" },
    { split_plan: { ...oof.split_plan, method: "invented" } },
    {
      split_plan: {
        ...oof.split_plan,
        folds: [
          { train: [2], test: [0, 1] },
          { train: [0, 1], test: [2, 3] },
        ],
      },
    },
    { split_plan_digest: undefined },
    { fold_assignments: [0, 1, 0, 1] },
    {
      split_plan: {
        ...oof.split_plan,
        folds: [
          { train: [0, 1], test: [0, 1] },
          { train: [0, 1], test: [2, 3] },
        ],
      },
    },
  ])("GSC-07 refuses absent or inconsistent producer/split authority: %j", (change) => {
    const result = buildOutOfFoldEvidencePlot({ ...oof, ...change });
    expect(result.data).toEqual([]);
    expect((result.layout.meta as any).refusal_reason).toBeTruthy();
  });
  it("GSC-14 honors exclusions before selecting 50 traces and retains exact source indices/labels", () => {
    const data = Array.from({ length: 80 }, (_, i) => [i, i + 1]);
    const mask = data.map((_, i) => i !== 0 && i !== 79);
    const projected = output("spectral_dataset", data, {
      data,
      y_axis: { include_mask: mask, labels: data.map((_, i) => `Exact ${i}`) },
    });
    Object.assign(projected.metadata, { data_role: "X_spectra", wavenumbers: [500, 501] });
    const w = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        embedded: true,
        nodeType: "data.file_load",
        nodeLabel: "Masked",
        nodeOutput: projected,
      },
      global: { stubs },
    });
    const vm = w.vm as any;
    expect(vm.plotData[0]).toMatchObject({ name: "Exact 1", y: [1, 2] });
    expect(vm.plotData[49].y).toEqual([50, 51]);
    expect(vm.plotLayout.meta.display_population).toMatchObject({
      shown: 50,
      total: 78,
      available: 80,
      excluded: 2,
      source_row_indices: Array.from({ length: 50 }, (_, i) => i + 1),
      sample_labels: Array.from({ length: 50 }, (_, i) => `Exact ${i + 1}`),
    });
    expect(w.get(".plot-sampling-disclosure").text()).toContain(
      "2 of 80 retained rows are excluded",
    );
    w.unmount();
  });
  it.each([[false, false], [true]])(
    "GSC-14 refuses empty or misaligned active cohorts: %j",
    (...mask) => {
      const data = [
          [1, 2],
          [3, 4],
        ],
        projected = output("spectral_dataset", data, { data, sample_axis: { include_mask: mask } });
      const w = mount(QuickPlotModal, {
        props: {
          modelValue: true,
          embedded: true,
          nodeType: "data.file_load",
          nodeLabel: "Mask",
          nodeOutput: projected,
        },
        global: { stubs },
      });
      expect((w.vm as any).plotData).toEqual([]);
      expect(w.get('[role="alert"]').text()).toMatch(/mask/);
      w.unmount();
    },
  );
  it.each([{embedded:false,nodeType:"data.file_load"},{embedded:true,nodeType:"data.file_load"},{embedded:true,nodeType:"preprocess.normalize"}])(
    "GSC-14 discloses 50/80 overlay while preserving all result rows ($nodeType, embedded=$embedded)",
    ({embedded,nodeType}) => {
      const data = Array.from({ length: 80 }, (_, i) => [i, i + 1]);
      const projected = output("spectral_dataset", data, { data });
      Object.assign(projected.metadata, {
        data_role: "X_spectra",
        wavenumbers: [500.001, 501.004],
        x_units: "nm",
        sample_labels: Array.from({ length: 80 }, (_, i) => `S${i}`),
      });
      const w = mount(QuickPlotModal, {
        props: {
          modelValue: true,
          embedded,
          nodeType,
          nodeLabel: "80 spectra",
          nodeOutput: projected,
        },
        global: { stubs },
      });
      const vm = w.vm as any;
      expect(vm.plotData).toHaveLength(50);
      expect(vm.plotData[49].y).toEqual([49, 50]);
      expect(vm.plotData[0].x).toEqual([500.001, 501.004]);
      expect(vm.plotLayout.meta.display_population).toMatchObject({
        shown: 50,
        total: 80,
        method: "first_rows",
        source_row_indices: Array.from({ length: 50 }, (_, i) => i),
      });
      if (nodeType === "preprocess.normalize") {
        expect(vm.plotLayout.annotations[1].text).toContain("50 of 80 active rows shown");
        expect(vm.plotLayout.meta.comparison_populations.original).toBeNull();
        expect(vm.plotLayout.meta.comparison_populations.preprocessed).toEqual(vm.plotLayout.meta.display_population);
      } else {
        expect(vm.plotLayout.title.text).toContain("First 50 of 80");
      }
      expect(w.get(".plot-sampling-disclosure").text()).toContain("50");
      expect(w.get(".plot-sampling-disclosure").text()).toContain("80");
      expect(w.props("nodeOutput").data).toHaveLength(80);
      expect(vm.plotSampling.plottedTableOnly).toBe(false);
      w.unmount();
    },
  );
  it("GSC-14 preserves separate masked comparison populations for overlay and heatmap", async () => {
    const makeOutput = (count: number, prefix: string) => {
      const data = Array.from({ length: count }, (_, i) => [i, i + 1]);
      return output("spectral_dataset", data, {
        data, y_axis: { labels: data.map((_, i) => `${prefix}${i}`), include_mask: data.map((_, i) => i !== 0) },
      });
    };
    const original = makeOutput(90, "Input ");
    const processed = makeOutput(80, "Output ");
    const w = mount(QuickPlotModal, { props: {
      modelValue: true, embedded: true, nodeType: "preprocess.normalize", nodeLabel: "Masked comparison",
      nodeInputs: { X: original }, nodeOutput: processed,
    }, global: { stubs } });
    const vm = w.vm as any;
    expect(vm.plotLayout.meta.comparison_populations.original).toMatchObject({
      shown: 50, total: 89, available: 90, excluded: 1, method: "first_rows",
      source_row_indices: Array.from({ length: 50 }, (_, i) => i + 1),
      sample_labels: Array.from({ length: 50 }, (_, i) => `Input ${i + 1}`),
    });
    expect(vm.plotLayout.meta.display_population).toMatchObject({
      shown: 50, total: 79, available: 80, excluded: 1, method: "first_rows",
      source_row_indices: Array.from({ length: 50 }, (_, i) => i + 1),
      sample_labels: Array.from({ length: 50 }, (_, i) => `Output ${i + 1}`),
    });
    expect(w.get(".plot-sampling-disclosure").text()).toContain("50 of 79 active preprocessed result rows");
    vm.selectedPlotKey = "spectra_heatmap";
    await w.vm.$nextTick();
    expect(vm.plotLayout.meta.comparison_populations.original).toMatchObject({ shown: 89, total: 89, method: "all_active" });
    expect(vm.plotLayout.meta.display_population).toMatchObject({ shown: 79, total: 79, method: "all_active" });
    expect(vm.plotLayout.meta.display_population.source_row_indices).toHaveLength(79);
    expect(w.find(".plot-sampling-disclosure").exists()).toBe(false);
    expect(original.data).toHaveLength(90);
    expect(processed.data).toHaveLength(80);
    w.unmount();
  });

  it("GSC-14 does not claim subsampling of a complete singleton overlay", () => {
    const data = [[1, 2]],
      projected = output("spectral_dataset", data, { data });
    Object.assign(projected.metadata, { data_role: "X_spectra", wavenumbers: [500, 501] });
    const w = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        embedded: true,
        nodeType: "data.file_load",
        nodeLabel: "singleton",
        nodeOutput: projected,
      },
      global: { stubs },
    });
    expect((w.vm as any).plotData).toHaveLength(1);
    expect(w.find(".plot-sampling-disclosure").exists()).toBe(false);
    w.unmount();
  });
});
