import { flushPromises, mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import BatchRunTab from '@/views/experiments/BatchRunTab.vue';
vi.mock('@/api/client', () => ({ default: { get: vi.fn(async (url: string) => ({ data:
  url === '/workflows' ? [{ id: 1, name: 'Saved workflow' }] :
  url === '/experiments' ? [{ id: 2, name: 'Dataset' }] : [],
})) } }));
vi.mock('@/stores/project', () => ({ useProjectStore: () => ({ currentProjectId: 3 }) }));
vi.mock('primevue/usetoast', () => ({ useToast: () => ({ add: vi.fn() }) }));
describe('Private upload remains separate from project Batch', () => {
  it('binds private upload only to one explicitly selected fitted artifact', async () => {
    const wrapper = mount(BatchRunTab, { props: { artifacts: [
      { artifact_uid: 'm1', name: 'First fit', workflow_id: 1 },
      { artifact_uid: 'm2', name: 'Second fit', workflow_id: 1 },
    ] }, global: { stubs: { Button: true, PrivateBatchUpload: true } } });
    await flushPromises();
    const vm = wrapper.vm as any;
    vm.selectedWorkflowIds = [1]; vm.selectedArtifactUids = ['m1'];
    await flushPromises();
    expect(wrapper.findComponent({ name: 'PrivateBatchUpload' }).props('artifactUid')).toBe('m1');
    vm.selectedArtifactUids = ['m1', 'm2'];
    await flushPromises();
    expect(wrapper.find('private-batch-upload-stub').exists()).toBe(false);
    vm.selectedArtifactUids = ['m1']; vm.mode = 'run_workflow';
    await flushPromises();
    expect(wrapper.find('private-batch-upload-stub').exists()).toBe(false);
    wrapper.unmount();
  });
});
