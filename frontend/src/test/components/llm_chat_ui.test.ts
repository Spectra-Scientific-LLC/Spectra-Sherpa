/* eslint-disable vue/one-component-per-file */
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import type { Component } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  appMode: { __v_isRef: true, value: "local" as string },
  appConfig: {
    __v_isRef: true,
    value: { subscription: { plan: "none" } } as Record<string, unknown>,
  },
  isDemoMode: { __v_isRef: true, value: false },
  featureFlags: {
    chatAssistant: false,
    sherpaAdvisor: false,
    sherpaAgenticTools: false,
  } as Record<string, boolean>,
  apiGet: vi.fn(),
  apiPut: vi.fn(),
  routerPush: vi.fn(),
  toastAdd: vi.fn(),
  llmStore: {
    conversations: [] as Array<Record<string, unknown>>,
    currentConversationId: null as string | null,
    messages: [] as Array<Record<string, unknown>>,
    loading: false,
    streaming: false,
    connectionStatus: "connected",
    lastError: null as string | null,
    currentConfig: null as Record<string, unknown> | null,
    connect: vi.fn(),
    refreshConversations: vi.fn(),
    checkConfigChange: vi.fn(),
    sendMessage: vi.fn(),
    loadConversation: vi.fn(),
    deleteConversation: vi.fn(),
    startNewConversation: vi.fn(),
  },
  sherpaStore: {
    messages: [] as Array<Record<string, unknown>>,
    state: "idle",
    activeTools: [] as Array<Record<string, unknown>>,
    init: vi.fn(),
    dispose: vi.fn(),
    syncWorkflow: vi.fn(),
    sendMessage: vi.fn(),
    clearMessages: vi.fn(),
  },
  experimentStore: {
    experiments: [] as Array<Record<string, unknown>>,
    fetchExperiments: vi.fn(),
  },
  workflowStore: {
    nodes: [] as Array<Record<string, unknown>>,
    edges: [] as Array<Record<string, unknown>>,
    workflowName: "Untitled",
    workflowDescription: "",
    currentTemplateId: null as string | null,
    workflowId: null as number | null,
    lastExecutionResults: {} as Record<string, unknown>,
    lastExecutionDiagnostics: {} as Record<string, unknown>,
    getNodeMetadata: vi.fn(() => null),
  },
  projectStore: {
    currentProjectId: 42,
  },
  authStore: {
    user: { id: 7, username: "alice" },
  },
}));

vi.mock("@/api/client", () => ({
  default: {
    get: mocks.apiGet,
    put: mocks.apiPut,
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({
    push: mocks.routerPush,
  }),
}));

vi.mock("primevue/usetoast", () => ({
  useToast: () => ({
    add: mocks.toastAdd,
  }),
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appMode: mocks.appMode,
    appConfig: mocks.appConfig,
    isFeatureEnabled: (feature: string) => Boolean(mocks.featureFlags[feature]),
  }),
}));

vi.mock("@/composables/useDemoMode", () => ({
  useDemoMode: () => ({
    isDemoMode: mocks.isDemoMode,
  }),
}));

vi.mock("@/stores/llm", () => ({
  useLlmStore: () => mocks.llmStore,
}));

vi.mock("@/stores/sherpa", () => ({
  useSherpaStore: () => mocks.sherpaStore,
}));

vi.mock("@/stores/experiment", () => ({
  useExperimentStore: () => mocks.experimentStore,
}));

vi.mock("@/stores/workflow", () => ({
  useWorkflowStore: () => mocks.workflowStore,
}));

vi.mock("@/stores/project", () => ({
  useProjectStore: () => mocks.projectStore,
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => mocks.authStore,
}));

vi.mock("@/utils/format", () => ({
  formatDateTime: () => "2026-03-13 10:00",
}));

import ChatPanel from "@/components/ChatPanel.vue";
import DataPrivacyTab from "@/views/settings/DataPrivacyTab.vue";

