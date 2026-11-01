import { expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import RetainedRunMapLink from '@/components/results/RetainedRunMapLink.vue';

it('links exact run/project identities without requesting any retained evidence', () => {
  const wrapper = mount(RetainedRunMapLink, { props: { runId: 42, projectId: 7 } });
  expect(wrapper.get('a').attributes('href')).toBe('/runs/42?project=7&tab=inspect&view=Summary#retained-observation-exclusions');
  expect(wrapper.text()).toBe('Inspect retained exclusions · Run #42');
});

it.each([{}, { runId: 42 }, { projectId: 7 }, { runId: 0, projectId: 7 }, { runId: 1.5, projectId: 7 }])(
  'never fabricates a run link for absent or invalid identity', props => {
    const wrapper = mount(RetainedRunMapLink, { props });
    expect(wrapper.find('a').exists()).toBe(false);
    expect(wrapper.text()).toContain('unavailable');
  },
);
