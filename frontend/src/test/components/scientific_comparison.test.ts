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
    expect(wrapper.find('[aria-label="Training CV"]').exists()).toBe(false);
    expect(wrapper.text()).toContain('Unavailable: calibration, training cv, outlier challenge.');
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
  it('aligns role metrics under run names without mixing CV or inventing deltas', () => {
    const value = evidence();
    value.items[0].label = 'PLS calibration'; value.items[1].label = 'R2 candidate 2';
    value.items[0].sections.held_out.metrics = { rmse: 2.2914, mae: 2.1665 };
    value.items[1].sections.held_out.metrics = { rmse: 1.7749, mae: 1.5655 };
    value.items[1].sections.training_cv.metrics = { rmse: 1.4861 };
    const pair = value.pairs[0].sections.find(s => s.role === 'held_out')!;
    pair.metric_values = { rmse: { left: 2.2914, right: 1.7749 } };
    const wrapper = mount(ScientificComparison, { props: { evidence: value } });
    const held = wrapper.get('[aria-label="Held-out validation"]');
    expect(held.text()).toContain('PLS calibration'); expect(held.text()).toContain('R2 candidate 2');
    expect(held.text()).toContain('Delta (2 − 1)');
    expect(held.text()).toContain('2.2914'); expect(held.text()).toContain('1.7749');
    expect(held.text()).not.toContain('1.4861');
    const mae = held.findAll('tr').find(row => row.text().includes('MAE'))!;
    expect(mae.findAll('td').at(-1)!.text()).toBe('—');
    expect(wrapper.get('[aria-label="Training CV"]').text()).toContain('1.4861');
    wrapper.unmount();
  });

  it('numbers every comparison consistently when more than two results are selected', () => {
    const value = evidence();
    value.items.push({ ...value.items[1], label: 'Third run', reference: { ...value.items[1].reference, id: '3' } });
    value.pairs[0].left_index = 1; value.pairs[0].right_index = 2;
    const wrapper = mount(ScientificComparison, { props: { evidence: value } });
    const held = wrapper.get('[aria-label="Held-out validation"]');
    expect(held.text()).toContain('2 · Run 2'); expect(held.text()).toContain('3 · Third run');
    expect(held.text()).toContain('Delta (3 − 2)');
    wrapper.unmount();
  });

});

it('shows population limitations in the initially expanded Summary', () => {
  const value = evidence();
  value.items[0].population.limitations = ['Independent population not verified'];
  const wrapper = mount(ScientificComparison, { props: { evidence: value }, attachTo: document.body });
  const summary = wrapper.findAllComponents({ name: 'Panel' }).find(panel => panel.props('header') === 'Summary')!;
  expect(summary.props('collapsed')).toBe(false);
  expect(summary.text()).toContain('Independent population not verified');
  expect(summary.get('.p-panel-content').isVisible()).toBe(true);
  wrapper.unmount();
});

 it('only gives a verdict and directional changes for comparable evidence with common units', async () => {
   const value = evidence();
   value.items.forEach(item => { item.sections.held_out.population = { verification: 'verified', limitations: [], units: 'ppm' }; });
   const wrapper = mount(ScientificComparison, { props: { evidence: value } });
   expect(wrapper.text()).toContain('Run 1 has lower held-out error: RMSEP 1.000 vs 2.000 ppm.');
   expect(wrapper.find('td.worse').text()).toContain('worse');
   value.pairs[0].sections.find(s => s.role === 'held_out')!.state = 'descriptive_only';
   await wrapper.setProps({ evidence: structuredClone(value) });
   expect(wrapper.find('.comparison-verdict').exists()).toBe(false);
   expect(wrapper.find('td.worse').exists()).toBe(false);
   wrapper.unmount();
 });

it('keeps actionable refusal explanations even when every role has no metrics', () => {
  const value = evidence();
  for (const item of value.items) for (const section of Object.values(item.sections)) {
    section.state = 'unavailable'; section.metrics = {};
  }
  for (const section of value.pairs[0].sections) {
    section.state = 'unavailable'; section.metric_values = {};
    section.reason = 'Choose a recipe and repetition from this saved paired evaluation.';
    section.next_action = 'Select the retained recipe.';
  }
  const wrapper = mount(ScientificComparison, { props: { evidence: value } });
  expect(wrapper.get('.unavailable-reasons').text()).toContain('Choose a recipe and repetition');
  expect(wrapper.get('.unavailable-reasons').text()).toContain('Select the retained recipe.');
  expect(wrapper.find('.comparison-verdict').exists()).toBe(false);
});

it('formats very large and very small measures without changing retained data', () => {
  const value = evidence();
  value.items[0].sections.held_out.metrics = { rer: 9553577508788658, bias: -6.0364e-15 };
  const wrapper = mount(ScientificComparison, { props: { evidence: value } });
  const held = wrapper.get('[aria-label="Held-out validation"]');
  expect(held.text()).toContain('9.55358e+15');
  expect(held.text()).toContain('-6.03640e-15');
  expect(held.text()).not.toContain('9553577508788658.0000');
  expect(value.items[0].sections.held_out.metrics.bias).toBe(-6.0364e-15);
  wrapper.unmount();
});


it('keeps evaluation origin in campaign headers, copied table text and numerical verdicts', () => {
  const value = evidence();
  const labels = ['Model 1.1 · Re-scored in round 2', 'Model 2.1 · Original evaluation in round 2'];
  value.items.forEach((item, index) => {
    item.label = labels[index];
    item.reference = {...item.reference, kind: 'external', provider: 'campaigns'};
    item.sections.held_out.population = {verification: 'verified', limitations: [], units: 'ppm'};
  });
  const wrapper = mount(ScientificComparison, {props: {evidence: value}});
  const table = wrapper.get('[aria-label="Held-out validation measures"]');
  for (const label of labels) {
    expect(table.text()).toContain(label);
    expect(wrapper.get('.comparison-verdict').text()).toContain(label);
  }
  wrapper.unmount();
});

it('maps a right-hand winner to its origin when copied from a three-model comparison', () => {
  const value = evidence();
  value.items.push(structuredClone(value.items[1]));
  value.items.forEach((item, index) => {
    item.label = `Model ${index + 1}.1 · Original evaluation in round ${index + 1}`;
    item.reference = {...item.reference, kind: 'external', provider: 'campaigns'};
    item.sections.held_out.population = {verification: 'verified', limitations: [], units: 'ppm'};
  });
  const pair = value.pairs[0];
  pair.left_index = 1; pair.right_index = 2;
  pair.sections.find(s => s.role === 'held_out')!.metric_values.rmse = {left: 2, right: 1};
  const wrapper = mount(ScientificComparison, {props: {evidence: value}});
  const verdict = wrapper.get('.comparison-verdict').text();
  expect(verdict).toContain('Run 3 has lower held-out error: RMSEP 1.000 vs 2.000 ppm');
  expect(verdict).toContain('Run 2: Model 2.1 · Original evaluation in round 2');
  expect(verdict).toContain('Run 3: Model 3.1 · Original evaluation in round 3');
  wrapper.unmount();
});
