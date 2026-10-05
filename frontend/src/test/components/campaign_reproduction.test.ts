import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import CampaignReproduction from '@/views/project/CampaignReproduction.vue';

const post = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ default: { post } }));

async function selectInputs(wrapper: ReturnType<typeof mount>) {
  for (const input of wrapper.findAll('input[type="file"]')) {
    Object.defineProperty(input.element, 'files', { value: [new File(['fixture'], 'local')], configurable: true });
    await input.trigger('change');
  }
  await wrapper.get('input[placeholder]').setValue('public-corn-m5-moisture-v1');
}

describe('CampaignReproduction', () => {
  beforeEach(() => { post.mockReset(); });
  it('submits the selected local inputs and separates identity from scientific reproduction', async () => {
    post.mockResolvedValue({ data: {
      package_sha256: 'package-digest',
      integrity_verified: { status: 'passed', reason: null },
      publisher_authenticated: { status: 'passed', reason: null },
      validation_reproduced: { status: 'not_run', reason: 'fixture_mismatch' },
      application_reproduced: { status: 'not_run', reason: 'fixture_mismatch' },
    } });
    const wrapper = mount(CampaignReproduction, { props: { projectId: 7 } });
    await selectInputs(wrapper);
    await wrapper.get('form').trigger('submit');
    await flushPromises();
    expect(post.mock.calls[0][0]).toBe('/projects/7/reproduce-campaign');
    const body = post.mock.calls[0][1] as FormData;
    expect(body.get('projection_id')).toBe('public-corn-m5-moisture-v1');
    expect(body.has('package') && body.has('publisher_keys') && body.has('fixture')).toBe(true);
    expect(wrapper.findAll('tbody tr')).toHaveLength(4);
    expect(wrapper.text()).toContain('fixture_mismatch');
    expect(wrapper.text()).toContain('package-digest');
    expect(wrapper.text()).toContain('not_run');
  });
  it('does not show a late result under a different project', async () => {
    let finish!: (value: unknown) => void;
    post.mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const wrapper = mount(CampaignReproduction, { props: { projectId: 7 } });
    await selectInputs(wrapper);
    await wrapper.get('form').trigger('submit');
    expect(wrapper.get('fieldset').attributes()).toHaveProperty('disabled');
    await wrapper.setProps({ projectId: 8 });
    finish({ data: { package_sha256: 'old-project' } });
    await flushPromises();
    expect(wrapper.text()).not.toContain('old-project');
    expect(wrapper.find('table').exists()).toBe(false);
  });
  it('displays an actionable server refusal', async () => {
    post.mockRejectedValue({ response: { data: { detail: 'Selected package does not match this imported project' } } });
    const wrapper = mount(CampaignReproduction, { props: { projectId: 7 } });
    await selectInputs(wrapper);
    await wrapper.get('form').trigger('submit');
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain('does not match');
    expect(wrapper.find('table').exists()).toBe(false);
  });
});
