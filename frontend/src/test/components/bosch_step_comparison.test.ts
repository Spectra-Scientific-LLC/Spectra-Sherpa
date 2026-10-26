import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent } from "vue";
import BoschStepComparison from "@/views/data/BoschStepComparison.vue";

enableAutoUnmount(afterEach);
const mocks = vi.hoisted(() => ({ uploadFile: vi.fn(), get: vi.fn(), post: vi.fn() }));
vi.mock("@/api/client", () => ({ default: { get: mocks.get, post: mocks.post } }));
vi.mock("@/stores/data", () => ({ useDataStore: () => ({ uploadFile: mocks.uploadFile }) }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => ({ user: { id: 1 } }) }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => ({ currentProjectId: 6 }) }));
vi.mock("@/views/data/SelectedSpectraPlotPanel.vue", () => ({ default: defineComponent({
  name: "SelectedSpectraPlotPanel", props: ["plotDatasets", "minimumTraceCount", "plotDatasetCount", "plotFileCount"], template: "<div />",
}) }));
const files = [
  { id: 1, file_path: "raw/Day_2024_08_05.nc", stage: "raw", created_at: "2024-08-05" },
  { id: 2, file_path: "raw/Day_2024_08_07.nc", stage: "raw", created_at: "2024-08-07" },
  { id: 3, file_path: "raw/Process_data.nc", stage: "raw", created_at: "2024-08-07" },
];
const step = (step_id: string) => ({ step_id, label: step_id, acquisition_count: 20,
  intervals: [{ first_acquisition: 10, last_acquisition: 29, acquisition_count: 20,
    start_time: 1722864000, end_time: 1722864000.9 }] });
const catalog = { process_file_id: 3, source_sha256: "a".repeat(64), process_sha256: "b".repeat(64), date: "2024-08-05", lot: null,
  wafers: [1, 2].map(id => ({ asset_id: `Wafer_0${id}`, refusal: null,
    alignment: { correlation: .92, boundary_uncertainty_s: .2 }, steps: [step("etch"), step("passivation")] })),
  unrecorded_protocol_steps: ["Initial chamber preparation"], warnings: [] };
beforeEach(() => { vi.clearAllMocks(); mocks.get.mockResolvedValue({ data: catalog });
  mocks.post.mockResolvedValue({ data: { dataset: { data: [[1, 2]], n_samples: 1, n_features: 2 }, selected_acquisition_count: 20 } }); });

describe("BOSCH step comparison", () => {
  it("loads retained labels without offering upload controls in My Dataset", async () => {
    const wrapper = mount(BoschStepComparison, { props: { experimentId: 3, files: files.slice(0, 2) } });
    await flushPromises();
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(wrapper.find('input[type="file"]').exists()).toBe(false);
    expect(wrapper.find('[aria-label="Process companion"]').exists()).toBe(false);
  });
  it("requires the staged process companion in Upload", async () => {
    const wrapper = mount(BoschStepComparison, { props: { stagedFiles: [{
      staging_id: "a".repeat(32), filename: "Day_2024_08_05.nc", size_bytes: 10,
      format_id: "bosch-netcdf", variant: "oes", assets: [],
    }] } });
    await flushPromises();
    expect(mocks.post).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("Use Load to add Process_data.nc");
    expect(wrapper.emitted("prepared")?.at(-1)).toEqual([null]);
  });
  it("compares the same selected step across selected days and wafers", async () => {
    const wrapper = mount(BoschStepComparison, { props: { experimentId: 3, files } });
    await flushPromises();
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).toContain("Acquisition ranges (1-based)");
    await wrapper.findAll("button")[0].trigger("click");
    await wrapper.findAll("button")[2].trigger("click");
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledTimes(4);
    for (const [, body] of mocks.post.mock.calls) expect(body).toMatchObject({ process_file_id: 3, step_id: "etch", source_sha256: "a".repeat(64), max_rows: 4 });
    const plot = wrapper.findComponent({ name: "SelectedSpectraPlotPanel" });
    expect(plot.props("plotDatasets")).toHaveLength(1);
    expect(plot.props("plotDatasets")[0].members).toHaveLength(4);
    expect(plot.props("plotDatasetCount")).toBe(1);
    expect(plot.props("plotFileCount")).toBe(2);
    expect(plot.props("minimumTraceCount")).toBe(4);
    await wrapper.get('[aria-label="Processing steps to compare"]').setValue(["passivation"]);
    expect(plot.props("plotDatasets")).toEqual([]);
  });
  it("rejects a stale preview after the selected processing step changes", async () => {
    let resolve!: (value: unknown) => void;
    const wrapper = mount(BoschStepComparison, { props: { experimentId: 3, files } });
    await flushPromises();
    mocks.post.mockReturnValue(new Promise(done => { resolve = done; }));
    await wrapper.findAll("button")[0].trigger("click");
    await wrapper.findAll("button")[2].trigger("click");
    await wrapper.get('[aria-label="Processing steps to compare"]').setValue(["passivation"]);
    resolve({ data: { dataset: { data: [[1, 2]] } } });
    await flushPromises();
    expect(wrapper.findComponent({ name: "SelectedSpectraPlotPanel" }).props("plotDatasets")).toEqual([]);
    expect(mocks.post).toHaveBeenCalledTimes(1);
  });
});
