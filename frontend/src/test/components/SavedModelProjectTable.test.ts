import { describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import api from '@/api/client';
import { downloadJson } from '@/utils/download';
import Table from '@/components/SavedModelProjectTable.vue';

vi.mock('@/api/client', () => ({default: {get: vi.fn()}}));
vi.mock('@/utils/download', () => ({downloadJson: vi.fn()}));

describe('saved-model project comparison', () => {
  it('shows exact CV and unavailable independent evidence, then opens one saved model', async () => {
    vi.mocked(api.get).mockResolvedValue({data: {rows: [{
      artifact_uid: 'a', name: 'Protein PLS', model_type: 'pls', target_names: ['Protein'],
      target_units: ['wt %'], training_dataset_id: 12, preprocessing: [{op_id: 'preprocess.snv'}],
      components: 3, calibration_count: 24, validation: {method: 'group_kfold', folds: 3},
      metrics: {rmsec: 0.34, rmsecv: 0.51, rmsep: null, r2_calibration: 0.92, q2_cv: 0.76},
      reference_quality: {method: 'Kjeldahl'}, exclusions: ['s3'],
      qualification: {state: 'unavailable'}, gaps: ['Independent-test RMSEP and count unavailable'],
    }], comparable_groups: []}});
    const wrapper = mount(Table, {props: {projectId: 4}});
    await flushPromises();
    expect(api.get).toHaveBeenCalledWith('/models/project-overview', {params: {project_id: 4, limit: 50, offset: 0}});
    expect(wrapper.text()).toContain('group_kfold · 3 folds');
    expect(wrapper.text()).toContain('Independent-test RMSEP and count unavailable');
    expect(wrapper.text()).toContain('24');
    expect(wrapper.findAll('td').some(cell => cell.text() === '—')).toBe(true);
    await wrapper.find('tbody th button').trigger('click');
    expect(wrapper.emitted('select')?.[0]).toEqual(['a']);
    await wrapper.find('button[aria-label="Export evidence dossier for Protein PLS, a"]').trigger('click');
    expect(downloadJson).toHaveBeenCalledWith(expect.objectContaining({
      schema_version: 'spectrasherpa.saved-model-evidence-dossier/1',
      model: expect.objectContaining({artifact_uid: 'a', metrics: expect.objectContaining({rmsecv: 0.51})}),
    }), 'saved-model-a-evidence.json');
  });

  it('reports a failed evidence read without inventing table rows', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('unavailable'));
    const wrapper = mount(Table, {props: {projectId: 4}});
    await flushPromises();
    expect(wrapper.find('[role="alert"]').text()).toContain('could not be verified');
    expect(wrapper.findAll('tbody tr')).toHaveLength(0);
  });

  it('presents PLS-DA target and held-out class evidence without regression claims or internal step IDs', async () => {
    vi.mocked(api.get).mockResolvedValue({data: {rows: [{
      artifact_uid: 'da', name: 'Lavender', model_type: 'plsda', target_names: ['claimed_botanical_group'],
      preprocessing: [{op_id: 'data.attach_target'}, {op_id: 'spectrasherpa.experiment_dataset_read/2'},
        {op_id: 'preprocess.snv'}, {op_id: 'data.train_test_split'}],
      held_out_validation: {role: 'held_out_test', count: 9}, independent_test_count: 9,
      classification_metrics: {calibration_balanced_accuracy: 1, held_out_balanced_accuracy: 0.8, held_out_accuracy: 0.89},
      metrics: {rmsec: null, rmsecv: null, rmsep: null, r2_calibration: null, q2_cv: null},
    }], comparable_groups: []}});
    const wrapper = mount(Table, {props: {projectId: 4}});
    await flushPromises();
    const cells = wrapper.findAll('tbody td');
    expect(cells[0].text()).toBe('claimed_botanical_group');
    expect(cells[2].text()).toBe('SNV');
    expect(wrapper.text()).toContain('9 held-out samples');
    expect(wrapper.text()).toContain('Held-out balanced 0.8');
    expect(wrapper.text()).not.toContain('data.attach_target');
    expect(wrapper.text()).not.toContain('spectrasherpa.experiment_dataset_read/2');
    expect(wrapper.text()).toContain('Not ranked');
  });

  it('names the assessed external view when it differs from the selected dataset', async () => {
    vi.mocked(api.get).mockResolvedValue({data: {rows: [{
      artifact_uid: 'b', name: 'External Protein', model_type: 'pls',
      metrics: {rmsep: 0.8}, independent_test_count: 20, bias: 0.1, coverage: 0.85,
      coverage_denominator: 17, qualification: {state: 'stale_for_selected_dataset', validation_view_id: 41},
    }], comparable_groups: []}});
    const wrapper = mount(Table, {props: {projectId: 4}});
    await flushPromises();
    expect(wrapper.text()).toContain('External view #41 · differs from selected dataset');
    expect(wrapper.findAll('td').find(cell => cell.text() === '0.8')?.attributes('title')).toContain('view #41');
    expect(wrapper.text()).toContain('17/20 rows available');
  });

  it('keeps Previous available after an exact full page has no following rows', async () => {
    const fullPage = {data: {rows: Array.from({length: 50}, (_, index) => ({
      artifact_uid: `model-${index}`, name: `Model ${index}`, model_type: 'pls',
    })), comparable_groups: []}};
    vi.mocked(api.get)
      .mockResolvedValueOnce(fullPage)
      .mockResolvedValueOnce({data: {rows: [], comparable_groups: []}})
      .mockResolvedValueOnce(fullPage);
    const wrapper = mount(Table, {props: {projectId: 4}});
    await flushPromises();
    await wrapper.findAll('.model-overview__paging button')[1].trigger('click');
    await flushPromises();
    expect(api.get).toHaveBeenLastCalledWith('/models/project-overview', {
      params: {project_id: 4, limit: 50, offset: 50},
    });
    expect(wrapper.text()).toContain('No more saved models on this page');
    expect(wrapper.findAll('.model-overview__paging button')[0].attributes('disabled')).toBeUndefined();
    await wrapper.findAll('.model-overview__paging button')[0].trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('Model 0');
  });
});