const ButtonStub = defineComponent({
  name: "AppButtonStub",
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

const InputTextStub = defineComponent({
  name: "InputText",
  inheritAttrs: false,
  props: {
    modelValue: { type: String, default: "" },
    disabled: { type: Boolean, default: false },
  },
  emits: ["update:modelValue", "keyup.enter"],
  template: `
    <input
      v-bind="$attrs"
      :value="modelValue"
      :disabled="disabled"
      @input="$emit('update:modelValue', $event.target.value)"
      @keyup.enter="$emit('keyup.enter', $event)"
    />
  `,
});

const MenuStub = defineComponent({
  name: "AppMenuStub",
  template: "<div class=\"menu-stub\"><slot /></div>",
});

const InputSwitchStub = defineComponent({
  name: "InputSwitch",
  inheritAttrs: false,
  props: {
    modelValue: { type: Boolean, default: false },
    disabled: { type: Boolean, default: false },
  },
  emits: ["update:modelValue", "change"],
  template: `
    <button
      v-bind="$attrs"
      data-test="input-switch"
      :data-disabled="String(disabled)"
      @click="disabled ? undefined : ($emit('update:modelValue', !modelValue), $emit('change'))"
    >
      {{ modelValue ? "on" : "off" }}
    </button>
  `,
});

const mountWithUiStubs = (component: Component) =>
  mount(component, {
    global: {
      stubs: {
        Button: ButtonStub,
        InputText: InputTextStub,
        Menu: MenuStub,
        InputSwitch: InputSwitchStub,
      },
      directives: {
        tooltip: () => undefined,
      },
    },
  });

describe("DataPrivacyTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.appMode.value = "local";
    mocks.appConfig.value = { subscription: { plan: "none" } };
    mocks.isDemoMode.value = false;
    mocks.featureFlags.chatAssistant = false;
    mocks.apiGet.mockResolvedValue({
      data: {
        allow_llm_chat: true,
        allow_llm_context: true,
        allow_nist_queries: false,
        allow_export: false,
        allow_spectrasherpa_sync: false,
      },
    });
    mocks.apiPut.mockResolvedValue({ data: { ok: true } });
  });

  it("disables workflow-context sharing in local mode and forces it off on save", async () => {
    const wrapper = mountWithUiStubs(DataPrivacyTab);
    await flushPromises();

    expect(wrapper.text()).toContain("Context-aware chat requires a Sherpa subscription.");
    const switches = wrapper.findAll('[data-test="input-switch"]');
    expect(switches).toHaveLength(4);
    expect(switches[1].attributes("data-disabled")).toBe("true");

    await switches[0].trigger("click");
    await flushPromises();

    expect(mocks.apiPut).toHaveBeenCalledWith("/egress/defaults", expect.objectContaining({
      allow_llm_chat: false,
      allow_llm_context: false,
    }));
  });

  it("disables workflow-context sharing in hybrid mode when chatAssistant is unavailable", async () => {
    mocks.appMode.value = "hybrid";
    mocks.featureFlags.chatAssistant = false;

    const wrapper = mountWithUiStubs(DataPrivacyTab);
    await flushPromises();

    expect(wrapper.text()).toContain("Context-aware chat requires a Sherpa subscription.");
    const switches = wrapper.findAll('[data-test="input-switch"]');
    expect(switches[1].attributes("data-disabled")).toBe("true");
  });

  it("disables workflow-context sharing until AI chat is enabled", async () => {
    mocks.appMode.value = "hybrid";
    mocks.featureFlags.chatAssistant = true;
    mocks.apiGet.mockResolvedValue({
      data: {
        allow_llm_chat: false,
        allow_llm_context: true,
        allow_nist_queries: false,
        allow_export: false,
        allow_spectrasherpa_sync: false,
      },
    });

    const wrapper = mountWithUiStubs(DataPrivacyTab);
    await flushPromises();

    expect(wrapper.text()).toContain("Enable AI Chat to share workflow context with Sherpa.");
    const switches = wrapper.findAll('[data-test="input-switch"]');
    expect(switches[1].attributes("data-disabled")).toBe("true");
  });

  it("enables workflow-context sharing when subscription chat is available", async () => {
    mocks.appMode.value = "hybrid";
    mocks.featureFlags.chatAssistant = true;
    mocks.apiGet.mockResolvedValue({
      data: {
        allow_llm_chat: true,
        allow_llm_context: true,
        allow_nist_queries: false,
        allow_export: false,
        allow_spectrasherpa_sync: false,
      },
    });

    const wrapper = mountWithUiStubs(DataPrivacyTab);
    await flushPromises();

    expect(wrapper.text()).toContain("Allow workflow structure, parameters, and execution summaries to be sent to Sherpa for context-aware chat.");
    const switches = wrapper.findAll('[data-test="input-switch"]');
    expect(switches[1].attributes("data-disabled")).toBe("false");
  });

  it("locks both AI chat toggles on in demo mode", async () => {
    mocks.appMode.value = "enterprise";
    mocks.isDemoMode.value = true;
    mocks.featureFlags.chatAssistant = true;
    mocks.apiGet.mockResolvedValue({
      data: {
        allow_llm_chat: false,
        allow_llm_context: false,
        allow_nist_queries: false,
        allow_export: false,
        allow_spectrasherpa_sync: false,
      },
    });

    const wrapper = mountWithUiStubs(DataPrivacyTab);
    await flushPromises();

    expect(wrapper.text()).toContain("AI Chat is always enabled in the Sherpa demo.");
    expect(wrapper.text()).toContain("Workflow context sharing is always enabled in the Sherpa demo.");
    const switches = wrapper.findAll('[data-test="input-switch"]');
    expect(switches[0].attributes("data-disabled")).toBe("true");
    expect(switches[1].attributes("data-disabled")).toBe("true");
  });
});

