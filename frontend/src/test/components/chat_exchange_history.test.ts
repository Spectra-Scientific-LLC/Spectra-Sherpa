import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChatExchangeHistory from '@/components/ChatExchangeHistory.vue';
import api from '@/api/client';
import { downloadText } from '@/utils/download';

vi.mock('@/api/client', () => ({ default: { get: vi.fn(), delete: vi.fn() } }));
vi.mock('@/utils/download', () => ({ downloadText: vi.fn() }));
const entry = {
  id: 'one', timestamp: '2026-10-01', provider: 'ollama', model: 'test', status: 'failed',
  duration_ms: 100, usage: null, truncated: false, response: 'Partial answer',
  request: JSON.stringify({ messages: [{ role: 'user', content: 'Explain PCA' }], system: 'Be concise' }),
};
const create = () => mount(ChatExchangeHistory, {
  global: { stubs: { Button: { props: ['label', 'disabled'], template: '<button :disabled="disabled">{{ label }}</button>' } } },
});

describe('local exchange history', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.get).mockResolvedValue({ data: { exchanges: [entry] } }); });
  it('shows actual instructions, incomplete outcome and missing usage; saves the same record', async () => {
    const wrapper = create(); await flushPromises();
    expect(wrapper.text()).toContain('Explain PCA');
    expect(wrapper.text()).toContain('Be concise');
    expect(wrapper.text()).toContain('failed');
    expect(wrapper.text()).toContain('Not supplied by provider');
    await wrapper.findAll('button').find(b => b.text() === 'Save exchange')!.trigger('click');
    expect(downloadText).toHaveBeenCalledWith(JSON.stringify(entry, null, 2), 'sherpa-exchange-one.json', 'application/json');
    vi.mocked(api.delete).mockResolvedValue({});
    await wrapper.findAll('button').find(b => b.text() === 'Clear exchanges')!.trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('No exchanges recorded');
  });
  it('discloses truncated requests instead of inventing their contents', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { exchanges: [{ ...entry, truncated: true, request: '{' }] } });
    const wrapper = create(); await flushPromises();
    expect(wrapper.text()).toContain('not a complete exchange');
    expect(wrapper.text()).toContain('Request record truncated');
  });
  it('shows request failure explicitly', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('offline'));
    const wrapper = create(); await flushPromises();
    expect(wrapper.find('[role="alert"]').text()).toBe('Unable to load local exchanges.');
  });
});
