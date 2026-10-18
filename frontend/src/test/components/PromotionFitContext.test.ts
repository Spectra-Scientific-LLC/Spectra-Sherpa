import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import api from '@/api/client';
import Context from '@/components/PromotionFitContext.vue';
vi.mock('@/api/client', () => ({ default: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
beforeEach(() => vi.clearAllMocks());
describe('final fitting workflow context', () => {
  it('shows verified source population without executing or expanding it', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { workflow_id: 2, source_run_id: 4, population: { fitted_count: 174, held_out_count: 57 }, fitting_plan: { state: 'complete_declared_development_fit', declared_development_count: 174 } } });
    const wrapper = mount(Context, { props: { artifactUid: 'model', workflowId: 2, sourceRunId: 4 } });
    await flushPromises();
    expect(wrapper.text()).toContain('all 174 declared development samples');
    expect(wrapper.text()).toContain('held-out samples: 57');
    expect(wrapper.text()).toContain('not a pinned replay');
    expect(wrapper.text()).toContain('has not started a fit');
    expect(api.post).not.toHaveBeenCalled(); expect(api.patch).not.toHaveBeenCalled();
  });
  it('refuses a mismatched run context rather than displaying trusted population counts', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { workflow_id: 2, source_run_id: 5, population: { fitted_count: 174, held_out_count: 57 } } });
    const wrapper = mount(Context, { props: { artifactUid: 'model', workflowId: 2, sourceRunId: 4 } });
    await flushPromises();
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
    expect(wrapper.text()).not.toContain('Fitted samples: 174');
    expect(api.post).not.toHaveBeenCalled();
  });
});
