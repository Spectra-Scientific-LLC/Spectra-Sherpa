import { mount } from '@vue/test-utils';
import { expect, it } from 'vitest';
import ValidationLedger from '@/components/ValidationLedger.vue';

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
