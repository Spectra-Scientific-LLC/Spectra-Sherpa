/* eslint-disable vue/one-component-per-file */
import { enableAutoUnmount, mount } from "@vue/test-utils";
import { defineComponent, reactive, nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  routeMeta: { public: false as boolean, standalone: false as boolean },
  appMode: { __v_isRef: true, value: "local" },
  appConfig: {
    __v_isRef: true,
    value: { features: { sherpaGuidance: false } },
  },
  hasLLMConfigured: { __v_isRef: true, value: false },
  backendConnected: { __v_isRef: true, value: true },
  checkingStatus: { __v_isRef: true, value: false },
  toastAdd: vi.fn(),
  routerPush: vi.fn(),
  notifySystemEvent: vi.fn(),
  checkBackendStatus: vi.fn(),
  startHealthCheck: vi.fn(),
  stopHealthCheck: vi.fn(),
  jobStore: {
    connect: vi.fn().mockResolvedValue(undefined),
    disconnect: vi.fn(),
  },
  guidanceStart: vi.fn().mockResolvedValue(true),
  guidanceStop: vi.fn(),
  activityStart: vi.fn(),
  activityStop: vi.fn(),
  authStore: {
    user: { id: 7, username: "alice", capabilities: { admin: false } } as {
      id: number;
      username: string;
      capabilities: { admin: boolean };
    } | null,
    logout: vi.fn(),
  },
  projectStore: {
    currentProjectId: 1,
    currentProject: { id: 1, name: "Demo Project" },
    projectList: [{ id: 1, name: "Demo Project", modified: "2026-03-16" }],
    fetchProjects: vi.fn().mockResolvedValue(undefined),
    selectProject: vi.fn(),
    createProject: vi.fn(),
    updateProject: vi.fn(),
    exportProject: vi.fn(),
    importProject: vi.fn(),
  },
  notificationStore: {
    unreadCount: 2,
  },
  workflowStore: {
    nodes: [] as Array<Record<string, unknown>>,
    hasUnsavedChanges: false,
    workflowId: null as number | null,
    saveWorkflow: vi.fn(),
  },
  experimentStore: {
    experiments: [] as Array<Record<string, unknown>>,
  },
  provenanceStore: {
    projectId: null as number | null,
    summary: null as null | { verified_at: string; records: Array<Record<string, unknown>> },
    error: null,
    refresh: vi.fn().mockResolvedValue(undefined),
  },
  llmStore: {
    connectionStatus: "disconnected",
    configStatus: "missing",
    startConfigPolling: vi.fn(),
    stopConfigPolling: vi.fn(),
  },
}));

vi.mock("vue-router", async () => {
  const actual = await vi.importActual<typeof import("vue-router")>("vue-router");
  return {
    ...actual,
    useRoute: () => ({
      meta: mocks.routeMeta,
    }),
    useRouter: () => ({
      push: mocks.routerPush,
      currentRoute: { value: { fullPath: "/" } },
    }),
  };
});

vi.mock("primevue/usetoast", () => ({
  useToast: () => ({
    add: mocks.toastAdd,
  }),
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appMode: mocks.appMode,
    appConfig: mocks.appConfig,
    hasLLMConfigured: mocks.hasLLMConfigured,
    reloadConfig: vi.fn().mockResolvedValue(true),
  }),
}));

vi.mock("@/composables/useBackendStatus", () => ({
  useBackendStatus: () => ({
    backendConnected: mocks.backendConnected,
    checkingStatus: mocks.checkingStatus,
    checkBackendStatus: mocks.checkBackendStatus,
    startHealthCheck: mocks.startHealthCheck,
    stopHealthCheck: mocks.stopHealthCheck,
  }),
}));

vi.mock("@/composables/useNotifier", () => ({
  useNotifier: () => ({
    notifySystemEvent: mocks.notifySystemEvent,
  }),
}));

vi.mock("@/stores/auth", async () => {
  const { reactive } = await vi.importActual<typeof import("vue")>("vue");
  mocks.authStore = reactive(mocks.authStore) as typeof mocks.authStore;
  return {
    useAuthStore: () => mocks.authStore,
  };
});

vi.mock("@/stores/job", () => ({
  useJobStore: () => mocks.jobStore,
}));

vi.mock("@/stores/project", () => ({
  useProjectStore: () => reactive(mocks.projectStore),
}));

