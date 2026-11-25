import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CustomNodesSettingsSection from '@/views/settings/CustomNodesSettingsSection.vue';

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock('@/api/client', () => ({ default: mocks }));

const state = (overrides: Record<string, unknown> = {}) => ({
  available: true,
  enabled: true,
  active: true,
  restart_required: false,
  folder: '/data/user/my_nodes',
  sources: [
    { source: 'whitaker-hayes', kind: 'folder', location: '/data/user/my_nodes/whitaker_hayes', version: '0.0.0', status: 'loaded', nodes: ['user.whitaker-hayes.despike'], message: null },
    { source: 'broken', kind: 'folder', location: '/data/user/my_nodes/broken', version: null, status: 'failed', nodes: [], message: 'SyntaxError: invalid syntax' },
  ],
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockResolvedValue({ data: state() });
  mocks.put.mockResolvedValue({ data: state({ enabled: false, restart_required: true }) });
});

describe('custom nodes settings', () => {
  it('lists loaded and failed sources with the My nodes folder', async () => {
    const wrapper = mount(CustomNodesSettingsSection);
    await flushPromises();
    expect(mocks.get).toHaveBeenCalledWith('/config/custom-nodes');
    expect(wrapper.text()).toContain('/data/user/my_nodes');
    expect(wrapper.text()).toContain('loaded: user.whitaker-hayes.despike');
    expect(wrapper.text()).toContain('not loaded: SyntaxError: invalid syntax');
    expect(wrapper.find('[role=status]').exists()).toBe(false);
    wrapper.unmount();
  });

  it('turns custom nodes off and says a restart is needed', async () => {
    const wrapper = mount(CustomNodesSettingsSection);
    await flushPromises();
    await wrapper.get('input[name=custom_nodes_enabled]').setValue(false);
    await flushPromises();
    expect(mocks.put).toHaveBeenCalledWith('/config/custom-nodes', { enabled: false });
    expect(wrapper.get('[role=status]').text()).toBe('Restart Spectra Sherpa to apply this change.');
    wrapper.unmount();
  });

  it('puts the box back when the change cannot be saved', async () => {
    mocks.put.mockRejectedValue(new Error('Read-only .env'));
    const wrapper = mount(CustomNodesSettingsSection);
    await flushPromises();
    const box = wrapper.get('input[name=custom_nodes_enabled]');
    await box.setValue(false);
    await flushPromises();
    expect(wrapper.get('[role=alert]').text()).toBe('Could not change this setting.');
    expect((box.element as HTMLInputElement).checked).toBe(true);
    wrapper.unmount();
  });

  it('shows nothing where custom nodes are unavailable', async () => {
    mocks.get.mockRejectedValue(new Error('Not found'));
    const wrapper = mount(CustomNodesSettingsSection);
    await flushPromises();
    expect(wrapper.html()).not.toContain('Custom nodes');
    wrapper.unmount();
  });
});
