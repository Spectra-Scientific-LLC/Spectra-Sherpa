/* eslint-disable vue/one-component-per-file */
import { mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  routeMeta: { public: false as boolean },
  appMode: { __v_isRef: true, value: "local" },
  hasLLMConfigured: { __v_isRef: true, value: false },
  backendConnected: { __v_isRef: true, value: true },
  backendDegraded: { __v_isRef: true, value: false },
  checkingStatus: { __v_isRef: true, value: false },
  pluginFailureCount: { __v_isRef: true, value: 0 },
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
  authStore: {
    user: { id: 7, username: "alice", is_superuser: false },
    logout: vi.fn(),
  },
  projectStore: {
    currentProjectId: 1,
    currentProject: { id: 1, name: "Demo Project" },
    projectList: [{ id: 1, name: "Demo Project", modified: "2026-03-16" }],
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
  },
  experimentStore: {
    experiments: [] as Array<Record<string, unknown>>,
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
    hasLLMConfigured: mocks.hasLLMConfigured,
  }),
}));

vi.mock("@/composables/useBackendStatus", () => ({
  useBackendStatus: () => ({
    backendConnected: mocks.backendConnected,
    backendDegraded: mocks.backendDegraded,
    checkingStatus: mocks.checkingStatus,
    pluginFailureCount: mocks.pluginFailureCount,
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

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => mocks.authStore,
}));

vi.mock("@/stores/job", () => ({
  useJobStore: () => mocks.jobStore,
}));

vi.mock("@/stores/project", () => ({
  useProjectStore: () => mocks.projectStore,
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
  name: "Button",
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
  },
  emits: ["update:modelValue", "change"],
  template: "<div v-bind=\"$attrs\"><slot name=\"value\" :value=\"modelValue\" /></div>",
});

const MenuStub = defineComponent({
  name: "Menu",
  template: "<div class=\"menu-stub\"><slot /></div>",
});

const RouterViewStub = defineComponent({
  name: "RouterView",
  template: "<div data-test=\"router-view\" />",
});

const TopbarStub = defineComponent({
  name: "Topbar",
  props: {
    navCollapsed: { type: Boolean, default: false },
    chatCollapsed: { type: Boolean, default: false },
    showChatToggle: { type: Boolean, default: true },
  },
  template: "<div data-test=\"topbar-stub\" />",
});

const ChatPanelStub = defineComponent({
  name: "ChatPanel",
  props: {
    compact: { type: Boolean, default: false },
    collapsed: { type: Boolean, default: false },
  },
  template: "<div data-test=\"chat-panel-stub\" />",
});

const SidebarStub = defineComponent({
  name: "Sidebar",
  props: {
    collapsed: { type: Boolean, default: false },
  },
  template: "<div data-test=\"sidebar-stub\" />",
});

vi.mock("@/components/SherpaUpgradeModal.vue", () => ({
  default: defineComponent({ name: "SherpaUpgradeModal", template: "<div />" }),
}));

vi.mock("@/components/DemoUpgradeModal.vue", () => ({
  default: defineComponent({ name: "DemoUpgradeModal", template: "<div />" }),
}));

vi.mock("primevue/toast", () => ({
  default: defineComponent({ name: "Toast", template: "<div />" }),
}));

vi.mock("@/components/ChangePasswordDialog.vue", () => ({
  default: defineComponent({ name: "ChangePasswordDialog", template: "<div />" }),
}));

vi.mock("@/components/UserProfileDialog.vue", () => ({
  default: defineComponent({ name: "UserProfileDialog", template: "<div />" }),
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
    mocks.jobStore.connect.mockClear();
    mocks.jobStore.disconnect.mockClear();
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
});

describe("Topbar action hover labels", () => {
  beforeEach(() => {
    mocks.projectStore.currentProject = { id: 1, name: "Demo Project" };
    mocks.projectStore.currentProjectId = 1;
    mocks.authStore.user = { id: 7, username: "alice", is_superuser: false };
    mocks.appMode.value = "local";
  });

  it("adds descriptive titles to the action icons to the right of the status lights", () => {
    const wrapper = mountTopbar(true);

    expect(wrapper.get('[aria-label="Export project"]').attributes("title")).toBe("Export Project");
    expect(wrapper.get('[aria-label="Toggle chat panel"]').attributes("title")).toBe("Open chat panel");
    expect(wrapper.get('[aria-label="Notifications"]').attributes("title")).toBe("Open notifications");
    expect(wrapper.get('[aria-label="User menu"]').attributes("title")).toBe("Open user menu");
  });

  it("updates the chat toggle label when the chat panel is open", () => {
    const wrapper = mountTopbar(false);

    expect(wrapper.get('[aria-label="Toggle chat panel"]').attributes("title")).toBe("Collapse chat panel");
  });
});