vi.mock("@/stores/projectProvenance", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/stores/projectProvenance")>(),
  useProjectProvenanceStore: () => mocks.provenanceStore,
}));

vi.mock("@/stores/notification", () => ({
  useNotificationStore: () => mocks.notificationStore,
}));

vi.mock("@/stores/workflow", () => ({
  useWorkflowStore: () => mocks.workflowStore,
}));

vi.mock("@/stores/experiment", () => ({
  useExperimentStore: () => mocks.experimentStore,
}));

vi.mock("@/stores/llm", () => ({
  useLlmStore: () => mocks.llmStore,
}));

const ButtonStub = defineComponent({
  name: "PrimeButton",
  inheritAttrs: false,
  props: {
    disabled: { type: Boolean, default: false },
  },
  emits: ["click"],
  template: `
    <button v-bind="$attrs" :disabled="disabled" @click="$emit('click', $event)">
      <slot />
    </button>
  `,
});

const DropdownStub = defineComponent({
  name: "Dropdown",
  inheritAttrs: false,
  props: {
    modelValue: { type: [Number, String, null], default: null },
    options: { type: Array, default: () => [] },
  },
  emits: ["update:modelValue", "change"],
  template: '<div v-bind="$attrs"><slot name="value" :value="modelValue" /></div>',
});

const MenuStub = defineComponent({
  name: "PrimeMenu",
  template: '<div class="menu-stub"><slot /></div>',
});

const RouterViewStub = defineComponent({
  name: "RouterView",
  template: '<div data-test="router-view" />',
});

const TopbarStub = defineComponent({
  name: "Topbar",
  props: {
    navCollapsed: { type: Boolean, default: false },
    chatCollapsed: { type: Boolean, default: false },
    showChatToggle: { type: Boolean, default: true },
  },
  template: '<div data-test="topbar-stub" />',
});

const ChatPanelStub = defineComponent({
  name: "ChatPanel",
  props: {
    compact: { type: Boolean, default: false },
    collapsed: { type: Boolean, default: false },
  },
  template: '<div data-test="chat-panel-stub" />',
});

const SidebarStub = defineComponent({
  name: "Sidebar",
  props: {
    collapsed: { type: Boolean, default: false },
  },
  template: '<div data-test="sidebar-stub" />',
});

vi.mock("@/components/SherpaUpgradeModal.vue", () => ({
  default: defineComponent({ name: "SherpaUpgradeModal", template: "<div />" }),
}));

vi.mock("@/components/DemoUpgradeModal.vue", () => ({
  default: defineComponent({ name: "DemoUpgradeModal", template: "<div />" }),
}));

vi.mock("@/components/AppFooter.vue", () => ({
  default: defineComponent({ name: "AppFooter", template: "<div />" }),
}));

vi.mock("@/components/AboutDialog.vue", () => ({
  default: defineComponent({ name: "AboutDialog", template: "<div />" }),
}));

vi.mock("@/components/guidance/GuidanceToast.vue", () => ({
  default: defineComponent({ name: "GuidanceToast", template: "<div />" }),
}));

vi.mock("@/components/guidance/GuidanceGlowOverlay.vue", () => ({
  default: defineComponent({ name: "GuidanceGlowOverlay", template: "<div />" }),
}));

vi.mock("@/composables/useGuidance", () => ({
  useGuidance: () => ({
    start: mocks.guidanceStart,
    stop: mocks.guidanceStop,
  }),
}));

vi.mock("@/composables/useActivityTracker", () => ({
  useActivityTracker: () => ({
    start: mocks.activityStart,
    stop: mocks.activityStop,
  }),
}));

vi.mock("primevue/toast", () => ({
  default: defineComponent({ name: "Toast", template: "<div />" }),
}));

// ChangePasswordDialog and UserProfileDialog were removed from OSS in
// Phase 1b — they live in the server-provided auth module now.

vi.mock("@/composables/useTopbarMenu", () => ({
  useTopbarMenu: () => ({
    items: { value: [] as unknown[] },
    addItems: vi.fn(),
    removeItems: vi.fn(),
    clear: vi.fn(),
    _internal: { value: [] as unknown[] },
  }),
}));

vi.mock("@/components/ProjectDialog.vue", () => ({
  default: defineComponent({ name: "ProjectDialog", template: "<div />" }),
}));

vi.mock("@/components/ProjectDetailsDrawer.vue", () => ({
  default: defineComponent({ name: "ProjectDetailsDrawer", template: "<div />" }),
}));

