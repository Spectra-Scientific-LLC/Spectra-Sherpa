import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createRouter, createMemoryHistory } from 'vue-router';
import { createPinia, setActivePinia } from 'pinia';
import api from '@/api/client';
import Saved from '@/components/SavedPairedEvaluation.vue';
import Panel from '@/components/PairedEvaluationPanel.vue';
vi.mock('@/components/ScientificComparison.vue', () => ({default: {props: ['evidence'], template: '<div class="shared-comparison">{{evidence.items[0].label}}</div>'}}));
vi.mock('@/api/client', () => ({ default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
const record = {
  schema_version: 'spectrasherpa-paired-evaluation/1', protocol: { recipes: [{run_id: 1, model_node_id: 'pls'}, {run_id: 2, model_node_id: 'pls'}] },
  protocol_digest: 'protocol-receipt', population: {development_count: 174, held_out_count: 57}, splits: [{digest: 'fold-receipt'}],
  paired_rmsecv_differences: [-0.2], results: [{execution: {metrics: {rmse: 1.2}}}, {execution: {metrics: {rmse: 1}}}],
  summary: {right_meaningfully_better: 1, left_meaningfully_better: 0, within_margin: 0}, interpretation: 'Development evidence, not independent validation.',
};
beforeEach(() => { setActivePinia(createPinia()); vi.resetAllMocks(); vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });
async function launch() {
  const router = createRouter({history: createMemoryHistory(), routes: [{path: '/', component: {template: '<div/>'}}, {path: '/runs/:runId', component: {template: '<div/>'}}]});
  await router.push('/'); await router.isReady();
  const wrapper = mount(Panel, {props: {recipes: [{run_id: 1, model_node_id: 'pls', label: 'First'}, {run_id: 2, model_node_id: 'pls', label: 'Second'}]}, global: {plugins: [router]}});
  vi.mocked(api.post).mockResolvedValueOnce({data: {development_count: 174, held_out_count: 57, fits: 10}}).mockResolvedValueOnce({data: {run_id: 81, job_id: 12}});
  await wrapper.findAll('button').find(b => b.text() === 'Review evaluation protocol')!.trigger('click'); await flushPromises();
  await wrapper.findAll('button').find(b => b.text() === 'Run evaluation')!.trigger('click'); await flushPromises();
  return {wrapper, router};
}
describe('saved paired evaluation journey', () => {
  it('requests a selected repetition for the shared OOF comparison without refitting', async () => {
    const repeated = {...record, paired_rmsecv_differences: [-.2, -.1]};
    vi.mocked(api.get).mockResolvedValueOnce({data: {status: 'completed', record: repeated, scientific_comparison: {items: [{label: 'Repetition 1'}]}}})
      .mockResolvedValueOnce({data: {status: 'completed', record: repeated, scientific_comparison: {items: [{label: 'Repetition 2'}]}}});
    const wrapper = mount(Saved, {props: {runId: 81}}); await flushPromises();
    expect(wrapper.get('.shared-comparison').text()).toBe('Repetition 1');
    await wrapper.get('select').setValue('1'); await flushPromises();
    expect(api.get).toHaveBeenLastCalledWith('/runs/paired-evaluations/81', {params: {repetition: 1}, signal: expect.any(AbortSignal)});
    expect(wrapper.get('.shared-comparison').text()).toBe('Repetition 2'); expect(api.post).not.toHaveBeenCalled(); wrapper.unmount();
  });

  it('reopens the exact completed record after remount without fitting again', async () => {
    vi.mocked(api.get).mockResolvedValue({data: {status: 'completed', record}});
    const first = mount(Saved, {props: {runId: 81}}); await flushPromises();
    expect(first.text()).toContain('174'); expect(first.text()).toContain('fold-receipt'); first.unmount();
    const reopened = mount(Saved, {props: {runId: 81}}); await flushPromises();
    expect(reopened.text()).toContain('Run #1 · pls'); expect(reopened.text()).toContain('1.2000');
    expect(api.get).toHaveBeenCalledTimes(2); expect(api.post).not.toHaveBeenCalled(); reopened.unmount();
  });
  it('polls a saved running job and displays terminal failure with restart guidance', async () => {
    vi.mocked(api.get).mockResolvedValueOnce({data: {status: 'running'}}).mockResolvedValueOnce({data: {status: 'failed', error: 'Fold rank infeasible'}});
    const wrapper = mount(Saved, {props: {runId: 81}}); await flushPromises();
    expect(wrapper.text()).toContain('running'); await vi.advanceTimersByTimeAsync(1500); await flushPromises();
    expect(wrapper.text()).toContain('Fold rank infeasible'); expect(wrapper.text()).toContain('resume is unavailable');
    await vi.advanceTimersByTimeAsync(3000); expect(api.get).toHaveBeenCalledTimes(2); wrapper.unmount();
  });
  it('shows polling errors and retries saved evidence without starting new work', async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error('Connection interrupted')).mockResolvedValueOnce({data: {status: 'completed', record}});
    const wrapper = mount(Saved, {props: {runId: 81}}); await flushPromises(); expect(wrapper.get('[role="alert"]').text()).toContain('Connection interrupted');
    await wrapper.get('button').trigger('click'); await flushPromises(); expect(wrapper.text()).toContain('1.2000'); expect(api.post).not.toHaveBeenCalled(); wrapper.unmount();
  });
  it('opens the retained run and does not falsely claim cancellation when cancellation fails', async () => {
    vi.mocked(api.get).mockResolvedValue({data: {status: 'running'}});
    vi.mocked(api.delete).mockRejectedValue(new Error('Cancellation denied'));
    const {wrapper, router} = await launch();
    await wrapper.findAll('button').find(b => b.text() === 'Cancel evaluation')!.trigger('click'); await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain('Cancellation denied'); expect(wrapper.text()).toContain('Evaluation running');
    await wrapper.findAll('button').find(b => b.text() === 'Open saved evaluation')!.trigger('click'); await flushPromises(); expect(router.currentRoute.value.path).toBe('/runs/81');
    wrapper.unmount(); await vi.advanceTimersByTimeAsync(3000); expect(api.get).toHaveBeenCalledTimes(1);
  });
});
