import { describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { ref } from 'vue';
import api from '@/api/client';
import Qualification from '@/components/SavedModelQualification.vue';
import { requestAdvisorPrompt } from '@/lib/advisorPromptActions';

vi.mock('@/api/client', () => ({default: {get: vi.fn(), post: vi.fn()}}));
vi.mock('@/utils/download', () => ({downloadJson: vi.fn()}));
vi.mock('@/lib/advisorPromptActions', () => ({requestAdvisorPrompt: vi.fn()}));
vi.mock('@/composables/useAppConfig', () => ({useAppConfig: () => ({
  appConfig: ref({siteProfile: 'pro', advisorContextPolicy: 'full'}), appMode: ref('hosted'), isFeatureEnabled: () => true,
})}));

describe('saved model qualification', () => {
  it('asks Advisor only on an explicit click with current identity, not browser statistics', async () => {
    vi.mocked(requestAdvisorPrompt).mockClear();
    vi.mocked(api.get).mockImplementation(async (url) => {
      if (String(url).endsWith('/qualification')) return {data: {
        status: {state: 'accepted_under_declared_policy', dossier_digest: 'a'.repeat(64),
          decision_digest: 'c'.repeat(64), validation_view_digest: 'b'.repeat(64)},
        records: [{kind: 'assessment', record_digest: 'a'.repeat(64), validation_view_digest: 'b'.repeat(64), payload: {}}],
      }} as never;
      if (String(url) === '/experiments') return {data: []} as never;
      return {data: {manifest: {response_identity: {names: ['Protein'], units: ['%']}}}} as never;
    });
    const wrapper = mount(Qualification, {props: {artifactUid: 'model-1', projectId: 2, workflowId: 7, runId: 11}});
    await flushPromises();
    expect(requestAdvisorPrompt).not.toHaveBeenCalled();
    await wrapper.findAll('button').find(button => button.text() === 'Ask Sherpa about this qualification')!.trigger('click');
    expect(requestAdvisorPrompt).toHaveBeenCalledTimes(1);
    expect(vi.mocked(requestAdvisorPrompt).mock.calls[0][1]?.diagnosticScope?.reference).toEqual({
      kind: 'saved_model_qualification', artifact_uid: 'model-1', workflow_id: 7, run_id: 11,
      dossier_digest: 'a'.repeat(64), validation_view_digest: 'b'.repeat(64),
      decision_digest: 'c'.repeat(64), response_index: 0,
    });
  });
  it('keeps unresolved current evidence available for an Advisor explanation', async () => {
    vi.mocked(api.get).mockImplementation(async (url) => {
      if (String(url).endsWith('/qualification')) return {data: {
        status: {state: 'incomplete', dossier_digest: 'a'.repeat(64), validation_view_digest: 'b'.repeat(64)},
        records: [{kind: 'assessment', record_digest: 'a'.repeat(64), payload: {assessment: 'incomplete'}}],
      }} as never;
      if (String(url) === '/experiments') return {data: []} as never;
      return {data: {manifest: {response_identity: {names: ['Protein'], units: ['%']}}}} as never;
    });
    const wrapper = mount(Qualification, {props: {artifactUid: 'model-1', projectId: 2, workflowId: 7, runId: 11}});
    await flushPromises();
    expect((wrapper.findAll('button').find(button => button.text() === 'Ask Sherpa about this qualification')!.element as HTMLButtonElement).disabled).toBe(false);
  });
  it('clears a selected decision when fresh source verification fails', async () => {
    const record = {
      kind: 'assessment', record_digest: 'a'.repeat(64), context_digest: 'b'.repeat(64),
      validation_view_id: 8, payload: {
        assessment: 'criteria_met', context: {intended_use: 'Protein assay', intended_population: 'External lots'},
        policy: {policy_name: 'Protein', policy_version: '1'}, calculation: {complete_rows: 24, responses: []}, criteria: [],
      },
    };
    let qualifications = 0;
    vi.mocked(api.get).mockImplementation(async (url) => {
      if (String(url).endsWith('/qualification')) {
        qualifications++;
        if (qualifications === 2) throw new Error('source changed');
        return {data: {status: {state: 'awaiting_review'}, records: [record]}} as never;
      }
      if (String(url) === '/experiments') return {data: []} as never;
      return {data: {manifest: {response_identity: {names: ['Protein'], units: ['%']}}}} as never;
    });
    const wrapper = mount(Qualification, {props: {artifactUid: 'model-1', projectId: 2}});
    await flushPromises();
    await wrapper.findAll('button').find(button => button.text() === 'Review current assessment')!.trigger('click');
    expect(wrapper.find('fieldset').exists()).toBe(true);
    await wrapper.findAll('button').find(button => button.text() === 'Refresh evidence')!.trigger('click');
    await flushPromises();
    expect(wrapper.find('[role="alert"]').text()).toContain('source changed');
    expect(wrapper.find('fieldset').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('Current status: awaiting_review');
  });
});
