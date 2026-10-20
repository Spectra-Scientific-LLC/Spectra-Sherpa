import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import api from '@/api/client';
import Review from '@/components/ModelPromotionReview.vue';
const navigate = vi.hoisted(() => vi.fn());
vi.mock('vue-router', () => ({ useRouter: () => ({ push: navigate }) }));
vi.mock('@/api/client', () => ({ default: { get: vi.fn(), patch: vi.fn(), post: vi.fn() } }));
const snapshot = { review_digest: 'a'.repeat(64), population: { fitted_count: 174, held_out_count: null }, qualification: { state: 'unavailable' }, blockers: [], limitations: ['Not independent validation'], guidance: { reason: 'Reuse the fitted model', scientific_basis: 'Separate CV and validation' } };
const stubs = {
  Dialog: { template: '<section><slot/><slot name="footer"/></section>' },
  Button: { props: ['label', 'disabled'], template: '<button :disabled="disabled">{{label}}</button>' },
  SavedModelQualification: true, ModelOutlierChallenge: true, QualificationPanel: true, ScientificBasisHelp: true,
};
beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks(); vi.mocked(api.get).mockResolvedValue({ data: snapshot }); });
describe('shared promotion review', () => {
  it('requires intended use and rationale without requiring a provider and pins the reviewed digest', async () => {
    const wrapper = mount(Review, { props: { artifactUid: 'model', projectId: 1 }, global: { stubs } });
    await flushPromises();
    expect(wrapper.text()).toContain('174 development samples');
    expect(wrapper.text()).toContain('Held-out count: not recorded');
    const confirm = wrapper.findAll('button').find(b => b.text() === 'Confirm deploy-ready')!;
    expect(confirm.attributes('disabled')).toBeDefined();
    expect(wrapper.find('option[value="accepted_external_validation"]').attributes('disabled')).toBeDefined();
    await wrapper.findAll('textarea')[0].setValue('Instrument exploration');
    await wrapper.findAll('textarea')[1].setValue('Inspected exact artifact');
    await confirm.trigger('click'); await flushPromises();
    expect(api.patch).toHaveBeenCalledWith('/models/model', { is_deploy_ready: true, promotion_review: { review_digest: snapshot.review_digest, intended_use: 'Instrument exploration', rationale: 'Inspected exact artifact', protocol: 'exploratory' } });
    expect(wrapper.emitted('confirmed')).toHaveLength(1);
  });
  it('shows a server stale-evidence refusal without confirming readiness', async () => {
    vi.mocked(api.patch).mockRejectedValue({ isAxiosError: true, response: { data: { detail: 'Evidence changed after review' } } });
    const wrapper = mount(Review, { props: { artifactUid: 'model' }, global: { stubs } });
    await flushPromises();
    await wrapper.findAll('textarea')[0].setValue('Exploration'); await wrapper.findAll('textarea')[1].setValue('Reviewed');
    await wrapper.findAll('button').find(b => b.text() === 'Confirm deploy-ready')!.trigger('click'); await flushPromises();
    expect(wrapper.find('[role="alert"]').text()).toContain('Evidence changed');
    expect(wrapper.emitted('confirmed')).toBeUndefined();
  });
  it('uses the same decision for an imported application without inventing a saved model id', async () => {
    const wrapper = mount(Review, { props: { canonicalArtifactId: 17, workflowId: 12, projectId: 1 }, global: { stubs } });
    await flushPromises();
    await wrapper.findAll('textarea')[0].setValue('Exploration'); await wrapper.findAll('textarea')[1].setValue('Reviewed');
    await wrapper.findAll('button').find(b => b.text() === 'Confirm deploy-ready')!.trigger('click'); await flushPromises();
    expect(api.get).toHaveBeenCalledWith('/deploy/canonical-artifacts/17/promotion-review', { signal: expect.any(AbortSignal) });
    expect(api.post).toHaveBeenCalledWith('/deploy/canonical-artifacts/17/promotion-review', expect.objectContaining({ review_digest: snapshot.review_digest }));
    expect(api.patch).not.toHaveBeenCalled();
  });
  it('opens the verified source workflow for an explicit final fit without executing it', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { ...snapshot, workflow_id: 12, source_run_id: 7, fitting_plan: { state: 'complete_declared_development_fit', declared_development_count: 174 } } });
    const wrapper = mount(Review, { props: { artifactUid: 'model', projectId: 1 }, global: { stubs } });
    await flushPromises();
    expect(wrapper.text()).toContain('All 174 declared development samples');
    await wrapper.findAll('button').find(b => b.text() === 'Open workflow to prepare final fit')!.trigger('click');
    await flushPromises();
    expect(navigate).toHaveBeenCalledWith({ path: '/workflow', query: { workflow_id: 12, project_id: 1, promotion_artifact: 'model', promotion_source_run: 7 } });
    expect(api.post).not.toHaveBeenCalled(); expect(api.patch).not.toHaveBeenCalled();
  });

});
