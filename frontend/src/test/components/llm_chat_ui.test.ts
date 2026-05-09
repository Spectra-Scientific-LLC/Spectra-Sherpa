/* eslint-disable vue/one-component-per-file */
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import type { Component, PropType } from "vue";
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
  routerResolve: vi.fn((target: { path?: string; query?: Record<string, unknown> }) => {
    const tab = typeof target.query?.tab === "string" ? `?tab=${target.query.tab}` : "";
    return { href: `${target.path || ""}${tab}` };
  }),
  route: {
    path: "/workflow",
    query: {} as Record<string, unknown>,
  },
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
    conversations: [] as Array<Record<string, unknown>>,
    currentConversationId: null as string | null,
    state: "idle",
    isSyncing: false,
    isChatting: false,
    activeTools: [] as Array<Record<string, unknown>>,
    subscriptionRequired: null as string | null,
    subscriptionUpgradeUrl: null as string | null,
    init: vi.fn(),
    dispose: vi.fn(),
    syncWorkflow: vi.fn(),
    sendMessage: vi.fn(),
    clearMessages: vi.fn(),
    refreshConversations: vi.fn(),
    startNewConversation: vi.fn(),
    loadConversation: vi.fn(),
    deleteConversation: vi.fn(),
    openSubscriptionUpgrade: vi.fn(),
  },
  advisorStore: {
    activeChannelId: null as number | null,
    activeNodeId: null as number | null,
    activeTopicId: null as number | null,
    activeNode: null as Record<string, unknown> | null,
    topics: [] as Array<Record<string, unknown>>,
    createTopic: vi.fn(async () => ({ id: 101, conversation_id: null })),
    setActiveTopic: vi.fn(async () => undefined),
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
    resolve: mocks.routerResolve,
  }),
  useRoute: () => mocks.route,
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