describe("ChatPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.appMode.value = "local";
    mocks.appConfig.value = { subscription: { plan: "none" } };
    mocks.isDemoMode.value = false;
    mocks.featureFlags.chatAssistant = false;
    mocks.featureFlags.sherpaAdvisor = false;
    mocks.featureFlags.sherpaAgenticTools = false;
    mocks.apiGet.mockImplementation((url: string) => {
      if (url === "/egress/defaults") {
        return Promise.resolve({ data: { allow_llm_chat: true } });
      }
      return Promise.resolve({ data: [] });
    });
    mocks.llmStore.currentConfig = null;
    mocks.llmStore.messages = [];
    mocks.llmStore.conversations = [];
    mocks.llmStore.loading = false;
    mocks.llmStore.streaming = false;
    mocks.authStore.user = { id: 7, username: "alice" };
  });

  it("shows local BYOK setup copy and local settings control in local mode", async () => {
    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    expect(wrapper.text()).toContain("Configure an LLM API key in Settings to enable chat.");
    expect(wrapper.find(".llm-settings-btn").exists()).toBe(true);
  });

  it("shows subscription-required copy and hides local settings in non-local mode without chat access", async () => {
    mocks.appMode.value = "hybrid";
    mocks.appConfig.value = { subscription: { plan: "none" } };
    mocks.featureFlags.chatAssistant = false;

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    expect(wrapper.text()).toContain("Chat requires a Sherpa subscription.");
    expect(wrapper.find(".llm-settings-btn").exists()).toBe(false);
  });

  it("shows deployment-unavailable copy when subscribed but chatAssistant is off", async () => {
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { subscription: { plan: "pro" } };
    mocks.featureFlags.chatAssistant = false;

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    expect(wrapper.text()).toContain("Chat is unavailable for this deployment.");
    expect(wrapper.find(".llm-settings-btn").exists()).toBe(false);
  });

  it("shows privacy-gated message before provider/subscription messages when AI chat is disabled", async () => {
    mocks.apiGet.mockImplementation((url: string) => {
      if (url === "/egress/defaults") {
        return Promise.resolve({ data: { allow_llm_chat: false } });
      }
      return Promise.resolve({ data: [] });
    });

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    expect(wrapper.text()).toContain("AI chat is disabled in Settings > Data & Privacy.");
    expect(wrapper.text()).not.toContain("Configure an LLM API key in Settings to enable chat.");
  });
});
