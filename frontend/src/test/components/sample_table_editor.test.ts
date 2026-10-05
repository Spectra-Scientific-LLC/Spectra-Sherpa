import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/api/client";
import SampleTableEditor, {
  type SampleTableSavePayload,
} from "@/components/data/SampleTableEditor.vue";

vi.mock("@/api/client", () => ({
  default: { get: vi.fn() },
}));

const plan = {
  schema_version: "spectrasherpa-acquisition-plan/3",
  experiment_id: 12,
  plate_format_id: "plate-96",
  plate_format_label: "96-well plate",
  capacity: 96,
  revision: "a".repeat(64),
  samples: [],
  mixtures: [],
  factors: [],
  wells: [
    {
      well_position: "A01",
      planned_sample_label: null,
      sample_id: null,
      mixture_id: null,
      factor_values: {},
    },
    {
      well_position: "B02",
      planned_sample_label: null,
      sample_id: null,
      mixture_id: null,
      factor_values: {},
    },
  ],
  acquisition_order: [],
  matching: { rules: {}, matches: [] },
};

const measured = {
  schema_version: "spectrasherpa.sample-table-editor/1",
  source_file_id: 41,
  revision: "b".repeat(64),
  sample_table_file_id: 73,
  selected_target: "class",
  target_definitions: [{ name: "class", type: "categorical" }],
  annotation_columns: ["batch"],
  plate_format_id: "plate-96",
  rows: [
    {
      row_index: 0,
      source_file_id: 41,
      sample_id: "lavender-1",
      include: false,
      targets: { class: "healthy" },
      plate_id: "",
      well: "",
      annotations: { batch: "day-1" },
    },
    {
      row_index: 1,
      source_file_id: 41,
      sample_id: "lavender-2",
      include: true,
      targets: { class: "stressed" },
      plate_id: "",
      well: "",
      annotations: { batch: "day-2" },
    },
  ],
};

describe("SampleTableEditor acquisition-plan synchronization", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.get).mockImplementation((url: string) =>
      Promise.resolve({ data: url.includes("acquisition-plan") ? plan : measured }),
    );
  });

  it("previews differences before applying the acquisition matching proposal", async () => {
    const wrapper = shallowMount(SampleTableEditor, {
      props: {
        sampleCount: 2,
        sampleLabels: ["source-1", "source-2"],
        sourceFileId: 41,
        sourceName: "Lavender",
        experimentId: 12,
        analysisBinding: {
          revision: measured.revision,
          sample_table_file_id: 73,
          selected_target: "class",
          target_type: "categorical",
        },
      },
      global: {
        stubs: {
          Dialog: { template: "<div><slot /><slot name='footer' /></div>" },
          DataTable: { template: "<div><slot /></div>" },
        },
      },
    });

    await wrapper.find('button-stub[label="Edit measured samples"]').trigger("click");
    await flushPromises();

    expect(api.get).toHaveBeenCalledWith("/builder/analysis-binding/41");
    expect(api.get).toHaveBeenCalledWith("/experiments/12/acquisition-plan");
    expect(wrapper.find('tag-stub[value="2 planned"]').exists()).toBe(true);
    expect(wrapper.find('tag-stub[value="Publication needed"]').exists()).toBe(true);
    await wrapper.find('button-stub[label="Use acquisition plan"]').trigger("click");
    expect(wrapper.text()).toContain("Build a proposed measured-sample table");
    await wrapper.find('button-stub[label="Preview differences"]').trigger("click");
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain("Proposed measured samples");
    expect(wrapper.text()).toContain("2 field changes across 2 rows");
    await wrapper.find('button-stub[label="Apply proposal"]').trigger("click");
    await wrapper.vm.$nextTick();

    const preview = wrapper.findComponent({ name: "PlateMap96Well" });
    const wells = preview.props("wells");
    expect(wells.map((well: { well_position: string }) => well.well_position)).toEqual([
      "A01",
      "B02",
    ]);
    expect(wells[0]).toMatchObject({
      label: "lavender-1",
      excluded: true,
      details: expect.arrayContaining([
        { label: "class (categorical)", value: "healthy" },
        { label: "batch", value: "day-1" },
      ]),
    });
    expect(wrapper.find('tag-stub[value="Plan and measured samples synchronized"]').exists()).toBe(
      true,
    );
  });

  it("shows save failures and refreshes only the binding revision before retry", async () => {
    const wrapper = shallowMount(SampleTableEditor, {
      props: {
        sampleCount: 2,
        sampleLabels: ["source-1", "source-2"],
        sourceFileId: 41,
        sourceName: "Lavender",
        experimentId: 12,
        analysisBinding: {
          revision: measured.revision,
          sample_table_file_id: 73,
          selected_target: "class",
          target_type: "categorical",
        },
        saveError: "Measured samples changed since this editor opened.",
        saveConflict: true,
      },
      global: {
        stubs: {
          Dialog: { template: "<div><slot /><slot name='footer' /></div>" },
          DataTable: { template: "<div><slot /></div>" },
        },
      },
    });

    await wrapper.find('button-stub[label="Edit measured samples"]').trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("Measured samples changed since this editor opened.");

    vi.mocked(api.get).mockImplementation((url: string) =>
      Promise.resolve({
        data: url.includes("acquisition-plan")
          ? plan
          : url.endsWith("/revision")
            ? { revision: null }
            : measured,
      }),
    );
    await wrapper.find('button-stub[label="Refresh binding"]').trigger("click");
    await flushPromises();

    expect(wrapper.emitted("clearSaveError")).toHaveLength(2);
    expect(wrapper.text()).toContain("Your edits are unchanged");
    await wrapper.find('button-stub[label="Review publication"]').trigger("click");
    expect(wrapper.emitted("save")).toBeUndefined();
    expect(wrapper.text()).toContain("Publish a new immutable measured-sample version");
    await wrapper.find('button-stub[label="Publish new immutable version"]').trigger("click");
    const payload = wrapper.emitted("save")?.at(-1)?.[0] as SampleTableSavePayload;
    expect(payload.expectedRevision).toBeNull();
    expect(payload.summary.includedSamples).toBe(1);
  });

  it("offers revision recovery when an unbound draft conflicts with a new binding", async () => {
    const wrapper = shallowMount(SampleTableEditor, {
      props: {
        sampleCount: 2,
        sampleLabels: ["source-1", "source-2"],
        sourceFileId: 41,
        sourceName: "Lavender",
        experimentId: 12,
        saveError: "Measured samples changed since this editor opened.",
        saveConflict: true,
      },
      global: {
        stubs: {
          Dialog: { template: "<div><slot /><slot name='footer' /></div>" },
          DataTable: { template: "<div><slot /></div>" },
        },
      },
    });

    await wrapper.find('button-stub[label="Edit measured samples"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('button-stub[label="Refresh binding"]').exists()).toBe(true);

    vi.mocked(api.get).mockResolvedValueOnce({ data: { revision: "c".repeat(64) } });
    await wrapper.find('button-stub[label="Refresh binding"]').trigger("click");
    await flushPromises();
    expect(api.get).toHaveBeenCalledWith("/builder/analysis-binding/41/revision");
    expect(wrapper.text()).toContain("Your edits are unchanged");
  });
});
