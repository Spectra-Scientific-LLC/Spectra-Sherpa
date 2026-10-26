import { enableAutoUnmount, mount } from "@vue/test-utils";
import { afterEach, expect, it } from "vitest";
import Matrix from "@/views/data/BoschStepMatrix.vue";
import type { StepEntry } from "@/views/data/composables/useProcessingStepSelection";
enableAutoUnmount(afterEach);
const entry = {
  experimentId: 4,
  file: { id: 5, file_path: "raw/Day_2024_08_05.nc" },
  catalog: {
    date: "2024-08-05",
    process_file_id: 6,
    wafers: [
      {
        asset_id: "Wafer_01",
        steps: [
          { step_id: "etch", intervals: [], acquisition_count: 10 },
          { step_id: "break", intervals: [], acquisition_count: 2 },
        ],
      },
    ],
  },
} as StepEntry;
it("renders selections without its own workflow, upload, save or preview controls", async () => {
  const wrapper = mount(Matrix, { props: { entries: [entry], modelValue: [] } });
  expect(wrapper.findAll("button")).toHaveLength(1);
  expect(wrapper.find("input").exists()).toBe(false);
  expect(wrapper.find("h1,h2").exists()).toBe(false);
  expect(wrapper.find('[aria-pressed="true"]').exists()).toBe(false);
  await wrapper.get("button").trigger("click");
  expect(wrapper.emitted("update:modelValue")![0][0]).toEqual([
    {
      experiment_id: 4,
      file_id: 5,
      process_file_id: 6,
      asset_id: "Wafer_01",
      step_id: "production",
    },
  ]);
  expect(wrapper.find('[aria-pressed="true"]').exists()).toBe(false);
  await wrapper.setProps({ modelValue: wrapper.emitted("update:modelValue")![0][0] as never });
  expect(wrapper.find('[aria-pressed="true"]').exists()).toBe(true);
  await wrapper.get("button").trigger("click");
  expect(wrapper.emitted("update:modelValue")![1][0]).toEqual([]);
});
