import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PrivateBatchUpload from '@/views/experiments/PrivateBatchUpload.vue';

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('@/api/client', () => ({ default: { get, post } }));
vi.mock('@/stores/project', () => ({ useProjectStore: () => ({ currentProjectId: 1 }) }));

function open() {
  return mount(PrivateBatchUpload, { props: { artifactUid: 'frozen-model' }, global: { stubs: { Button: true } } });
}

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue({ data: { privateBatchUpload: true, maxFiles: 2, maxRequestBytes: 2 * 1024 * 1024 } });
});

describe('Private prediction-only upload', () => {
  it('does not expose upload without the account capability', async () => {
    get.mockResolvedValue({ data: { privateBatchUpload: false } });
    const wrapper = open();
    await flushPromises();
    expect(wrapper.find('input[type=file]').exists()).toBe(false);
    expect(post).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it('uses server limits and discards a selection on model change', async () => {
    const wrapper = open();
    await flushPromises();
    const input = wrapper.get('input[type=file]');
    Object.defineProperty(input.element, 'files', { configurable: true, value: [
      new File(['1'], 'a.csv'), new File(['2'], 'b.csv'), new File(['3'], 'c.csv'),
    ] });
    await input.trigger('change');
    expect(wrapper.get('[role=alert]').text()).toContain('at most 2 files');
    await wrapper.setProps({ artifactUid: 'other-model' });
    await flushPromises();
    expect(wrapper.find('[role=alert]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('3 files');
    wrapper.unmount();
  });

  it('submits only the chosen files to the exact model and surfaces the persisted run', async () => {
    const wrapper = open();
    await flushPromises();
    const input = wrapper.get('input[type=file]');
    const file = new File(['x,y\n1,2\n'], 'private.csv');
    Object.defineProperty(input.element, 'files', { value: [file] });
    await input.trigger('change');
    post.mockResolvedValue({ data: { run_id: 9 } });
    get.mockResolvedValue({ data: { id: 9, status: 'running' } });
    await (wrapper.vm as unknown as { predict: () => Promise<void> }).predict();
    expect(post).toHaveBeenCalledWith('/runs/batch/files/frozen-model', expect.any(FormData), expect.any(Object));
    const body = post.mock.calls[0][1] as FormData;
    expect(body.getAll('files')).toEqual([file]);
    expect(wrapper.emitted('completed')?.[0]).toEqual([{ id: 9, status: 'running' }]);
    wrapper.unmount();
  });
});
