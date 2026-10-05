import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import WatchDryRun from '@/views/deploy/WatchDryRun.vue';
import api from '@/api/client';
import { downloadText } from '@/utils/download';
vi.mock('@/api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
vi.mock('@/utils/download', () => ({ downloadText: vi.fn() }));
const receipt = { status: 'completed', run_id: 5, checked_at: '2026-10-01', folder: '/incoming', pattern: '*.csv', result_preview: { y_pred: [2.5] } };
const create = () => mount(WatchDryRun, { props: { watchId: 3 }, global: { stubs: {
  Button: { props: ['label', 'disabled'], template: '<button :disabled="disabled">{{ label }}</button>' },
} } });
describe('ordinary saved-model dry run', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.get).mockResolvedValue({ data: { receipt: null } }); });
  it('shows and exports the actual saved prediction without enabling monitoring', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: receipt });
    const view = create(); await flushPromises();
    await view.find('input').setValue('sample.csv'); await view.find('button').trigger('click'); await flushPromises();
    expect(api.post).toHaveBeenCalledExactlyOnceWith('/deploy/watches/3/dry-run', { file_name: 'sample.csv' });
    expect(view.text()).toContain('2.5'); expect(view.text()).toContain('Saved run #5');
    await view.findAll('button')[1].trigger('click');
    expect(downloadText).toHaveBeenCalledWith(JSON.stringify(receipt, null, 2), 'watch-3-dry-run.json', 'application/json');
  });
  it('discloses historical settings without requiring requalification', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { receipt: { ...receipt, matches_current_settings: false, last_activated_at: '2026-10-02' } } });
    const view = create(); await flushPromises();
    expect(view.find('[role="alert"]').text()).toContain('earlier watch settings');
    expect(view.text()).not.toContain('then close this panel and enable');
    expect(view.text()).toContain('optional check does not determine whether the watch can run');
  });
  it('blocks a new check until loading completes, preventing stale load overwrite', async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(api.get).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const view = create(); await view.find('input').setValue('sample.csv');
    expect(view.find('button').attributes('disabled')).toBeDefined();
    finish({ data: { receipt: null } }); await flushPromises();
    expect(view.find('button').attributes('disabled')).toBeUndefined();
  });
  it('shows an actionable refused check', async () => {
    vi.mocked(api.post).mockRejectedValue({ response: { data: { detail: 'Choose a settled file.' } } });
    const view = create(); await flushPromises();
    await view.find('input').setValue('missing.csv'); await view.find('button').trigger('click'); await flushPromises();
    expect(view.find('[role="alert"]').text()).toBe('Choose a settled file.');
  });
});
