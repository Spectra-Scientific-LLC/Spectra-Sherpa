import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { defineComponent } from 'vue';
import Matrix from '@/views/data/BoschMatrixPrototype.vue';
enableAutoUnmount(afterEach);
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('@/api/client', () => ({ default: api }));
vi.mock('vue-router', () => ({ useRoute: () => ({ query: { experimentId: '4' } }) }));
vi.mock('@/views/data/SelectedSpectraPlotPanel.vue', () => ({ default: defineComponent({ name: 'Plot', props: ['plotDatasets'], template: '<div />' }) }));
const step = (id: string) => ({ step_id: id, label: id, acquisition_count: 10, intervals: [{ first_acquisition: 1, last_acquisition: 10, start_time: 100, end_time: 101, acquisition_count: 10 }] });
beforeEach(() => {
 vi.clearAllMocks();
 api.get.mockImplementation(async (url: string) => ({ data: url.includes('time-series-portfolios') ? [] : url.endsWith('/files') ? [{ id: 5, file_path: 'raw/Day_2024_08_05.nc' }] : { date: '2024-08-05', process_file_id: 4, source_sha256: 'a'.repeat(64), process_sha256: 'b'.repeat(64), warnings: [], wafers: [{ asset_id: 'Wafer_01', refusal: null, alignment: {}, steps: ['etch','passivation','gas1_plasma','mixed_plasma','break'].map(step) }] } }));
 api.post.mockResolvedValue({ data: { dataset: { data: [[1, 2]] } } });
});
it('offers only recorded plasma selections, with no automatic wafer or break selection', async () => {
 const wrapper=mount(Matrix); await flushPromises();
 expect(wrapper.findAll('[aria-pressed="false"]')).toHaveLength(3);
 expect(wrapper.findAll('[aria-pressed="true"]')).toHaveLength(0);
 expect(wrapper.findAll('button').some(b => b.attributes('aria-label')?.includes('Break'))).toBe(false);
 expect(wrapper.text()).toContain('No identified interval');
 await wrapper.get('[aria-label="2024-08-05, Post-production plasma, Wafer_01"]').trigger('click');
 await wrapper.findAll('button').find(b => b.text()==='Preview selected spectra')!.trigger('click');
 await flushPromises();
 expect(api.post).toHaveBeenCalledTimes(1);
 expect(api.post.mock.calls[0][1]).toMatchObject({ step_id: 'gas1_plasma', asset_id: 'Wafer_01', process_file_id: 4, max_rows: 4 });
 expect(wrapper.findComponent({ name: 'Plot' }).props('plotDatasets')[0].members).toHaveLength(1);
});
it('keeps production phases separate in original-spectrum previews', async () => {
 const wrapper=mount(Matrix); await flushPromises();
 await wrapper.get('[aria-label="2024-08-05, Production etch, Wafer_01"]').trigger('click');
 await wrapper.findAll('button').find(b => b.text()==='Preview selected spectra')!.trigger('click');
 await flushPromises();
 expect(api.post.mock.calls.map(c => c[1].step_id)).toEqual(['etch','passivation']);
});
