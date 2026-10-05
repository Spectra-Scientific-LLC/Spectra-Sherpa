import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BatchRunTab from '@/views/experiments/BatchRunTab.vue';

const { get, post, toast } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), toast: vi.fn() }));
vi.mock('@/api/client', () => ({ default: { get, post } }));
vi.mock('primevue/usetoast', () => ({ useToast: () => ({ add: toast }) }));
vi.mock('@/stores/project', () => ({ useProjectStore: () => ({ currentProjectId: 1 }) }));
vi.mock('@/composables/useDemoMode', () => ({ useDemoMode: () => ({ isDemoMode: { value: false } }) }));

function open() {
  return mount(BatchRunTab, { props: { artifacts: [{
    artifact_uid: 'exact-model', name: 'Exact model', model_type: 'pls_da', n_features: 2,
  }] }, global: {
    stubs: { Button: true, Dropdown: true, InputText: true, MultiSelect: true },
  } });
}

beforeEach(() => {
  vi.clearAllMocks();
  get.mockImplementation(async (url: string) => {
    if (url === '/experiments') return { data: [{ id: 1, name: 'First' }, { id: 2, name: 'Second' }] };
    if (url.endsWith('/scientific-assets')) return { data: { assets: [{ asset_id: 'only', title: 'Only', shape: [3, 2] }] } };
    if (url.endsWith('/files')) return { data: [{ id: 10 }] };
    return { data: { id: Number(url.split('/').at(-1)), metadata: { n_features: 2 } } };
  });
});

describe('Persisted application preflight', () => {
  it('blocks during inventory loading and discards a late previous selection', async () => {
    let release!: (value: unknown) => void;
    const original = get.getMockImplementation()!;
    get.mockImplementation((url: string) => url === '/experiments/1/files/10/scientific-assets'
      ? new Promise(resolve => { release = resolve; }) : original(url));
    const wrapper = open();
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      selectedExperimentId: number; selectedExperimentDetail: { id: number }; canSubmit: boolean;
      requiresAssetSelection: boolean; selectedArtifactUids: string[];
    };
    vm.selectedArtifactUids = ['exact-model'];
    vm.selectedExperimentId = 1;
    expect(vm.canSubmit).toBe(false);
    await flushPromises();
    expect(vm.canSubmit).toBe(false);
    vm.selectedExperimentId = 2;
    await flushPromises();
    expect(vm.selectedExperimentDetail.id).toBe(2);
    expect(vm.canSubmit).toBe(true);
    release({ data: { assets: [{ asset_id: 'a' }, { asset_id: 'b' }] } });
    await flushPromises();
    expect(vm.selectedExperimentDetail.id).toBe(2);
    expect(vm.requiresAssetSelection).toBe(false);
    wrapper.unmount();
  });

  it('persists even one model through runs/batch and exposes its failed run', async () => {
    post.mockResolvedValue({ data: { status: 'failed', run: { id: 7, name: 'Failed attempt' },
      results: [{ artifact_uid: 'exact-model', status: 'failed', error: 'Axis mismatch' }] } });
    const wrapper = open();
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      selectedExperimentId: number; selectedArtifactUids: string[]; handleSubmit: () => Promise<void>;
    };
    vm.selectedArtifactUids = ['exact-model'];
    vm.selectedExperimentId = 2;
    await flushPromises();
    await vm.handleSubmit();
    expect(post).toHaveBeenCalledWith('/runs/batch', expect.objectContaining({
      artifact_uids: ['exact-model'], dataset: expect.objectContaining({ experiment_id: 2 }), scope: 'all',
    }));
    expect(wrapper.emitted('completed')?.[0]).toEqual([{ id: 7, name: 'Failed attempt' }]);
    wrapper.unmount();
  });

  it('uses the selected saved definition as the exact batch dataset', async () => {
    const original = get.getMockImplementation()!;
    get.mockImplementation((url: string) => url === '/experiments/2/dataset-views'
      ? Promise.resolve({ data: [{ id: 41, name: 'MP5 held-out', selection: { stage: 'raw', asset_id: 'spectra' } }] })
      : original(url));
    post.mockResolvedValue({ data: { status: 'completed', run: { id: 9, name: 'MP5 prediction' }, results: [] } });
    const wrapper = open();
    await flushPromises();
    const vm = wrapper.vm as unknown as {
      selectedExperimentId: number; selectedDatasetViewId: number; selectedArtifactUids: string[];
      canSubmit: boolean; handleSubmit: () => Promise<void>;
    };
    vm.selectedArtifactUids = ['exact-model'];
    vm.selectedExperimentId = 2;
    await flushPromises();
    vm.selectedDatasetViewId = 41;
    await flushPromises();
    expect(vm.canSubmit).toBe(true);
    await vm.handleSubmit();
    expect(post).toHaveBeenCalledWith('/runs/batch', expect.objectContaining({
      dataset_view_id: 41, scope: 'all',
      dataset: expect.objectContaining({ experiment_id: 2, stage: 'raw', asset_id: null }),
    }));
    wrapper.unmount();
  });
});