vi.mock("@/stores/advisor", () => ({
  useAdvisorStore: () => mocks.advisorStore,
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

const ButtonStub = defineComponent({
  name: "AppButtonStub",
  inheritAttrs: false,
  props: {
    disabled: { type: Boolean, default: false },
    label: { type: String, default: "" },
  },
  emits: ["click"],
  template: `
    <button v-bind="$attrs" :disabled="disabled" @click="$emit('click', $event)">
      <slot>{{ label }}</slot>
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
  props: {
    model: { type: Array as PropType<Array<Record<string, unknown>>>, default: () => [] },
  },
  methods: {
    toggle() {
      return undefined;
    },
  },
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

const DropdownStub = defineComponent({
  name: "Dropdown",
  inheritAttrs: false,
  props: {
    modelValue: { type: [String, Number, null] as PropType<string | number | null>, default: null },
    options: { type: Array as PropType<Array<Record<string, unknown>>>, default: () => [] },
    optionLabel: { type: String, default: "label" },
    optionValue: { type: String, default: "value" },
    placeholder: { type: String, default: "" },
    disabled: { type: Boolean, default: false },
  },
  emits: ["update:modelValue"],
  template: `
    <select
      v-bind="$attrs"
      :value="modelValue ?? ''"
      :disabled="disabled"
      @change="$emit('update:modelValue', $event.target.value || null)"
    >
      <option value="">{{ placeholder }}</option>
      <option v-for="opt in options" :key="opt[optionValue]" :value="opt[optionValue]">
        {{ opt[optionLabel] }}
      </option>
    </select>
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
        Dropdown: DropdownStub,
      },
      directives: {
        tooltip: () => undefined,
      },
    },
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
    mocks.route.path = "/workflow";
    mocks.route.query = {};
    mocks.llmStore.currentConfig = null;
    mocks.llmStore.messages = [];
    mocks.llmStore.conversations = [];
    mocks.llmStore.loading = false;
    mocks.llmStore.streaming = false;
    mocks.sherpaStore.messages = [];
    mocks.sherpaStore.conversations = [];
    mocks.sherpaStore.currentConversationId = null;
    mocks.sherpaStore.state = "idle";
    mocks.sherpaStore.isSyncing = false;
    mocks.sherpaStore.isChatting = false;
    mocks.sherpaStore.activeTools = [];
    mocks.sherpaStore.subscriptionRequired = null;
    mocks.sherpaStore.subscriptionUpgradeUrl = null;
    mocks.advisorStore.activeChannelId = null;
    mocks.advisorStore.activeNodeId = null;
    mocks.advisorStore.activeTopicId = null;
    mocks.advisorStore.activeNode = null;
    mocks.advisorStore.topics = [];
    mocks.workflowStore.workflowId = null;
    mocks.workflowStore.lastExecutionResults = {};
    mocks.authStore.user = { id: 7, username: "alice" };
  });

  it("shows local BYO endpoint setup copy in local mode", async () => {
    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    expect(wrapper.text()).toContain("Set CHAT_ENDPOINT_URL and CHAT_ENDPOINT_KEY in your environment, or configure local chat in Settings.");
    expect(wrapper.find(".setup-link").exists()).toBe(false);
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
    expect(wrapper.text()).not.toContain("Set CHAT_ENDPOINT_URL and CHAT_ENDPOINT_KEY in your environment, or configure local chat in Settings.");
  });

  it("shows only Sherpa Advisor in demo mode when Sherpa is available", async () => {
    mocks.appMode.value = "enterprise";
    mocks.isDemoMode.value = true;
    mocks.appConfig.value = { subscription: { plan: "demo" } };
    mocks.featureFlags.chatAssistant = true;
    mocks.featureFlags.sherpaAdvisor = true;

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    expect(wrapper.text()).toContain("Sherpa Advisor");
    expect(wrapper.text()).not.toContain("LLM Chat");
  });

  it("renders LLM assistant markdown and math with the shared renderer", async () => {
    mocks.featureFlags.chatAssistant = true;
    mocks.llmStore.messages = [
      { role: "assistant", content: "**PLS-DA**\n\n$$y = x^2$$" },
    ];

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    const assistantBubble = wrapper.find(".chat-message.assistant .chat-bubble--md");
    expect(assistantBubble.exists()).toBe(true);
    expect(assistantBubble.html()).toContain("<strong>PLS-DA</strong>");
    expect(assistantBubble.html()).toContain("katex");
  });

  it("opens the standalone Sherpa view with the current Sherpa tab preserved", async () => {
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { subscription: { plan: "demo" } };
    mocks.featureFlags.chatAssistant = true;
    mocks.featureFlags.sherpaAdvisor = true;

    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    const sherpaTab = wrapper.findAll("button").find((button) => button.text() === "Sherpa Advisor");
    expect(sherpaTab).toBeTruthy();
    await sherpaTab!.trigger("click");
    await flushPromises();

    await wrapper.find('[aria-label="Open in new tab"]').trigger("click");

    expect(openSpy).toHaveBeenCalledWith("/llm-chat?tab=sherpa", "_blank", "noopener,noreferrer");
    expect(mocks.routerPush).toHaveBeenCalledWith({
      path: "/llm-chat",
      query: { tab: "sherpa" },
    });

    openSpy.mockRestore();
  });

  it("loads the standalone Sherpa view from route state without auto-syncing the workflow", async () => {
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { subscription: { plan: "demo" } };
    mocks.featureFlags.chatAssistant = true;
    mocks.featureFlags.sherpaAdvisor = true;
    mocks.route.path = "/llm-chat";
    mocks.route.query = { tab: "sherpa" };
    mocks.workflowStore.workflowId = 123;

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    expect(wrapper.find('[aria-label="Sherpa topics"]').exists()).toBe(true);
    expect(mocks.sherpaStore.syncWorkflow).not.toHaveBeenCalled();
  });

  it("shows a Sherpa topics button in the top bar", async () => {
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { subscription: { plan: "demo" } };
    mocks.featureFlags.sherpaAdvisor = true;
    mocks.sherpaStore.conversations = [
      { id: "conv-1", title: "PLS-DA validation", updatedAt: "2026-04-10T12:00:00Z" },
    ];

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    const sherpaTab = wrapper.findAll("button").find((button) => button.text() === "Sherpa Advisor");
    expect(sherpaTab).toBeTruthy();
    await sherpaTab!.trigger("click");
    await flushPromises();

    expect(wrapper.find('[aria-label="Sherpa topics"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("Topics");
  });

  it("creates and activates a server-backed Sherpa topic when starting a new Sherpa conversation", async () => {
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { subscription: { plan: "demo" } };
    mocks.featureFlags.sherpaAdvisor = true;
    mocks.advisorStore.activeNodeId = 55;
    mocks.advisorStore.topics = [];

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    const sherpaTab = wrapper.findAll("button").find((button) => button.text() === "Sherpa Advisor");
    expect(sherpaTab).toBeTruthy();
    await sherpaTab!.trigger("click");
    await flushPromises();

    await wrapper.find('[aria-label="Start new Sherpa conversation"]').trigger("click");
    await flushPromises();

    expect(mocks.advisorStore.createTopic).toHaveBeenCalledWith({ title: "Topic 1" });
    expect(mocks.advisorStore.setActiveTopic).toHaveBeenCalledWith(101);
    expect(mocks.sherpaStore.startNewConversation).toHaveBeenCalled();
  });

  it("does not start an unpersisted server Sherpa topic without an active memory node", async () => {
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { subscription: { plan: "demo" } };
    mocks.featureFlags.sherpaAdvisor = true;
    mocks.advisorStore.activeNodeId = null;

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    const sherpaTab = wrapper.findAll("button").find((button) => button.text() === "Sherpa Advisor");
    expect(sherpaTab).toBeTruthy();
    await sherpaTab!.trigger("click");
    await flushPromises();

    await wrapper.find('[aria-label="Start new Sherpa conversation"]').trigger("click");
    await flushPromises();

    expect(mocks.advisorStore.createTopic).not.toHaveBeenCalled();
    expect(mocks.sherpaStore.startNewConversation).not.toHaveBeenCalled();
    expect(mocks.toastAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        severity: "warn",
        summary: "Select a worksheet first",
      }),
    );
  });

  it("guards against duplicate server topic creation from rapid clicks", async () => {
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { subscription: { plan: "demo" } };
    mocks.featureFlags.sherpaAdvisor = true;
    mocks.advisorStore.activeNodeId = 55;
    let resolveCreateTopic: (value: { id: number; conversation_id: null }) => void = () => undefined;
    mocks.advisorStore.createTopic.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveCreateTopic = resolve;
        }),
    );

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    const sherpaTab = wrapper.findAll("button").find((button) => button.text() === "Sherpa Advisor");
    expect(sherpaTab).toBeTruthy();
    await sherpaTab!.trigger("click");
    await flushPromises();

    const newButton = wrapper.find('[aria-label="Start new Sherpa conversation"]');
    await newButton.trigger("click");
    await newButton.trigger("click");

    expect(mocks.advisorStore.createTopic).toHaveBeenCalledTimes(1);

    resolveCreateTopic({ id: 202, conversation_id: null });
    await flushPromises();

    expect(mocks.advisorStore.setActiveTopic).toHaveBeenCalledWith(202);
    expect(mocks.sherpaStore.startNewConversation).toHaveBeenCalledTimes(1);
  });

  it("shows a contacting status while Sherpa chat is waiting for acceptance", async () => {
    mocks.appMode.value = "enterprise";
    mocks.isDemoMode.value = true;
    mocks.appConfig.value = { subscription: { plan: "demo" } };
    mocks.featureFlags.sherpaAdvisor = true;
    mocks.sherpaStore.state = "chatting";
    mocks.sherpaStore.isChatting = true;
    mocks.sherpaStore.messages = [{ role: "user", content: "tell me about PCA" }];
    mocks.sherpaStore.activeTools = [];

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    expect(wrapper.text()).toContain("Contacting Sherpa Advisor...");
  });

  it("shows a preparing status instead of an empty assistant bubble", async () => {
    mocks.appMode.value = "enterprise";
    mocks.isDemoMode.value = true;
    mocks.appConfig.value = { subscription: { plan: "demo" } };
    mocks.featureFlags.sherpaAdvisor = true;
    mocks.sherpaStore.state = "chatting";
    mocks.sherpaStore.isChatting = true;
    mocks.sherpaStore.messages = [
      { role: "user", content: "tell me about PCA" },
      { role: "assistant", content: "" },
    ];
    mocks.sherpaStore.activeTools = [];

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    expect(wrapper.text()).toContain("Sherpa Advisor is preparing a response...");
    expect(wrapper.findAll(".chat-message.assistant .chat-bubble")).toHaveLength(1);
  });

  it("keeps Sherpa input available for general questions when no workflow is loaded", async () => {
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { subscription: { plan: "demo" } };
    mocks.featureFlags.chatAssistant = true;
    mocks.featureFlags.sherpaAdvisor = true;
    mocks.workflowStore.workflowId = null;

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    const sherpaTab = wrapper.findAll("button").find((button) => button.text() === "Sherpa Advisor");
    expect(sherpaTab).toBeTruthy();
    await sherpaTab!.trigger("click");
    await flushPromises();

    const input = wrapper.find("input");
    expect(input.attributes("placeholder")).toBe(
      "Ask Sherpa about chemistry, datasets, or your next workflow step..."
    );
    expect(input.attributes("disabled")).toBeUndefined();

    expect(mocks.sherpaStore.syncWorkflow).not.toHaveBeenCalled();
  });

  it("routes explicit workflow generation requests through agentic tools", async () => {
    mocks.appMode.value = "enterprise";
    mocks.appConfig.value = { subscription: { plan: "demo" } };
    mocks.featureFlags.chatAssistant = true;
    mocks.featureFlags.sherpaAdvisor = true;
    mocks.featureFlags.sherpaAgenticTools = true;
    mocks.workflowStore.workflowId = 12;

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    const sherpaTab = wrapper.findAll("button").find((button) => button.text() === "Sherpa Advisor");
    expect(sherpaTab).toBeTruthy();
    await sherpaTab!.trigger("click");
    await flushPromises();

    const input = wrapper.find("input");
    await input.setValue("Can you generate a PLSDA model of the same data?");
    await input.trigger("keyup.enter");

    expect(mocks.sherpaStore.sendMessage).toHaveBeenCalledWith(
      "Can you generate a PLSDA model of the same data?",
      true,
    );
  });

  it("prompts users to run the workflow before asking Sherpa about results", async () => {
    mocks.appMode.value = "enterprise";
    mocks.featureFlags.chatAssistant = true;
    mocks.featureFlags.sherpaAdvisor = true;
    mocks.workflowStore.workflowId = 12;
    mocks.workflowStore.lastExecutionResults = {};

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    const sherpaTab = wrapper.findAll("button").find((button) => button.text() === "Sherpa Advisor");
    expect(sherpaTab).toBeTruthy();
    await sherpaTab!.trigger("click");
    await flushPromises();

    const input = wrapper.find("input");
    expect(input.attributes("placeholder")).toBe(
      "Run the workflow first, then ask Sherpa about the results..."
    );
    expect(mocks.sherpaStore.syncWorkflow).not.toHaveBeenCalled();
    expect(wrapper.find('[aria-label="Re-sync workflow"]').exists()).toBe(true);
  });

  it("shows an upgrade action when Sherpa reports a subscription upgrade URL", async () => {
    mocks.appMode.value = "enterprise";
    mocks.featureFlags.sherpaAdvisor = true;
    mocks.sherpaStore.subscriptionRequired = "Upgrade required.";
    mocks.sherpaStore.subscriptionUpgradeUrl = "https://example.com/upgrade";

    const wrapper = mountWithUiStubs(ChatPanel);
    await flushPromises();

    const sherpaTab = wrapper.findAll("button").find((button) => button.text() === "Sherpa Advisor");
    expect(sherpaTab).toBeTruthy();
    await sherpaTab!.trigger("click");
    await flushPromises();

    const upgradeButton = wrapper.findAll("button").find((button) => button.text() === "Upgrade Plan");
    expect(upgradeButton).toBeTruthy();

    await upgradeButton!.trigger("click");
    expect(mocks.sherpaStore.openSubscriptionUpgrade).toHaveBeenCalled();
  });
});
