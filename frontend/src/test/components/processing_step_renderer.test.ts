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

it("changes one wafer's phase without selecting other wafers and defaults to Both", async () => {
  const full = structuredClone(entry);
  full.catalog.wafers[0].steps.push({step_id:'passivation',intervals:[],acquisition_count:3} as never);
  full.catalog.wafers.push({...full.catalog.wafers[0],asset_id:'Wafer_02'});
  const wrapper = mount(Matrix,{props:{entries:[full],modelValue:[]}});
  expect(wrapper.text()).toContain('BOSCH production');
  expect(wrapper.findAll('select').map(s => (s.element as HTMLSelectElement).value)).toEqual(['production','production']);
  await wrapper.findAll('button')[0].trigger('click');
  await wrapper.setProps({modelValue:wrapper.emitted('update:modelValue')!.at(-1)![0] as never});
  await wrapper.findAll('select')[0].setValue('etch');
  const chosen = wrapper.emitted('update:modelValue')!.at(-1)![0] as any[];
  expect(chosen).toHaveLength(1);
  expect(chosen[0].step_id).toBe('etch');
  await wrapper.setProps({modelValue:chosen as never});
  expect((wrapper.findAll('select')[1].element as HTMLSelectElement).value).toBe('production');
  expect(wrapper.findAll('button')[0].attributes('aria-pressed')).toBe('true');
  await wrapper.findAll('button')[0].trigger('click');
  expect(wrapper.emitted('update:modelValue')!.at(-1)![0]).toEqual([]);
});