vi.mock("@/components/NotificationCenterDrawer.vue", () => ({
  default: defineComponent({ name: "NotificationCenterDrawer", template: "<div />" }),
}));

import MainLayout from "@/layouts/MainLayout.vue";
import Topbar from "@/components/Topbar.vue";

enableAutoUnmount(afterEach);

const mainLayoutMountOptions = {
  global: {
    stubs: {
      RouterView: RouterViewStub,
      Topbar: TopbarStub,
      ChatPanel: ChatPanelStub,
      Sidebar: SidebarStub,
    },
  },
};

const mountTopbar = (chatCollapsed = true) =>
  mount(Topbar, {
    props: {
      navCollapsed: false,
      chatCollapsed,
      showChatToggle: true,
    },
    global: {
      stubs: {
        Button: ButtonStub,
        Dropdown: DropdownStub,
        Menu: MenuStub,
      },
    },
  });

describe("MainLayout chat panel defaults", () => {
  beforeEach(() => {
    localStorage.clear();
    mocks.routeMeta.public = false;
    mocks.routeMeta.standalone = false;
    mocks.appMode.value = "local";
    mocks.appConfig.value = { features: { sherpaGuidance: false } };
    mocks.backendConnected.value = true;
    mocks.authStore.user = { id: 7, username: "alice", capabilities: { admin: false } };
    mocks.jobStore.connect.mockClear();
    mocks.jobStore.disconnect.mockClear();
    mocks.guidanceStart.mockReset();
    mocks.guidanceStart.mockResolvedValue(true);
    mocks.guidanceStop.mockClear();
    mocks.activityStart.mockClear();
    mocks.activityStop.mockClear();
  });

  it("starts with the chat panel collapsed on first load", () => {
    const wrapper = mount(MainLayout, mainLayoutMountOptions);

    expect(localStorage.getItem("chatCollapsed")).toBe("true");
    expect(wrapper.findComponent(TopbarStub).props("chatCollapsed")).toBe(true);
    expect(wrapper.findComponent(ChatPanelStub).props("collapsed")).toBe(true);
  });

  it("preserves an existing chat panel preference", () => {
    localStorage.setItem("chatCollapsed", "false");
    const wrapper = mount(MainLayout, mainLayoutMountOptions);

    expect(wrapper.findComponent(TopbarStub).props("chatCollapsed")).toBe(false);
    expect(wrapper.findComponent(ChatPanelStub).props("collapsed")).toBe(false);
  });

  it("renders standalone routes without the application chrome", () => {
    mocks.routeMeta.standalone = true;
    const wrapper = mount(MainLayout, mainLayoutMountOptions);

    expect(wrapper.find('[data-test="router-view"]').exists()).toBe(true);
    expect(wrapper.findComponent(TopbarStub).exists()).toBe(false);
    expect(wrapper.findComponent(SidebarStub).exists()).toBe(false);
    expect(wrapper.findComponent(ChatPanelStub).exists()).toBe(false);
  });

  it("does not start guidance when hosted configuration does not advertise it", async () => {
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { features: { sherpaGuidance: false } };
    mount(MainLayout, mainLayoutMountOptions);
    await nextTick();
    await nextTick();
    expect(mocks.guidanceStart).not.toHaveBeenCalled();
  });
  it("starts guidance after authenticated server-backed config is ready", async () => {
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { features: { sherpaGuidance: true } };

    mount(MainLayout, mainLayoutMountOptions);
    await nextTick();
    await nextTick();

    expect(mocks.guidanceStart).toHaveBeenCalledTimes(1);
    expect(mocks.activityStart).toHaveBeenCalledTimes(1);
  });

  it("does not start guidance before an authenticated user is available", async () => {
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { features: { sherpaGuidance: true } };
    mocks.authStore.user = null;

    mount(MainLayout, mainLayoutMountOptions);
    await nextTick();
    await nextTick();

    expect(mocks.guidanceStart).not.toHaveBeenCalled();
    expect(mocks.activityStart).not.toHaveBeenCalled();
  });

  it("starts guidance once when login rehydrates the user after layout mount", async () => {
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { features: { sherpaGuidance: true } };
    mocks.authStore.user = null;

    mount(MainLayout, mainLayoutMountOptions);
    await nextTick();
    await nextTick();

    expect(mocks.guidanceStart).not.toHaveBeenCalled();
    expect(mocks.activityStart).not.toHaveBeenCalled();

    mocks.authStore.user = { id: 7, username: "alice", capabilities: { admin: false } };
    await nextTick();
    await nextTick();

    expect(mocks.guidanceStart).toHaveBeenCalledTimes(1);
    expect(mocks.activityStart).toHaveBeenCalledTimes(1);

    await nextTick();

    expect(mocks.guidanceStart).toHaveBeenCalledTimes(1);
    expect(mocks.activityStart).toHaveBeenCalledTimes(1);
  });

  it("does not attach the activity tracker if readiness is lost during guidance.start()", async () => {
    // Review finding: guidance.start() can resolve after a retry/backoff
    // window that spanned a logout.  The tracker must not bind to a
    // torn-down session — readiness is re-checked after the await.
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { features: { sherpaGuidance: true } };

    let resolveStart: () => void = () => {};
    mocks.guidanceStart.mockImplementation(
      () =>
        new Promise<boolean>((resolve) => {
          resolveStart = () => resolve(true);
        }),
    );

    mount(MainLayout, mainLayoutMountOptions);
    await nextTick();
    await nextTick();
    expect(mocks.guidanceStart).toHaveBeenCalledTimes(1);
    expect(mocks.activityStart).not.toHaveBeenCalled();

    // Readiness lost while start() is still in flight.
    mocks.authStore.user = null;
    await nextTick();
    await nextTick();

    // start() finally resolves — the post-await readiness re-check must
    // refuse to start the tracker and must stop guidance instead.
    resolveStart();
    await nextTick();
    await nextTick();

    expect(mocks.activityStart).not.toHaveBeenCalled();
    expect(mocks.guidanceStop).toHaveBeenCalled();
  });

  it("restarts guidance if readiness returns before a cancelled startup unwinds", async () => {
    // Review follow-up: a quick logout/login bounce can restore readiness
    // before the cancelled guidance.start() promise resolves.  The stale
    // startup must not be marked started, and MainLayout must kick off a
    // fresh startup once its in-flight guard is cleared.
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { features: { sherpaGuidance: true } };

    let resolveFirstStart: () => void = () => {};
    mocks.guidanceStart.mockImplementationOnce(
      () =>
        new Promise<boolean>((resolve) => {
          resolveFirstStart = () => resolve(false);
        }),
    );
    mocks.guidanceStart.mockResolvedValue(true);

    mount(MainLayout, mainLayoutMountOptions);
    await nextTick();
    await nextTick();
    expect(mocks.guidanceStart).toHaveBeenCalledTimes(1);

    mocks.authStore.user = null;
    await nextTick();
    await nextTick();
    mocks.authStore.user = { id: 8, username: "bob", capabilities: { admin: false } };
    await nextTick();
    await nextTick();

    resolveFirstStart();
    await nextTick();
    await nextTick();
    await nextTick();

    expect(mocks.guidanceStart).toHaveBeenCalledTimes(2);
    expect(mocks.activityStart).toHaveBeenCalledTimes(1);
  });
});

