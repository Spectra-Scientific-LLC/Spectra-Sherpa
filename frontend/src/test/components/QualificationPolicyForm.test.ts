import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import Form from '@/components/QualificationPolicyForm.vue';

async function fill(wrapper: ReturnType<typeof mount>) {
  const fields = { 'policy-name': 'Routine control', 'intended-use': 'Casein measurement', population: 'Production milk', namespace: 'lab-register', 'sampling-design': 'Independent production batches', method: 'Reference method', 'method-version': '2026', 'measurement-basis': 'single_measurement', 'minimum-specimens': '20', 'per-component': '5', screening: '0.9', 'rmsep-0': '0.3', 'bias-0': '0.1', 'minimum-0': '1', 'maximum-0': '5' };
  for (const [field, value] of Object.entries(fields)) await wrapper.get(`[data-field="${field}"]`).setValue(value);
}
describe('guided qualification policy', () => {
  it('never supplies acceptance limits or checks independence declarations automatically', async () => {
    const wrapper = mount(Form, { props: { responseIdentity: { names: ['Casein'], units: ['wt %'] } } });
    const prepare = () => wrapper.findAll('button').find(button => button.text() === 'Use this policy and context')!;
    expect(prepare().attributes('disabled')).toBeDefined();
    expect(wrapper.findAll('input[type=checkbox]').every(input => !(input.element as HTMLInputElement).checked)).toBe(true);
    await fill(wrapper);
    expect(prepare().attributes('disabled')).toBeUndefined();
    await prepare().trigger('click');
    const value = wrapper.emitted('prepared')![0][0] as { policy: string; context: string };
    const policy = JSON.parse(value.policy), context = JSON.parse(value.context);
    expect(policy.response_identity).toEqual({ names: ['Casein'], units: ['wt %'] });
    expect(policy.responses[0]).toEqual({ max_rmsep: 0.3, max_absolute_bias: 0.1, intended_minimum: 1, intended_maximum: 5 });
    expect(context.reference_method.version).toBe('2026');
    expect(context.reference_method.measurement_basis).toBe('single_measurement');
    expect(context.independent_specimen_sampling_declared).toBe(false);
    expect(context.policy_frozen_before_validation).toBe(false);
    expect(wrapper.emitted('execute')).toBeUndefined();
  });
  it('requires an explicit reference method version and measurement basis, including replicate count', async () => {
    const wrapper = mount(Form, {props: {responseIdentity: {names: ['Casein'], units: ['wt %']}}});
    expect((wrapper.get('[data-field="method-version"]').element as HTMLInputElement).value).toBe('');
    expect((wrapper.get('[data-field="measurement-basis"]').element as HTMLSelectElement).value).toBe('');
    await fill(wrapper); await wrapper.get('[data-field="measurement-basis"]').setValue('replicate_mean');
    const prepare = () => wrapper.findAll('button').find(button => button.text() === 'Use this policy and context')!;
    expect(prepare().attributes('disabled')).toBeDefined();
    await wrapper.get('[data-field="measurements-per-label"]').setValue('3'); await prepare().trigger('click');
    const value = wrapper.emitted('prepared')![0][0] as {context: string};
    expect(JSON.parse(value.context).reference_method.measurements_per_label).toBe(3);
  });
  it('requires explicit imported response identity and refuses reversed ranges', async () => {
    const wrapper = mount(Form); await fill(wrapper);
    const prepare = wrapper.findAll('button').find(button => button.text() === 'Use this policy and context')!;
    expect(prepare.attributes('disabled')).toBeDefined();
    await wrapper.get('[data-field="name-0"]').setValue('Casein');
    await wrapper.get('[data-field="unit-0"]').setValue('wt %');
    expect(prepare.attributes('disabled')).toBeUndefined();
    await wrapper.get('[data-field="minimum-0"]').setValue('6');
    expect(prepare.attributes('disabled')).toBeDefined();
  });
});
