import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import RetainedPopulationSummary from '@/components/results/RetainedPopulationSummary.vue';

describe('retained population projection', () => {
  const value = {
    schema_version: 'spectrasherpa-retained-population-summary/1', run_id: 42,
    rows: [{ label: 'Retained exclusions (load)', value: '6 source; 4 active; 2 excluded in total.' }],
    sources: [{ node_id: 'load', port: 'exclusions', availability: 'available', source_count: 6, active_count: 4, excluded_count: 2 }],
  };
  it('displays only retained facts and addresses the exact source map', async () => {
    const before = JSON.stringify(value);
    const wrapper = mount(RetainedPopulationSummary, { props: { runId: 42, value } });
    expect(wrapper.text()).toContain('Source 6');
    expect(wrapper.text()).toContain('Used 4');
    expect(wrapper.text()).toContain('Excluded 2');
    expect(wrapper.find('dl').exists()).toBe(false);
    expect(wrapper.find('table').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('6 source; 4 active; 2 excluded');
    expect(wrapper.get('span[title^="Used in"]').attributes('title')).toContain('Downstream use may differ');
    await wrapper.findAll('button')[0].trigger('click');
    await wrapper.findAll('button')[1].trigger('click');
    expect(wrapper.emitted('inspect')).toEqual([['load']]);
    expect(wrapper.emitted('download')).toEqual([['load']]);
    expect(JSON.stringify(value)).toBe(before);
  });
  it.each([undefined, { ...value, run_id: 7 }, { ...value, schema_version: 'unknown' },
    { ...value, rows: [{ label: 'Incomplete' }] }])('refuses missing, mismatched or malformed projections', input => {
    const wrapper = mount(RetainedPopulationSummary, { props: { runId: 42, value: input } });
    expect(wrapper.text()).toBe('Retained exclusions unavailable');
    expect(wrapper.get('span').attributes('title')).toContain('Current exclusions are not substituted');
    expect(wrapper.findAll('button')).toHaveLength(0);
  });
  it('offers no exact map download for unavailable evidence', () => {
    const wrapper = mount(RetainedPopulationSummary, { props: { runId: 42, value: {
      ...value, sources: [{ node_id: 'load', port: 'exclusions', availability: 'unavailable' }],
      rows: [{ label: 'Retained exclusions (load)', value: 'Unavailable: source map missing.' }],
    } } });
    expect(wrapper.text()).toContain('Unavailable');
    expect(wrapper.text()).not.toContain('Excluded 0');
    expect(wrapper.find('[aria-label^="Download retained row map"]').exists()).toBe(false);
  });
  it('refuses inconsistent counts rather than inventing inclusion from report prose', () => {
    const wrapper = mount(RetainedPopulationSummary, { props: { runId: 42, value: {
      ...value, sources: [{ ...value.sources[0], active_count: 5 }],
    } } });
    expect(wrapper.text()).toBe('Retained exclusions unavailable');
    expect(wrapper.findAll('button')).toHaveLength(0);
  });
});
