import { mount } from '@vue/test-utils';
import { expect, it } from 'vitest';
import ValidationLedger from '@/components/ValidationLedger.vue';

it('keeps a large ledger bounded on screen without discarding population or small residuals', () => {
  const source = Array.from({ length: 30000 }, (_, index) => ({
    sample: `specimen-${index}`, target: 'response', reference: 100, predicted: 100.00001,
    residual: 0.00001, role: 'held_out_test',
  }));
  const wrapper = mount(ValidationLedger, {
    props: { rows: source }, global: { stubs: { Button: true } },
  });
  expect(wrapper.findAll('tbody tr')).toHaveLength(200);
  expect(wrapper.text()).toContain('30000 sample-level predictions');
  expect(wrapper.text()).toContain('Showing the first 200 rows');
  expect(wrapper.find('tbody tr').text()).toContain('1.000e-5');
  expect(source[0].residual).toBe(0.00001);
  wrapper.unmount();
});

it('does not call an unevaluated mixed row incorrect', () => {
  const wrapper = mount(ValidationLedger, {
    props: { rows: [
      { sample: 'a', reference: 'A', predicted: 'A', correct: true },
      { sample: 'b', reference: 'B', predicted: 'A', correct: false },
      { sample: 'c', reference: null, predicted: 'A' },
    ] }, global: { stubs: { Button: true } },
  });
  const rows = wrapper.findAll('tbody tr');
  expect(rows[0].text()).toContain('Yes');
  expect(rows[1].text()).toContain('No');
  expect(rows[2].text()).toContain('Not evaluated');
});
