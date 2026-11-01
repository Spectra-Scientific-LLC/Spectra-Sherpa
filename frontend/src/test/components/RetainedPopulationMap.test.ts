import { expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import RetainedPopulationMap from '@/components/results/RetainedPopulationMap.vue';
import type { WorkflowPopulation } from '@/utils/workflowPopulation';

function fixture(): WorkflowPopulation {
  return {
    schema_version: 'spectrasherpa-workflow-population/1', source_node_id: 'load', source_digest: 'a'.repeat(64),
    source_count: 202, active_count: 201, workflow_excluded_count: 1, identity_basis: 'typed_sample_id',
    rows: Array.from({ length: 202 }, (_, i) => ({
      observation_ref: `load:${'a'.repeat(64)}:${i}`, source_row: i + 1,
      sample_id: `typed-${i}`, sample_label: 'duplicate', source_included: true,
      included: i !== 200, workflow_excluded: i === 200, result_row: i === 200 ? null : i > 200 ? i : i + 1,
    })),
  };
}

it('shows excluded rows and original identities across bounded pages without borrowing current decisions', async () => {
  const value = fixture();
  const before = JSON.stringify(value);
  const resolve = vi.fn(() => ({ excluded: true, restorable: true }));
  const wrapper = mount(RetainedPopulationMap, { props: { value, nodeId: 'load' }, global: {
    provide: { 'workflow-population-actions': { resolve } },
  } });
  expect(wrapper.findAll('tbody tr')).toHaveLength(100);
  expect(wrapper.text()).toContain('not use by every downstream computation');
  expect(wrapper.find('tbody tr').text()).toContain('typed-0');
  expect(wrapper.find('tbody tr').text()).toContain('Not excluded');
  await wrapper.findAll('button')[1].trigger('click');
  await wrapper.findAll('button')[1].trigger('click');
  expect(wrapper.findAll('tbody tr')).toHaveLength(2);
  const excluded = wrapper.find('tbody tr').findAll('td').map(cell => cell.text());
  expect(excluded).toEqual(['201', 'typed-200', 'duplicate', 'Yes', 'Excluded', 'No', 'Excluded']);
  const included = wrapper.findAll('tbody tr')[1].findAll('td').map(cell => cell.text());
  expect(included).toEqual(['202', 'typed-201', 'duplicate', 'Yes', 'Not excluded', 'Yes', '201']);
  expect(resolve).not.toHaveBeenCalled();
  expect(JSON.stringify(value)).toBe(before);
});

it('does not render a foreign or incomplete retained map', () => {
  for (const value of [{ ...fixture(), source_node_id: 'foreign' }, { ...fixture(), rows: [] }, undefined]) {
    const wrapper = mount(RetainedPopulationMap, { props: { value, nodeId: 'load' } });
    expect(wrapper.text()).toContain('unavailable or inconsistent');
    expect(wrapper.findAll('tbody tr')).toHaveLength(0);
  }
});

const inconsistentCases: [string, (value: WorkflowPopulation) => void][] = [
  ['included workflow exclusion', value => { value.rows[0].workflow_excluded = true; value.workflow_excluded_count++; }],
  ['included source exclusion', value => { value.rows[0].source_included = false; }],
  ['excluded without either decision', value => { value.rows[200].workflow_excluded = false; value.workflow_excluded_count = 0; }],
  ['foreign node reference', value => { value.rows[0].observation_ref = `other:${value.source_digest}:0`; }],
  ['foreign digest reference', value => { value.rows[0].observation_ref = `load:${'b'.repeat(64)}:0`; }],
  ['duplicate reference', value => { value.rows[1].observation_ref = value.rows[0].observation_ref; }],
  ['noncanonical index', value => { value.rows[0].observation_ref = `load:${value.source_digest}:00`; }],
  ['reordered rows', value => { [value.rows[0], value.rows[1]] = [value.rows[1], value.rows[0]]; }],
  ['zero source row', value => { value.rows[0].source_row = 0; }],
  ['duplicate source row', value => { value.rows[1].source_row = 1; }],
  ['missing included result row', value => { value.rows[0].result_row = null; }],
  ['excluded result row', value => { value.rows[200].result_row = 201; }],
  ['result row skips exclusion', value => { value.rows[201].result_row = 202; }],
  ['duplicate result row', value => { value.rows[1].result_row = 1; }],
  ['fractional result row', value => { value.rows[0].result_row = 1.5; }],
  ['wrong source count', value => { value.source_count--; }],
  ['wrong active count', value => { value.active_count--; }],
  ['wrong workflow exclusion count', value => { value.workflow_excluded_count++; }],
  ['nonfinite count', value => { value.active_count = NaN; }],
  ['nonboolean inclusion', value => { Object.assign(value.rows[0], { included: 1 }); }],
  ['string source row', value => { Object.assign(value.rows[0], { source_row: '1' }); }],
  ['string result row', value => { Object.assign(value.rows[0], { result_row: '1' }); }],
  ['missing excluded result row', value => { Reflect.deleteProperty(value.rows[200], 'result_row'); }],
  ['sparse rows', value => { delete value.rows[50]; }],
  ['over canonical maximum', value => { value.rows = new Array(100_001); value.source_count = 100_001; }],
];

it.each(inconsistentCases)('refuses %s without repairing the retained map', (_, change) => {
  const value = fixture();
  change(value);
  const before = JSON.stringify(value);
  const wrapper = mount(RetainedPopulationMap, { props: { value, nodeId: 'load' } });
  expect(wrapper.text()).toContain('unavailable or inconsistent');
  expect(wrapper.find('table').exists()).toBe(false);
  expect(wrapper.findAll('button')).toHaveLength(0);
  expect(JSON.stringify(value)).toBe(before);
  wrapper.unmount();
});

it.each([
  { availability: 'unavailable' },
  { source_count: '202' },
  { active_count: '201' },
  { workflow_excluded_count: true },
  { schema_version: 'spectrasherpa-workflow-population/2' },
])('refuses malformed or unavailable envelope %j', override => {
  const wrapper = mount(RetainedPopulationMap, { props: { value: { ...fixture(), ...override }, nodeId: 'load' } });
  expect(wrapper.text()).toContain('unavailable or inconsistent');
  expect(wrapper.find('table').exists()).toBe(false);
  wrapper.unmount();
});

it('accepts overlapping source/workflow exclusions without adding their counts together', () => {
  const value = fixture();
  value.rows[200].source_included = false;
  const wrapper = mount(RetainedPopulationMap, { props: { value, nodeId: 'load' } });
  expect(wrapper.find('table').exists()).toBe(true);
  expect(wrapper.text()).not.toContain('unavailable or inconsistent');
  wrapper.unmount();
});

it('removes previously displayed rows when a replacement retained map is inconsistent', async () => {
  const wrapper = mount(RetainedPopulationMap, { props: { value: fixture(), nodeId: 'load' } });
  await wrapper.findAll('button')[1].trigger('click');
  const inconsistent = fixture();
  inconsistent.rows[201].included = false;
  await wrapper.setProps({ value: inconsistent });
  expect(wrapper.find('table').exists()).toBe(false);
  expect(wrapper.text()).toContain('unavailable or inconsistent');
  await wrapper.setProps({ value: fixture() });
  expect(wrapper.find('tbody tr').find('td').text()).toBe('1');
  wrapper.unmount();
});
