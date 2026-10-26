import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils';
import { afterEach, expect, it, vi } from 'vitest';
import Filter from '@/views/data/ProcessingStepFilter.vue';
import type { ExperimentFile } from '@/types';
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('@/api/client', () => ({default: api}));
enableAutoUnmount(afterEach);
it('opens above preview with no selection, updates on toggles and clears when the file changes', async () => {
  api.get.mockImplementation(async (url: string) => ({data: url.endsWith('time-series-portfolios') ? [] : {
    date:'2024-08-05', process_file_id:4, source_sha256:'a', process_sha256:'b',
    wafers:[{asset_id:'Wafer_01', steps:[{step_id:'gas1_plasma',label:'Gas1',intervals:[],acquisition_count:10}]}],
  }}));
  api.post.mockResolvedValue({data:{dataset:{data:[[1,2]]}}});
  const wrapper = mount(Filter,{props:{experimentId:4,projectId:6,scopeKey:'6:4',fileSelections:{4:null},files:[{id:5,file_path:'Day_2024_08_05.nc'} as ExperimentFile]}});
  await flushPromises();
  expect(wrapper.get('details').attributes()).toHaveProperty('open');
  expect(wrapper.get('summary').text()).toContain('Steps Selection');
  expect(wrapper.find('[aria-pressed="true"]').exists()).toBe(false);
  expect(api.post).not.toHaveBeenCalled();
  await wrapper.get('button[aria-pressed]').trigger('click');
  await flushPromises();
  const selected = wrapper.emitted('preview')!.at(-1)![0] as any[];
  expect(selected[0].members[0].curveGroupColor).toBeTruthy();
  expect(wrapper.get('button[aria-pressed]').attributes('style')).toContain('background-color:');
  await wrapper.get('button[aria-pressed]').trigger('click');
  await flushPromises();
  expect(wrapper.emitted('preview')!.at(-1)![0]).toEqual([]);
  await wrapper.setProps({files:[{id:6,file_path:'Day_2024_08_07.nc'} as ExperimentFile]});
  await flushPromises();
  expect(wrapper.find('[aria-pressed="true"]').exists()).toBe(false);
});
