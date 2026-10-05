import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/api/client";
import MultiWellAcquisitionPanel from "@/views/data/MultiWellAcquisitionPanel.vue";

const toastAdd = vi.fn();
let capabilityDisabled = false;

vi.mock("@/api/client", () => ({
  default: { get: vi.fn(), put: vi.fn() },
}));

vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));
vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({ isCapabilityDisabled: () => capabilityDisabled }),
}));

const plan = {
  schema_version: "spectrasherpa-acquisition-plan/3" as const,
  experiment_id: 12,
  plate_format_id: "plate-96" as const,
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
  ],
  acquisition_order: [],
  matching: { rules: {}, matches: [] },
};

describe("MultiWellAcquisitionPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capabilityDisabled = false;
    vi.mocked(api.get).mockImplementation((url: string) =>
      Promise.resolve({
        data: url.includes("presets")
          ? []
          : url === "/acquisition-preferences"
            ? { default_plate_format_id: "plate-96" }
            : plan,
      }),
    );
    vi.mocked(api.put).mockResolvedValue({ data: plan });
  });

  it("loads and saves the complete multi-well experiment contract", async () => {
    const wrapper = shallowMount(MultiWellAcquisitionPanel, {
      props: {
        experimentId: 12,
        experimentName: "Lavender",
        experimentOptions: [{ id: 12, name: "Lavender" }],
      },
    });
    await flushPromises();

    expect(api.get).toHaveBeenCalledWith("/experiments/12/acquisition-plan");
    expect(wrapper.text()).toContain("1/96");
    expect(wrapper.text()).toContain("Measured rows changed");
    expect(wrapper.text()).toContain("0");

    wrapper.findComponent({ name: "PlateMap96Well" }).vm.$emit("well-click", "A02");
    await wrapper.vm.$nextTick();
    const save = wrapper.find('button-stub[label="Save acquisition plan"]');
    expect(save.exists()).toBe(true);
    await save.trigger("click");
    await flushPromises();

    expect(api.put).toHaveBeenCalledWith("/experiments/12/acquisition-plan", {
      plate_format_id: "plate-96",
      expected_revision: "a".repeat(64),
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
          well_position: "A02",
          planned_sample_label: null,
          sample_id: null,
          mixture_id: null,
          factor_values: {},
        },
      ],
      acquisition_order: [],
      matching: { rules: {}, matches: [] },
    });
    expect(toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Acquisition plan saved" }),
    );
  });

  it("switches datasets through the owning Data workspace", async () => {
    const wrapper = shallowMount(MultiWellAcquisitionPanel, {
      props: {
        experimentId: null,
        experimentOptions: [{ id: 21, name: "Corn" }],
      },
    });

    wrapper.findComponent({ name: "Dropdown" }).vm.$emit("update:modelValue", 21);
    expect(wrapper.emitted("selectExperiment")).toEqual([[21]]);
    expect(api.get).not.toHaveBeenCalled();
  });

  it("keeps a failed save draft available for retry", async () => {
    vi.mocked(api.put)
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce({ data: plan });
    const wrapper = shallowMount(MultiWellAcquisitionPanel, {
      props: {
        experimentId: 12,
        experimentName: "Lavender",
        experimentOptions: [{ id: 12, name: "Lavender" }],
      },
    });
    await flushPromises();

    wrapper.findComponent({ name: "PlateMap96Well" }).vm.$emit("well-click", "A02");
    await wrapper.find('button-stub[label="Save acquisition plan"]').trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("temporary failure");
    expect(wrapper.findComponent({ name: "PlateMap96Well" }).exists()).toBe(true);
    await wrapper.find('button-stub[label="Retry save"]').trigger("click");
    await flushPromises();
    expect(api.put).toHaveBeenCalledTimes(2);
    expect(api.get).toHaveBeenCalledTimes(3);
  });

  it("shows a read-only plan when authoring is disabled by the demo contract", async () => {
    capabilityDisabled = true;
    const wrapper = shallowMount(MultiWellAcquisitionPanel, {
      props: {
        experimentId: 12,
        experimentName: "Lavender",
        experimentOptions: [{ id: 12, name: "Lavender" }],
      },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("read-only in the current profile");
    expect(wrapper.find('button-stub[label="Save acquisition plan"]').exists()).toBe(false);
    expect(wrapper.findComponent({ name: "PlateMap96Well" }).props("interactive")).toBe(false);
  });
});
