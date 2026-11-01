import { expect, it, vi } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createMemoryHistory, createRouter } from 'vue-router';
import RetainedRunMapLink from '@/components/results/RetainedRunMapLink.vue';

function render(props: { runId?: number; projectId?: number }) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/runs/:runId', component: { template: '<div />' } },
  ] });
  return { router, wrapper: mount(RetainedRunMapLink, { props, global: { plugins: [router] } }) };
}

it('links exact run/project identities without requesting any retained evidence', () => {
  const { wrapper } = render({ runId: 42, projectId: 7 });
  expect(wrapper.get('a').attributes('href')).toBe('/runs/42?project=7&tab=inspect&view=Summary#retained-observation-exclusions');
  expect(wrapper.text()).toBe('Inspect retained exclusions · Run #42');
});

it('uses router navigation without a document reload or parent selection click', async () => {
  const { wrapper, router } = render({ runId: 42, projectId: 7 });
  await router.isReady();
  const push = vi.spyOn(router, 'push');
  const selectionClick = vi.fn();
  const parent = document.createElement('div');
  parent.appendChild(wrapper.element);
  parent.addEventListener('click', selectionClick);
  await wrapper.get('a').trigger('click');
  await flushPromises();
  expect(push).toHaveBeenCalledWith('/runs/42?project=7&tab=inspect&view=Summary#retained-observation-exclusions');
  expect(router.currentRoute.value.params.runId).toBe('42');
  expect(selectionClick).not.toHaveBeenCalled();
  wrapper.unmount();
  parent.remove();
});

it.each([{}, { runId: 42 }, { projectId: 7 }, { runId: 0, projectId: 7 }, { runId: 1.5, projectId: 7 }])(
  'never fabricates a run link for absent or invalid identity', props => {
    const { wrapper } = render(props);
    expect(wrapper.find('a').exists()).toBe(false);
    expect(wrapper.text()).toContain('unavailable');
  },
);
