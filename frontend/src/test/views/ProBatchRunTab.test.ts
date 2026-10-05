import { flushPromises, mount } from '@vue/test-utils';
import { reactive } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BatchRunTab from '@/views/experiments/BatchRunTab.vue';
const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), toast: vi.fn(), project: null as any }));
vi.mock('@/api/client', () => ({ default: { get: mocks.get, post: mocks.post } }));
vi.mock('@/stores/project', () => ({ useProjectStore: () => mocks.project }));
vi.mock('@/composables/useAppConfig', () => ({ useAppConfig: () => ({ siteProfile: { value: 'pro' } }) }));
vi.mock('primevue/usetoast', () => ({ useToast: () => ({ add: mocks.toast }) }));
const select = {
  props: ['modelValue', 'options', 'optionValue', 'optionLabel', 'inputId', 'disabled'],
  emits: ['update:modelValue'],
  template: `<select :id="inputId" :disabled="disabled" :value="modelValue" @change="$emit('update:modelValue', options.find(o => String(o[optionValue]) === $event.target.value)[optionValue])"><option value="">Choose</option><option v-for="o in options" :key="o[optionValue]" :value="o[optionValue]">{{o[optionLabel]}}</option></select>`,
};
const multi = {
  ...select,
  template: `<select :id="inputId" multiple :disabled="disabled" @change="$emit('update:modelValue', Array.from($event.target.selectedOptions).map(o => o.value))"><option v-for="o in options" :key="o[optionValue]" :value="o[optionValue]">{{o[optionLabel]}}</option></select>`,
};
function open() {
  return mount(BatchRunTab, { props: { artifacts: [{ artifact_uid: 'm1', name: 'Calibrated model', model_type: 'pca', n_features: 3 }] }, global: { stubs: {
    Dropdown: select, MultiSelect: multi, InputText: true, PrivateBatchUpload: true,
    Button: { props: ['label', 'disabled'], template: '<button :disabled="disabled">{{label}}</button>' },
  } } });
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.project = reactive({ currentProjectId: 3 });
  mocks.get.mockImplementation(async (url: string) => ({ data:
    url === '/experiments' ? [{ id: 4, name: 'Synthetic spectra' }] :
    url.endsWith('/scientific-assets') ? { assets: [{ asset_id: 'single', shape: [12, 3] }] } :
    url.endsWith('/files') ? [{ id: 5 }] : { id: 4, metadata: { n_features: 3 } },
  }));
  mocks.post.mockResolvedValue({ data: { status: 'completed', run: { id: 9, name: 'Saved batch' }, results: [{ status: 'completed' }] } });
});
async function choose(wrapper: ReturnType<typeof open>) {
  await flushPromises();
  await wrapper.get('#batch-models').setValue(['m1']);
  await wrapper.get('#batch-dataset').setValue('4');
  await flushPromises();
}
describe('Pro durable batch journey', () => {
  it('submits exact models, dataset and population, then exposes the saved run', async () => {
    const wrapper = open();
    await choose(wrapper);
    await wrapper.get('#batch-scope').setValue('test');
    await wrapper.get('button').trigger('click');
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith('/runs/batch', {
      artifact_uids: ['m1'], dataset: { experiment_id: 4, stage: 'raw', asset_id: null },
      scope: 'test', run_name: 'Batch prediction — 1 model',
    });
    expect(wrapper.emitted('completed')).toEqual([[{ id: 9, name: 'Saved batch' }]]);
    wrapper.unmount();
  });
  it('preserves the synthetic stage inspected before submission', async () => {
    const original = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((url: string, options: any) => url.endsWith('/files') && options?.params?.stage === 'raw' ? Promise.resolve({ data: [] }) : original(url, options));
    const wrapper = open();
    await choose(wrapper);
    await wrapper.get('button').trigger('click');
    await flushPromises();
    expect(mocks.post.mock.calls[0][1].dataset.stage).toBe('synthetic');
    wrapper.unmount();
  });
  it('discloses partial failure and preserves its saved run identity', async () => {
    mocks.post.mockResolvedValue({ data: { status: 'partial', run: { id: 9, name: 'Partial batch' }, results: [{ status: 'failed' }] } });
    const wrapper = open();
    await choose(wrapper);
    await wrapper.get('button').trigger('click');
    await flushPromises();
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({ severity: 'warn', summary: 'Batch run partially saved' }));
    expect(wrapper.emitted('completed')?.[0][0]).toEqual({ id: 9, name: 'Partial batch' });
    wrapper.unmount();
  });
  it('does not attach a late saved run to a newly selected project', async () => {
    let finish: (v: any) => void = () => {};
    mocks.post.mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const wrapper = open();
    await choose(wrapper);
    await wrapper.get('button').trigger('click');
    mocks.project.currentProjectId = 6;
    await flushPromises();
    finish({ data: { status: 'completed', run: { id: 9 }, results: [] } });
    await flushPromises();
    expect(wrapper.emitted('completed')).toBeUndefined();
    expect(mocks.toast).not.toHaveBeenCalled();
    expect(wrapper.get('button').attributes('disabled')).toBeDefined();
    wrapper.unmount();
  });
});
