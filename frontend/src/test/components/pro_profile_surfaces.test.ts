import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SettingsContent from "@/views/settings/SettingsContent.vue";
import Sidebar from "@/components/Sidebar.vue";
import DeployContent from "@/views/deploy/DeployContent.vue";
import AuditContent from "@/views/audit/AuditContent.vue";
import NotificationCenterDrawer from "@/components/NotificationCenterDrawer.vue";
import MemoryMapView from "@/views/project/MemoryMapView.vue";
import BatchRunTab from "@/views/experiments/BatchRunTab.vue";
import LogsView from "@/views/LogsView.vue";
const mocks = vi.hoisted(() => ({
  mode: { value: "enterprise" }, profile: { value: "pro" },
  demo: { value: false }, get: vi.fn(), fetchWatches: vi.fn(),
  fetchDeployRuns: vi.fn(), fetchPredictions: vi.fn(), push: vi.fn(),
}));
vi.mock("@/composables/useAppConfig", () => ({ useAppConfig: () => ({
  appMode: mocks.mode, siteProfile: mocks.profile, appConfig: { value: {} }, isFeatureEnabled: () => true,
}) }));
vi.mock("@/composables/useDemoMode", () => ({ useDemoMode: () => ({ isDemoMode: mocks.demo }) }));
vi.mock("@/composables/usePrimaryNavigation", () => ({ usePrimaryNavigation: () => ({ items: { value: [] } }) }));
vi.mock("@/stores/notification", () => ({ useNotificationStore: () => ({ notifications: [], actionRequired: [], unreadCount: 0 }) }));
vi.mock("@/stores/guidance", () => ({ useGuidanceStore: () => ({ notifications: [], loadNotifications: mocks.get }) }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => ({ currentProjectId: 3, ensureProjectForBrowserTab: async () => ({ id: 3 }) }) }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: mocks.push }), useRoute: () => ({ query: {} }) }));
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: vi.fn() }) }));
vi.mock("@/stores/advisor", () => ({ useAdvisorStore: () => ({ switchScope: vi.fn() }) }));
vi.mock("@/stores/runs", () => ({ useRunsStore: () => ({ fetchPredictions: mocks.fetchPredictions }) }));
vi.mock("@/stores/deploy", () => ({ useDeployStore: () => ({
  watches: [], deployRuns: [], loading: false, runsLoading: false,
  fetchWatches: mocks.fetchWatches, fetchDeployRuns: mocks.fetchDeployRuns,
}) }));
vi.mock("@/api/client", () => ({ default: { get: mocks.get } }));
const settingsOptions = { global: { stubs: {
  ApiKeysTab: true, IntegrationsTab: true, PlateFormatSettingsSection: true,
  GuidanceSettingsSection: true,
  TabView: { template: "<div><slot /></div>" }, TabPanel: { template: "<div><slot /></div>" },
} } };
describe("Pro routes with operator-owned configuration", () => {
  beforeEach(() => {
    mocks.mode.value = "enterprise"; mocks.profile.value = "pro"; mocks.demo.value = false;
    mocks.get.mockReset();
    mocks.fetchWatches.mockReset();
    mocks.fetchDeployRuns.mockReset();
    mocks.fetchPredictions.mockReset();
    mocks.push.mockReset();
  });
  it("offers durable and private project batch prediction", async () => {
    mocks.get.mockImplementation((url: string) => Promise.resolve({
      data: url === "/deploy/capabilities"
        ? { privateBatchUpload: true, maxFiles: 2, maxRequestBytes: 2 * 1024 * 1024 }
        : [],
    }));
    const wrapper = mount(BatchRunTab, { global: { stubs: { PrivateBatchUpload: true, Dropdown: true, MultiSelect: true, InputText: true, Button: true } } });
    await flushPromises();
    // The batch tab renders the uploader once a single model is selected;
    // the empty initial selection keeps the control out of the DOM here.
    expect(wrapper.findComponent({ name: "PrivateBatchUpload" }).exists()).toBe(false);
    expect(wrapper.find(".batch-form").exists()).toBe(true);
    expect(wrapper.text()).toContain("100,000 values");
    expect(mocks.get).toHaveBeenCalledWith("/experiments", { params: { project_id: 3 } });
  });
  it("keeps hosted Pro deployment on a Workbench without blocked requests", async () => {
    mocks.get.mockResolvedValue({ data: [] });
    const deploy = mount(DeployContent, { global: { stubs: {
      ResponsiveHeaderActions: { template: "<div><slot/></div>" }, Button: { props: ["label", "disabled"], template: '<button :disabled="disabled">{{label}}</button>'  },
      ContextualActions: true,
      TabView: { template: "<div><slot/></div>" }, TabPanel: { template: "<div><slot/></div>" },
      Dialog: true, DataTable: true, Column: true,
    } } });
    await flushPromises();
    expect(deploy.text()).toContain("Deploy from a Workbench");
    expect(deploy.text()).toContain("Folder watches and prediction history run on a Workbench");
    expect(deploy.text()).not.toContain("Released applications");
    expect(deploy.text()).not.toContain("New Watch");
    expect(deploy.find('button[title="Refresh"]').exists()).toBe(false);
    expect(mocks.fetchWatches).not.toHaveBeenCalled();
    expect(mocks.fetchDeployRuns).not.toHaveBeenCalled();
    expect(mocks.get).not.toHaveBeenCalled();
    mocks.get.mockClear();
    const audit = mount(AuditContent, { global: { stubs: {
      AuditCapabilityStrip: true, AuditFilterChips: true, AuditEventsTable: true,
      AuditChainStatus: true, AuditReportPackResult: true,
    } } });
    await flushPromises();
    expect(audit.text()).toContain("Audit capabilities are not enabled");
    expect(audit.text()).not.toContain("Request upgrade");
    expect(mocks.get).not.toHaveBeenCalled();
  });
  it.each(["local", "demo"])("routes %s audit upgrade requests to the official support address", async (profile) => {
    mocks.profile.value = profile;
    mocks.mode.value = profile === "local" ? "local" : "enterprise";
    mocks.demo.value = profile === "demo";
    const audit = mount(AuditContent, { global: { stubs: {
      AuditCapabilityStrip: true, AuditFilterChips: true, AuditEventsTable: true,
      AuditChainStatus: true, AuditReportPackResult: true,
    } } });
    await flushPromises();
    const link = audit.get("a.notice-action");
    expect(link.text()).toBe("Request upgrade");
    const destination = new URL(link.attributes("href"));
    expect(destination.protocol).toBe("mailto:");
    expect(destination.pathname).toBe("support@spectrascientific.ai");
    expect(destination.searchParams.get("subject")).toBe("Spectra Sherpa audit upgrade");
    audit.unmount();
  });
  it("synchronizes project deployment history on mount and window focus", async () => {
    mocks.profile.value = "local"; mocks.mode.value = "local";
    mocks.get.mockResolvedValue({ data: [] });
    const wrapper = mount(DeployContent, { global: { stubs: {
      ResponsiveHeaderActions: { template: "<div><slot/></div>" },
      ContextualActions: true,
      Button: { props: ["label", "disabled"], template: '<button :disabled="disabled">{{label}}</button>' },
      TabView: { template: "<div><slot/></div>" }, TabPanel: { template: "<div><slot/></div>" },
      Dialog: true, DataTable: true, Column: true,
    } } });
    await flushPromises();
    expect(mocks.fetchWatches).toHaveBeenCalledTimes(1);
    expect(mocks.fetchDeployRuns).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("No prediction history");
    expect(wrapper.find('button[title="Refresh"]').exists()).toBe(false);
    window.dispatchEvent(new Event("focus")); await flushPromises();
    expect(mocks.fetchWatches).toHaveBeenCalledTimes(2);
    expect(mocks.fetchDeployRuns).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });
  it("shows Pro guidance and loads the project memory map", async () => {
    mocks.get.mockResolvedValue({ data: { project_id: 3, nodes: [], edges: [] } });
    const drawer = mount(NotificationCenterDrawer, { props: { modelValue: true }, global: { stubs: {
      Sidebar: { template: "<div><slot/></div>" }, Button: true,
    } } });
    expect(drawer.find(".guidance-tab").exists()).toBe(true);
    const memory = mount(MemoryMapView, { global: { stubs: {
      ResponsiveHeaderActions: true, Button: true, ProgressSpinner: true,
    } } });
    await flushPromises();
    expect(memory.text()).toContain("No memory yet");
    expect(mocks.get).toHaveBeenCalledWith("/memory/map", { params: { project_id: 3 } });
  });
  it("offers HITRAN, disclosure, acquisition, and Guidance settings on Pro", () => {
    const wrapper = mount(SettingsContent, settingsOptions);
    expect(wrapper.text()).toContain("Hosted providers are managed by your operator");
    expect(wrapper.findComponent({ name: "ApiKeysTab" }).props("hitranOnly")).toBe(true);
    expect(wrapper.findComponent({ name: "IntegrationsTab" }).props("privacyOnly")).toBe(true);
    expect(wrapper.findComponent({ name: "PlateFormatSettingsSection" }).exists()).toBe(true);
    expect(wrapper.findComponent({ name: "GuidanceSettingsSection" }).exists()).toBe(true);
  });
  it.each(["demo", "local"])("retains the existing %s settings surface", (profile) => {
    mocks.profile.value = profile;
    mocks.mode.value = profile === "local" ? "local" : "enterprise";
    mocks.demo.value = profile === "demo";
    const wrapper = mount(SettingsContent, settingsOptions);
    expect(wrapper.findComponent({ name: "ApiKeysTab" }).exists()).toBe(true);
  });
  it("does not advertise localhost server logs to hosted Pro customers", () => {
    const wrapper = mount(Sidebar, { props: { collapsed: false }, global: { stubs: {
      RouterLink: { props: ["to"], template: '<a :href="to"><slot/></a>' },
    } } });
    expect(wrapper.find('a[href="/logs"]').exists()).toBe(false);
    expect(wrapper.find('a[href="/runs"]').exists()).toBe(true);
  });
  it("retains the local Logs link and refresh request", async () => {
    mocks.mode.value = "local"; mocks.profile.value = "local";
    mocks.get.mockResolvedValue({ data: { logs: [{ level: "INFO", timestamp: "now", message: "Local diagnostic" }] } });
    const sidebar = mount(Sidebar, { props: { collapsed: false }, global: { stubs: {
      RouterLink: { props: ["to"], template: '<a :href="to"><slot/></a>' },
    } } });
    expect(sidebar.find('a[href="/logs"]').exists()).toBe(true);
    const logs = mount(LogsView, { global: { stubs: {
      ResponsiveHeaderActions: { template: '<div><slot/></div>' },
      Button: { props: ["label", "disabled"], template: '<button :disabled="disabled">{{label}}</button>' },
    } } });
    await logs.get("button").trigger("click");
    expect(mocks.get).toHaveBeenCalledWith("/logs");
  });
  it("explains a direct Logs deep link without calling the blocked endpoint", async () => {
    const wrapper = mount(LogsView, { global: { stubs: {
      ResponsiveHeaderActions: { template: '<div><slot/></div>' },
      Button: { props: ["label", "disabled"], template: '<button :disabled="disabled">{{label}}</button>' },
    } } });
    expect(wrapper.text()).toContain("deployment operator");
    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
    await wrapper.get("button").trigger("click");
    expect(mocks.get).not.toHaveBeenCalled();
  });
});
