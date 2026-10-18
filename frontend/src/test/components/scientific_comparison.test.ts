import { mount } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import ScientificComparison from '@/components/ScientificComparison.vue';
import type { EvidenceComparison, EvaluationRole } from '@/types/scientificComparison';

vi.mock('@/components/PlotlyChart.vue', () => ({ default: { name: 'PlotlyChart', props: ['data', 'layout', 'selectedPointIds'], template: '<div class="plot" />' } }));
vi.mock('@/components/ScientificBasisHelp.vue', () => ({ default: { template: '<details>Scientific basis</details>' } }));

function evidence(): EvidenceComparison {
  const population = { verification: 'unknown' as const, limitations: [] };
  const roles: EvaluationRole[] = ['calibration', 'training_cv', 'held_out', 'outlier_challenge'];
  return {
    schema_version: 'spectrasherpa-scientific-comparison/1',
    items: [0, 1].map(id => ({
      reference: { kind: 'run', id: String(id + 1), provider: 'runs', revision: 'a'.repeat(64) }, label: `Run ${id + 1}`, population,
      sections: Object.fromEntries(roles.map(role => [role, { role, state: role === 'held_out' ? 'verified' : 'unavailable',
        population, reason: 'Evidence', metrics: {}, sample_ids: ['s1'], observations: [10], predictions: [9 - id] }])) as EvidenceComparison['items'][number]['sections'],
    })),
    pairs: [{ left_index: 0, right_index: 1, sections: roles.map(role => ({
      role, state: role === 'held_out' ? 'comparable' : 'unavailable', reason: role === 'held_out' ? 'Matching held-out population' : 'Missing folds',
      next_action: 'Run a common evaluation', metric_values: role === 'held_out' ? { rmse: { left: 1, right: 2 } } : {},
    })) }],
  };
}

describe('Shared scientific comparison', () => {
  it('links lasso and table selection by exact specimen identity and resets for new evidence', async () => {
    const wrapper = mount(ScientificComparison, {props: {evidence: evidence()}});
    const charts = wrapper.findAllComponents({name: 'PlotlyChart'});
    charts[0].vm.$emit('selected', {points: [{customdata: 's1'}, {customdata: 'foreign'}]});
    await wrapper.vm.$nextTick();
    expect(charts[1].props('selectedPointIds')).toEqual(['s1']);
    expect(wrapper.get('[aria-label="Paired specimen results"] tr.selected-row').text()).toContain('s1');
    await wrapper.get('[aria-label="Paired specimen results"] tbody button').trigger('click');
    expect(charts[0].props('selectedPointIds')).toEqual([]);
    charts[1].vm.$emit('selected', {points: [{customdata: 's1'}]}); await wrapper.vm.$nextTick();
    charts[0].vm.$emit('deselect'); await wrapper.vm.$nextTick();
    expect(charts[1].props('selectedPointIds')).toEqual([]);
    charts[1].vm.$emit('selected', {points: [{customdata: 's1'}]}); await wrapper.vm.$nextTick();
    await wrapper.setProps({evidence: evidence()});
    expect(charts[0].props('selectedPointIds')).toEqual([]);
  });

  it('does not overlay observations for an unqualified pair with incompatible response units', () => {
    const value = evidence();
    value.items[0].population.units = 'percent'; value.items[1].population.units = 'mg/L';
    const section = value.pairs[0].sections.find(s => s.role === 'held_out')!;
    section.state = 'descriptive_only'; section.reason = 'Response units differ';
    const wrapper = mount(ScientificComparison, {props: {evidence: value}});
    expect(wrapper.text()).toContain('Response units differ');
    expect(wrapper.findAll('.plot')).toHaveLength(0);
  });

  it('keeps valid held-out evidence when CV is unavailable and unknown counts are not zero', () => {
    const wrapper = mount(ScientificComparison, { props: { evidence: evidence() } });
    expect(wrapper.get('[aria-label="Held-out validation"]').text()).toContain('Comparable: Matching held-out population');
    expect(wrapper.get('[aria-label="Held-out validation"]').text()).toContain('RMSEP');
    expect(wrapper.get('[aria-label="Training CV"]').text()).toContain('Unavailable: Missing folds');
    expect(wrapper.text()).toContain('Development: Unknown');
    expect(wrapper.text()).not.toContain('Development: 0');
    expect(wrapper.text()).toContain('Scientific basis');
  });

  it('uses reference minus prediction residuals only from the selected evidence role', () => {
    const wrapper = mount(ScientificComparison, { props: { evidence: evidence() } });
    const charts = wrapper.findAllComponents({ name: 'PlotlyChart' });
    // The only available population is held-out: one predicted and one residual plot.
    const plots = wrapper.findAll('.plot');
    expect(plots).toHaveLength(2);
    expect(charts.some(c => (c.props('data') as Array<{ y: number[] }>)[0]?.y[0] === 1)).toBe(true);
  });
});
