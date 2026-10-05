/* eslint-disable @typescript-eslint/no-explicit-any */
import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import DataTableModal from "@/views/workflow-builder/modals/DataTableModal.vue";
import QuickPlotModal from "@/views/workflow-builder/modals/QuickPlotModal.vue";
const stubs = {
  Dialog: { template: "<div><slot /></div>" },
  Dropdown: true,
  InputText: true,
  Button: true,
  DataTable: true,
  Column: true,
  PlotlyChart: true,
  Paginator: true,
};
const wrappers: any[] = [];
function table(data: any, metadata: any = {}) {
  const w = mount(DataTableModal, {
    props: {
      modelValue: true,
      nodeOutput: { data, metadata },
      nodeType: "output.plot",
      nodeLabel: "Synthetic",
    },
    global: { stubs },
  });
  wrappers.push(w);
  return w;
}
async function csv(w: any) {
  let blob: Blob | undefined;
  vi.spyOn(URL, "createObjectURL").mockImplementation((value: any) => {
    blob = value;
    return "blob:synthetic";
  });
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  w.vm.exportCSV();
  return blob?.text();
}
afterEach(() => {
  wrappers.splice(0).forEach((w) => w.unmount());
  vi.restoreAllMocks();
});
describe("Scientific surface export authority", () => {
  it("exports peak matrices with all four group columns and missing detections intact", async () => {
    const names = ["peak_position_1", "magnitude_at_peak_1", "group_position_1", "magnitude_at_group_position_1"];
    const w = table([[1202, 3, 1206, 2], [null, null, 1206, 1]], {
      column_names: names, sample_labels: ["detected", "missing"], data_role: "X_features",
    });
    expect(await csv(w)).toBe(`Index,Label,${names.join(",")}\n1,detected,1202,3,1206,2\n2,missing,,,1206,1\n`);
  });
  it("GSC-01 preserves both named spectra and point coordinates in table and CSV", async () => {
    const w = table([
      { type: "scatter", name: "A", x: [500, 501], y: [1, 2] },
      { type: "scatter", name: "B", x: [500, 501], y: [31, 32] },
    ]);
    await w.setProps({nodeOutput:{...w.props('nodeOutput'),metadata:{column_names:['stale_axis']}}});
    expect(w.vm.tableColumns.map((column:any)=>column.header)).toEqual(['#','trace_index','trace','point_index','x','y']);
    expect(w.vm.dataShape.cols).toBe(5);
    expect(w.vm.displayedData).toEqual([
      { trace_index: 1, trace: "A", point_index: 1, x: 500, y: 1 },
      { trace_index: 1, trace: "A", point_index: 2, x: 501, y: 2 },
      { trace_index: 2, trace: "B", point_index: 1, x: 500, y: 31 },
      { trace_index: 2, trace: "B", point_index: 2, x: 501, y: 32 },
    ]);
    expect(await csv(w)).toContain("4,2,B,2,501,32");
  });
  it("GSC-01 preserves grid coordinates and duplicate trace names without invented sample roles", () => {
    const w = table([
      { type: "heatmap", name: "grid", x: [10, 20], y: ["a"], z: [[1, null]] },
      { type: "heatmap", name: "grid", x: [10, 20], y: ["b"], z: [[3, 4]] },
    ]);
    expect(w.vm.displayedData).toHaveLength(4);
    expect(w.vm.displayedData[3]).toMatchObject({
      trace_index: 2,
      row_index: 1,
      column_index: 2,
      x: 20,
      y: "b",
      z: 4,
    });
  });
  it("GSC-01 refuses unsupported or mismatched trace coordinates instead of dropping a trace", async () => {
    const w = table([
      { type: "scatter", x: [1], y: [2] },
      { type: "scatter", x: [1, 2], y: [3] },
    ]);
    expect(w.get('[role="alert"]').text()).toContain("trace 2");
    expect(w.vm.displayedData).toEqual([]);
    expect(await csv(w)).toBeUndefined();
  });
  it("GSC-02 states the 100/120 scope and allows a sample beyond the preview after selecting All", async () => {
    const w = table(
      Array.from({ length: 120 }, (_, i) => [i]),
      { sample_labels: Array.from({ length: 120 }, (_, i) => `S${i}`) },
    );
    expect(w.text()).toContain("Showing first 100 of 120 rows");
    w.vm.searchQuery = "S119";
    await nextTick();
    expect(w.vm.tableData).toHaveLength(0);
    w.vm.rowLimit = 0;
    await nextTick();
    expect(w.vm.tableData).toHaveLength(1);
    expect(w.vm.tableData[0]._label_full).toBe("S119");
    expect(w.text()).toContain("regardless of preview limits or search filters");
  });
  it("GSC-02 all means all, including beyond the former 100000 bound", async () => {
    const w = table(Array.from({ length: 100001 }, (_, i) => i));
    w.vm.rowLimit = 0;
    await nextTick();
    expect(w.vm.tableData).toHaveLength(100001);
  });
  it("GSC-03 exports exact distinct spectral coordinates and unsplit sample labels", async () => {
    const w = table([[1, 2]], { wavenumbers: [500.001, 500.004], sample_labels: ["A,B"] });
    const output = await csv(w);
    expect(output).toBe('Index,Label,500.001,500.004\n1,"A,B",1,2\n');
    expect(w.text()).toContain("not a dataset or model replay package");
  });
  it("GSC-03 preserves non-spectral feature names and null values without borrowing target names", async () => {
    const w = table([[1, null]], {
      data_role: "X_features",
      feature_names: ["mass", "temperature"],
      target_names: ["class-A", "class-B"],
    });
    expect(await csv(w)).toBe("Index,mass,temperature\n1,1,\n");
  });
  it("GSC-03 preserves declared target names instead of inherited spectral coordinates", async () => {
    const w = table([[1, 2]], {
      target_names: ["A", "B"],
      wavenumbers: [500, 501],
      scientific_presentation: {
        schema_version: "spectrasherpa-node-presentation/1",
        contract_digest: "a".repeat(64),
        presentation_id: "targets",
        kind: "target_matrix",
        source_port: "target",
        source_ports: ["target"],
        modes: ["table"],
      },
    });
    expect(await csv(w)).toBe("Index,A,B\n1,1,2\n");
  });
  it.each([
    { role: "response_class", labels: ["control", "treated"] },
    { role: "actual_predicted_value", labels: ["Actual", "Predicted"] },
  ])(
    "GSC-03 uses declared $role columns over stale spectral coordinates",
    async ({ role, labels }) => {
      const w = table([[1, 2]], { wavenumbers: [500, 501] });
      await w.setProps({
        nodeOutput: {
          data: [[1, 2]],
          descriptor: { dimensions: [{ role: "sample" }, { role, labels }] },
          metadata: { wavenumbers: [500, 501] },
        },
      });
      expect(await csv(w)).toBe(`Index,${labels.join(",")}\n1,1,2\n`);
      expect(w.vm.tableColumns.map((c: any) => c.header)).toEqual(expect.arrayContaining(labels));
    },
  );
  it("GSC-03 preserves the exact source row label independently of display normalization", async () => {
    const w = table([[1], [2]], { sample_labels: ["  sample A  ", '["raw","tuple"]'] });
    expect(await csv(w)).toBe('Index,Label,Value\n1,  sample A  ,1\n2,"[""raw"",""tuple""]",2\n');
  });
  it("GSC-03 takes exact typed sample-axis identity before cleaned convenience metadata", async () => {
    const w = table([[1]], { sample_labels: ["Readability label"] });
    await w.setProps({
      nodeOutput: {
        data: [[1]],
        presentation_value: { data: [[1]], y_axis: { labels: ["  exact source | record 001  "] } },
        metadata: { sample_labels: ["Readability label"] },
      },
    });
    expect(await csv(w)).toBe("Index,Label,Value\n1,  exact source | record 001  ,1\n");
  });
  it.each([["short"], [{ nested: "ambiguous" }, "B"]])(
    "GSC-03 refuses invalid row authority: %j",
    async (...labels) => {
      const w = table([[1], [2]], { sample_labels: labels });
      expect(await csv(w)).toBeUndefined();
      await nextTick();
      expect(w.get('[role="alert"]').text()).toContain("declared row labels");
    },
  );
  it("GSC-09 reports an unavailable chart instead of a silent download no-op", async () => {
    const w = mount(QuickPlotModal, {
      props: {
        modelValue: true,
        embedded: true,
        nodeType: "output.plot",
        nodeLabel: "Empty",
        nodeOutput: { data: [], metadata: {} },
      },
      global: { stubs },
    });
    wrappers.push(w);
    await (w.vm as any).downloadPlot();
    await nextTick();
    expect(w.get('[role="alert"]').text()).toContain("Open an available plot");
  });
});

it("XGSC-06 exports the active cohort with retained indices and unrounded cells",async()=>{
  const data=[[1e-8,2,3],[999,999,999],[4,5,6]];
  const w=table(data,{scientific_presentation:{kind:"spectral_dataset"}});
  await w.setProps({nodeOutput:{data,metadata:w.props('nodeOutput').metadata,presentation_value:{data,
    sample_axis:{labels:["A","excluded","C"],include_mask:[true,false,true]},
    feature_axis:{data:[1000.01,1000.02,1000.03],include_mask:[true,false,true]}}}});
  const text=await csv(w);
  expect(text).toContain("1000.01,1000.03");
  expect(text).toContain("1,A,1e-8,3"); expect(text).toContain("3,C,4,6");
  expect(text).not.toContain("999"); expect(text).not.toContain("1000.02");
  expect(w.vm.formatValue(1e-8,true)).toBe("1e-8");
});
