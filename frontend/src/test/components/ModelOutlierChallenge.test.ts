import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import api from '@/api/client';
import Challenge from '@/components/ModelOutlierChallenge.vue';
vi.mock('@/api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.get).mockImplementation(async (url) => ({ data: String(url).includes('outlier-challenges') ? { records: [] } : [{ id: 4, name: 'Challenge selection' }] }));
  vi.mocked(api.post).mockResolvedValue({ data: {} });
});
describe('outlier challenge shared journey', () => {
  it.each([{ artifactUid: 'native', endpoint: '/models/native/outlier-challenges' }, { canonicalArtifactId: 17, endpoint: '/deploy/canonical-artifacts/17/outlier-challenges' }])('submits explicit independent label basis for $endpoint', async ({ endpoint, ...props }) => {
    const wrapper = mount(Challenge, { props: { ...props, projectId: 2 } }); await flushPromises();
    expect(api.get).toHaveBeenCalledWith(endpoint);
    await wrapper.findAll('select')[0].findAll('option')[1].setSelected(); await flushPromises();
    await wrapper.findAll('select')[1].findAll('option')[1].setSelected();
    await wrapper.get('input:not([type=checkbox])').setValue('Foreign matrix');
    await wrapper.get('textarea').setValue('Prepared by laboratory technician');
    expect(wrapper.get('button').attributes('disabled')).toBeDefined();
    await wrapper.get('input[type=checkbox]').setValue(true);
    expect(wrapper.get('button').attributes('disabled')).toBeUndefined();
    await wrapper.get('button').trigger('click'); await flushPromises();
    expect(api.post).toHaveBeenCalledExactlyOnceWith(endpoint, { dataset_view_id: 4, outlier_type: 'Foreign matrix', label_basis: 'Prepared by laboratory technician', labels_independent_of_detector: true });
  });
});
