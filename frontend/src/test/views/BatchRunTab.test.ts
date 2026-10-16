import { mount, flushPromises } from '@vue/test-utils';
import { reactive } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import BatchRunTab from '@/views/experiments/BatchRunTab.vue';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), project: null as any }));
vi.mock('@/api/client', () => ({ default: { get: mocks.get, post: mocks.post } }));
vi.mock('@/stores/project', () => ({ useProjectStore: () => mocks.project }));
vi.mock('primevue/usetoast', () => ({ useToast: () => ({ add: vi.fn() }) }));
function open() {
  return mount(BatchRunTab, { props: { artifacts: [
    { artifact_uid: 'm1', name: 'Model one', workflow_id: 1, source_run_id: 17, n_components: 5, created_at: '2026-10-09T12:00:00Z' },
    { artifact_uid: 'm2', name: 'Model two', workflow_id: 2 },
  ] }, global: { stubs: { PrivateBatchUpload: true,
    Button: { props: ['label', 'disabled'], template: '<button :disabled="disabled">{{ label }}</button>' },
  } } });
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.project = reactive({ currentProjectId: 3 });
  mocks.get.mockImplementation(async (url: string) => ({ data:
    url === '/workflows' ? [{ id: 1, name: 'PLS' }, { id: 2, name: 'PCR' }] :
    url === '/experiments' ? [{ id: 4, name: 'Corn' }] :
    url.endsWith('/dataset-views') ? [{ id: 7, name: 'Included cohort' }] : { id: 9 },
  }));
  mocks.post.mockImplementation(async (url: string, payload: any) => ({ data:
    url.endsWith('/preflight') ? { pairs: payload.pairs.map(() => ({
      compatible: true, receipt: 'a'.repeat(64), metadata: { accuracy_available: true, n_included_samples: 80 },
    })) } : { batch_id: 'batch-id', results: [{ run_id: 9, status: 'completed' }] },
  }));
});
async function choose(wrapper: ReturnType<typeof open>) {
  await flushPromises();
  const vm = wrapper.vm as any;
  vm.selectedWorkflowIds = [1, 2];
  vm.selectedArtifactUids = ['m1', 'm2'];
  vm.selectedDefinitionKeys = ['4:default', '4:7'];
  await flushPromises();
  return vm;
}
describe('Batch workflow verification', () => {
  it('excludes internal candidate sheets and workflows without fitted models in application mode', async () => {
    const wrapper = open();
    const vm = await choose(wrapper);
    vm.workflows = [
      { id: 1, name: 'Calibration', purpose: 'analysis' },
      { id: 2, name: 'Internal authority', purpose: 'managed_candidate_authority' },
      { id: 3, name: 'Preprocessing', purpose: 'analysis' },
    ];
    vm.selectedWorkflowIds = [1, 2, 3];
    await flushPromises();
    expect(wrapper.text()).not.toContain('Internal authority');
    expect(wrapper.text()).not.toContain('Preprocessing');
    expect(vm.combinations.every((pair: any) => pair.payload.workflow_id === 1 && pair.payload.artifact_uid)).toBe(true);
    vm.mode = 'run_workflow';
    await flushPromises();
    expect(wrapper.text()).toContain('Preprocessing');
    expect(wrapper.text()).not.toContain('Internal authority');
    wrapper.unmount();
  });
  it('offers two modes and a checkbox list, never a table or sample-partition scope', async () => {
    const wrapper = open();
    const vm = await choose(wrapper);
    expect(vm.combinations).toHaveLength(4);
    expect(wrapper.text()).toContain('Run #17');
    expect(wrapper.text()).toContain('5 LV');
    expect(wrapper.findAll('input[type="radio"]')).toHaveLength(2);
    expect(wrapper.find('table').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('Included test samples');
    expect(vm.canSubmit).toBe(false);
    await vm.checkCompatibility();
    expect(vm.canSubmit).toBe(true);
    wrapper.unmount();
  });
  it('submits only compatible, checked combinations with exact preflight receipts', async () => {
    const wrapper = open();
    const vm = await choose(wrapper);
    await vm.checkCompatibility();
    vm.toggleCombination(vm.combinations[0].key);
    await vm.handleSubmit();
    const call = mocks.post.mock.calls.find(([url]) => url === '/runs/verification')!;
    expect(call[1].pairs).toHaveLength(3);
    expect(call[1].mode).toBe('apply_model');
    expect(call[1].pairs[0]).toEqual(expect.objectContaining({ dataset_view_id: 7, receipt: 'a'.repeat(64) }));
    expect(wrapper.emitted('completed')).toEqual([[{ id: 9 }]]);
    expect(vm.canSubmit).toBe(false);
    wrapper.unmount();
  });
  it('disables incompatible combinations and explains targetless inference', async () => {
    mocks.post.mockResolvedValue({ data: { pairs: [
      { compatible: false, reason: 'Target units mismatch' },
      { compatible: true, receipt: 'b'.repeat(64), metadata: { accuracy_available: false, n_included_samples: 80 } },
      { compatible: false, reason: 'Wrong feature axis' }, { compatible: false, reason: 'Missing fitted model' },
    ] } });
    const wrapper = open();
    const vm = await choose(wrapper);
    await vm.checkCompatibility();
    await flushPromises();
    expect(vm.selectedPairs).toHaveLength(1);
    expect(wrapper.text()).toContain('Target units mismatch');
    expect(wrapper.text()).toContain('predictions only');
    expect(wrapper.findAll('.batch-combinations input[disabled]')).toHaveLength(3);
    wrapper.unmount();
  });
  it('requires an explicit legacy acknowledgement and a fresh preflight receipt', async () => {
    mocks.post.mockImplementation(async (url: string, payload: { pairs: { acknowledge_legacy_input_uncertainty?: boolean }[] }) => ({ data:
      url.endsWith('/preflight') ? { pairs: payload.pairs.map(pair => pair.acknowledge_legacy_input_uncertainty
        ? { compatible: true, receipt: 'c'.repeat(64), metadata: { n_included_samples: 6 } }
        : { compatible: false, code: 'legacy_ack_required', reason: 'Model predates fitted signal identity.' }) }
      : { batch_id: 'legacy-batch', results: [{ run_id: 9, status: 'completed' }] },
    }));
    const wrapper = open();
    const vm = await choose(wrapper);
    vm.selectedWorkflowIds = [1]; vm.selectedArtifactUids = ['m1']; vm.selectedDefinitionKeys = ['4:default'];
    await flushPromises();
    await vm.checkCompatibility();
    await flushPromises();
    expect(vm.canSubmit).toBe(false);
    expect(wrapper.text()).toContain('predates fitted signal identity');
    await wrapper.find('.legacy-ack input').trigger('change');
    expect(vm.canSubmit).toBe(false);
    await vm.checkCompatibility();
    expect(vm.canSubmit).toBe(true);
    await vm.handleSubmit();
    const call = mocks.post.mock.calls.find(([url]) => url === '/runs/verification')!;
    expect(call[1].pairs[0]).toEqual(expect.objectContaining({
      acknowledge_legacy_input_uncertainty: true, receipt: 'c'.repeat(64),
    }));
    wrapper.unmount();
  });
  it('uses workflow mode without an old model and invalidates preflight on mode change', async () => {
    const wrapper = open();
    const vm = await choose(wrapper);
    await vm.checkCompatibility();
    vm.mode = 'run_workflow';
    await flushPromises();
    expect(vm.canSubmit).toBe(false);
    expect(vm.combinations.every((pair: any) => pair.payload.artifact_uid === null)).toBe(true);
    await vm.checkCompatibility();
    await vm.handleSubmit();
    expect(mocks.post.mock.calls.find(([url]) => url === '/runs/verification')![1].mode).toBe('run_workflow');
    wrapper.unmount();
  });
  it('discards a late compatibility response after the selection changes', async () => {
    let finish!: (value: any) => void;
    mocks.post.mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const wrapper = open();
    const vm = await choose(wrapper);
    const check = vm.checkCompatibility();
    vm.selectedWorkflowIds = [1];
    await flushPromises();
    finish({ data: { pairs: [{ compatible: true, receipt: 'stale' }] } });
    await check;
    expect(vm.checks).toEqual([]);
    expect(vm.canSubmit).toBe(false);
    wrapper.unmount();
  });
  it('does not attach a late result to another project', async () => {
    const wrapper = open();
    const vm = await choose(wrapper);
    await vm.checkCompatibility();
    let finish!: (value: any) => void;
    mocks.post.mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const submit = vm.handleSubmit();
    mocks.project.currentProjectId = 8;
    await flushPromises();
    finish({ data: { batch_id: 'old-project', results: [{ run_id: 9 }] } });
    await submit;
    expect(wrapper.emitted('completed')).toBeUndefined();
    expect(vm.canSubmit).toBe(false);
    wrapper.unmount();
  });
  it('fails closed when a saved-definition inventory is unavailable', async () => {
    const original = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((url: string) => url.endsWith('/dataset-views')
      ? Promise.reject(new Error('Definition inventory failed')) : original(url));
    const wrapper = open();
    await flushPromises();
    expect((wrapper.vm as any).canCheck).toBe(false);
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
    wrapper.unmount();
  });
});