describe("Topbar action hover labels", () => {
  beforeEach(() => {
    mocks.projectStore.currentProject = { id: 1, name: "Demo Project" };
    mocks.projectStore.currentProjectId = 1;
    mocks.authStore.user = { id: 7, username: "alice", capabilities: { admin: false } };
    mocks.appMode.value = "local";
    mocks.workflowStore.workflowId = null;
    mocks.workflowStore.nodes = [];
    mocks.workflowStore.hasUnsavedChanges = false;
    mocks.workflowStore.saveWorkflow.mockReset();
    mocks.workflowStore.saveWorkflow.mockResolvedValue(undefined);
    mocks.projectStore.selectProject.mockReset();
    mocks.projectStore.fetchProjects.mockReset();
    mocks.projectStore.fetchProjects.mockResolvedValue(undefined);
    mocks.projectStore.projectList = [{ id: 1, name: "Demo Project", modified: "2026-03-16" }];
    mocks.experimentStore.experiments = [];
    mocks.provenanceStore.projectId = null;
    mocks.provenanceStore.summary = null;
    mocks.provenanceStore.error = null;
  });

  it("loads selector choices for a cold deep link and preserves the loaded project name", async () => {
    mocks.projectStore.projectList = [];
    mocks.projectStore.fetchProjects.mockImplementationOnce(async () => {
      reactive(mocks.projectStore).projectList = [{ id: 1, name: "Loaded project", modified: "2026-09-22" }];
    });
    const wrapper = mountTopbar(true);
    await nextTick();
    expect(mocks.projectStore.fetchProjects).toHaveBeenCalledOnce();
    expect(wrapper.text()).not.toContain("Unknown Project");
    expect(wrapper.findComponent(DropdownStub).props("options")).toEqual(mocks.projectStore.projectList);
  });

  it("saves a dirty workflow before switching projects", async () => {
    mocks.workflowStore.workflowId = 144;
    mocks.workflowStore.hasUnsavedChanges = true;
    mocks.projectStore.currentProject = { id: 2, name: "Second Project" };
    const wrapper = mountTopbar(true);
    const dropdown = wrapper.findComponent(DropdownStub);

    await dropdown.vm.$emit("update:modelValue", 2);
    await dropdown.vm.$emit("change");
    await nextTick();

    expect(mocks.workflowStore.saveWorkflow).toHaveBeenCalledWith({ createVersion: false });
    expect(mocks.projectStore.selectProject).toHaveBeenCalledWith(2);
    expect(mocks.workflowStore.saveWorkflow.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.projectStore.selectProject.mock.invocationCallOrder[0],
    );
  });

  it("keeps the current project when a dirty workflow cannot be saved", async () => {
    mocks.workflowStore.workflowId = 144;
    mocks.workflowStore.hasUnsavedChanges = true;
    mocks.workflowStore.saveWorkflow.mockRejectedValueOnce(new Error("save failed"));
    const wrapper = mountTopbar(true);
    const dropdown = wrapper.findComponent(DropdownStub);

    await dropdown.vm.$emit("update:modelValue", 2);
    await dropdown.vm.$emit("change");
    await nextTick();

    expect(mocks.projectStore.selectProject).not.toHaveBeenCalled();
    expect(mocks.toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({ summary: "Project Switch Stopped" }),
    );
  });

  it("adds descriptive titles to the action icons to the right of the status lights", () => {
    const wrapper = mountTopbar(true);

    expect(wrapper.get('[aria-label="Toggle chat panel"]').attributes("title")).toBe(
      "Open chat panel",
    );
    expect(wrapper.get('[aria-label="Notifications"]').attributes("title")).toBe(
      "Open notifications",
    );
    expect(wrapper.get('[aria-label="User menu"]').attributes("title")).toBe("Open user menu");
  });

  it("shows the active project name in the project-selector dropdown", () => {
    const wrapper = mountTopbar(true);

    // The dropdown's #value slot renders the current project's name as its
    // selected display.  This is the single source of project-context truth
    // in the topbar — a previously duplicated standalone <span> next to the
    // folder icon was removed because it showed the same name twice.
    expect(wrapper.get(".project-value").text()).toBe("Demo Project");
  });

  it("updates the chat toggle label when the chat panel is open", () => {
    const wrapper = mountTopbar(false);

    expect(wrapper.get('[aria-label="Toggle chat panel"]').attributes("title")).toBe(
      "Collapse chat panel",
    );
  });

  it.each([
    ["source", "Source", "missing"],
    ["dataset", "Dataset", "missing"],
    ["model", "Calibrated model", "faulty"],
  ])("shows available %s green despite incomplete provenance", (kind, label, state) => {
    mocks.provenanceStore.projectId = 1;
    mocks.provenanceStore.summary = {
      verified_at: "2026-10-04T00:00:00Z",
      records: [{ kind, label, state, name: "Corn M5", digest: null, detail: "No selection link",
        availability: { state: "healthy", detail: "Available in project." } }],
    };

    const wrapper = mountTopbar(true);

    expect(wrapper.get(`.provenance-indicators [aria-label^="${label}: Available in project."]`).classes()).toContain("status-green");
    expect(wrapper.get('.status-indicators [aria-label="Backend: Connected"]').classes()).toContain("status-green");
  });

  it("shows unavailable model files red even with healthy provenance", () => {
    mocks.provenanceStore.projectId = 1;
    mocks.provenanceStore.summary = {
      verified_at: "2026-10-04T00:00:00Z",
      records: [{ kind: "model", label: "Calibrated model", state: "healthy", name: "PLS",
        availability: { state: "faulty", detail: "Model files missing." } }],
    };
    const wrapper = mountTopbar(true);
    expect(wrapper.get('.provenance-indicators [aria-label^="Calibrated model: Model files missing."]').classes()).toContain("status-red");
  });
});
