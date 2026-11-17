import { flushPromises, mount } from '@vue/test-utils';
import { reactive, nextTick } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import InspectionSettingsSection from '@/views/settings/InspectionSettingsSection.vue';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn(), project: { currentProjectId: 1, currentProject: { name: "" } }, auth: { user: { id: 1 }, sessionRevision: 0 } }));
vi.mock('@/api/client', () => ({ default: mocks }));
vi.mock('@/stores/project', () => ({ useProjectStore: () => mocks.project }));
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocks.auth }));
const connection = { client_id: 'client-a', project_id: 1, client_label: 'Test client', expires_at: '2026-12-01T00:00:00Z', revoked_at: null, credential: 'ssmcp_secret' };

beforeEach(() => {
  vi.clearAllMocks();
  mocks.project = reactive({ currentProjectId: 1, currentProject: { name: 'First' } });
  mocks.auth = reactive({ user: { id: 1 }, sessionRevision: 0 });
  mocks.get.mockResolvedValue({ data: [] });
  mocks.post.mockResolvedValue({ data: connection });
  mocks.delete.mockResolvedValue({});
});

async function issue(wrapper: ReturnType<typeof mount>) {
  await flushPromises();
  await wrapper.get('input[maxlength]').setValue('Test client');
  await wrapper.get('input[name=confirm_external_provider]').setValue(true);
  await wrapper.get('form').trigger('submit');
}

describe('project-scoped inspection credentials', () => {
  it('requires acknowledgement and clears the secret on project switch', async () => {
    const wrapper = mount(InspectionSettingsSection);
    await flushPromises();
    expect(wrapper.get('button[type=submit]').attributes('disabled')).toBeDefined();
    await issue(wrapper);
    await flushPromises();
    expect((wrapper.get('input[readonly]').element as HTMLInputElement).value).toBe(connection.credential);
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ confirm_external_provider: true, ttl_seconds: 86400, project_summaries: false });
    mocks.project.currentProjectId = 2;
    await nextTick();
    expect(wrapper.find('input[readonly]').exists()).toBe(false);
    wrapper.unmount();
  });
  it('requires separate project summary opt-in and resets it after issuance', async () => {
    const wrapper = mount(InspectionSettingsSection);
    await flushPromises();
    const checkbox = wrapper.get('input[name=project_summaries]');
    expect((checkbox.element as HTMLInputElement).checked).toBe(false);
    await checkbox.setValue(true);
    await issue(wrapper);
    await flushPromises();
    expect(mocks.post.mock.calls[0][1].project_summaries).toBe(true);
    expect((checkbox.element as HTMLInputElement).checked).toBe(false);
    wrapper.unmount();
  });
  it('does not display a late issued credential after A to B to A', async () => {
    let resolve!: (value: unknown) => void;
    mocks.post.mockImplementation(() => new Promise((done) => { resolve = done; }));
    const wrapper = mount(InspectionSettingsSection);
    await issue(wrapper);
    mocks.project.currentProjectId = 2;
    await nextTick();
    mocks.project.currentProjectId = 1;
    await nextTick();
    resolve({ data: connection });
    await flushPromises();
    expect(wrapper.find('input[readonly]').exists()).toBe(false);
    wrapper.unmount();
  });
  it('clears a revealed credential on account-session change', async () => {
    const wrapper = mount(InspectionSettingsSection);
    await issue(wrapper);
    await flushPromises();
    mocks.auth.sessionRevision++;
    await nextTick();
    expect(wrapper.find('input[readonly]').exists()).toBe(false);
    wrapper.unmount();
  });
});
