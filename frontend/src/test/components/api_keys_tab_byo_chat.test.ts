/* eslint-disable vue/one-component-per-file */
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
  confirmAction: vi.fn(async () => true),
  advisorEnabled: false,
  realConfirm: false,
  appMode: { __v_isRef: true, value: "local" as string },
  appConfig: { __v_isRef: true, value: { demo: false } as Record<string, unknown> },
}));

vi.mock("@/api/client", () => ({
  default: { get: mocks.apiGet, post: mocks.apiPost, delete: mocks.apiDelete },
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appMode: mocks.appMode,
    appConfig: mocks.appConfig,
    isFeatureEnabled: () => mocks.advisorEnabled,
  }),
}));

// Tests choose the stub or, with mocks.realConfirm, the real owner-scoped dialog state.
vi.mock("@/composables/useConfirmAction", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/composables/useConfirmAction")>();
  return {
    ...actual,
    useConfirmAction: () => {
      const real = actual.useConfirmAction();
      return (options: Parameters<typeof real>[0]) => (mocks.realConfirm ? real(options) : mocks.confirmAction(options));
    },
  };
});

vi.mock("@/utils/authStorage", () => ({
  readStoredApiKey: () => "",
  writeStoredApiKey: vi.fn(),
}));

const ButtonStub = defineComponent({
  inheritAttrs: false,
  props: { label: { type: String, default: "" }, disabled: { type: Boolean, default: false } },
  emits: ["click"],
  template: '<button v-bind="$attrs" :disabled="disabled" @click="$emit(\'click\')">{{ label }}</button>',
});

const InputTextStub = defineComponent({
  inheritAttrs: false,
  props: { modelValue: { type: String, default: "" } },
  emits: ["update:modelValue"],
  template:
    '<input v-bind="$attrs" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
});

const DropdownStub = defineComponent({
  props: {
    modelValue: { type: String, default: "" },
    options: { type: Array, default: () => [] },
    inputId: { type: String, default: "" },
  },
  emits: ["update:modelValue", "change"],
  template: `
    <select :id="inputId" :value="modelValue" @change="$emit('update:modelValue', $event.target.value); $emit('change')">
      <option v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</option>
    </select>
  `,
});

const InputSwitchStub = defineComponent({
  props: { modelValue: { type: Boolean, default: false }, inputId: { type: String, default: "" } },
  emits: ["update:modelValue"],
  template:
    '<input :id="inputId" type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" />',
});

import ApiKeysTab from "@/views/settings/ApiKeysTab.vue";

function mountTab(props: Record<string, unknown> = {}) {
  return mount(ApiKeysTab, {
    props,
    global: {
      stubs: {
        Button: ButtonStub,
        InputText: InputTextStub,
        Dropdown: DropdownStub,
        InputSwitch: InputSwitchStub,
        Tag: true,
      },
    },
  });
}

describe("ApiKeysTab local BYO chat transports", () => {
  beforeEach(() => {
    mocks.apiGet.mockReset();
    mocks.apiPost.mockReset();
    mocks.apiGet.mockImplementation((url: string) => {
      if (url === "/api-keys") return Promise.resolve({ data: [] });
      if (url === "/config/byo-chat-config") {
        return Promise.resolve({
          data: {
            provider: "openai_compatible",
            endpoint_url: "https://api.deepseek.com/v1",
            model: "deepseek-chat",
            has_key: true,
            allow_private_endpoint: false,
            configured: true,
          },
        });
      }
      throw new Error(`Unhandled GET ${url}`);
    });
    mocks.apiPost.mockResolvedValue({ data: { success: true, configured: true } });
  });

  it("sends the native Anthropic transport rather than the OpenAI-compatible default", async () => {
    const wrapper = mountTab();
    await flushPromises();

    await wrapper.find("#byo-provider").setValue("anthropic");
    await wrapper.find("#byo-key").setValue("sk-ant-test");
    await wrapper.findAll("button").find((button) => button.text() === "Save LLM Configuration")!.trigger("click");
    await flushPromises();

    expect(mocks.apiPost).toHaveBeenCalledWith("/config/byo-chat-config", {
      endpoint_url: "https://api.anthropic.com",
      endpoint_key: "sk-ant-test",
      model: "claude-sonnet-4-6",
      provider: "anthropic",
      allow_private_endpoint: false,
    });
  });

  it("permits keyless Ollama only with explicit loopback consent", async () => {
    const wrapper = mountTab();
    await flushPromises();

    await wrapper.find("#byo-provider").setValue("ollama");
    await wrapper.find("#byo-allow-private-endpoint").setValue(true);
    await wrapper.findAll("button").find((button) => button.text() === "Save LLM Configuration")!.trigger("click");
    await flushPromises();

    expect(mocks.apiPost).toHaveBeenCalledWith("/config/byo-chat-config", {
      endpoint_url: "http://localhost:11434/v1",
      endpoint_key: "",
      model: "llama3",
      provider: "ollama",
      allow_private_endpoint: true,
    });
  });

  it("requires a new key when an OpenAI-compatible endpoint changes vendor", async () => {
    const wrapper = mountTab();
    await flushPromises();

    await wrapper.find("#byo-provider").setValue("openai");
    await flushPromises();

    expect(wrapper.text()).not.toContain("Saved");
    const saveButton = wrapper.findAll("button").find((button) => button.text() === "Save LLM Configuration")!;
    expect(saveButton.attributes("disabled")).toBeDefined();
  });
});

describe("ApiKeysTab hosted Pro HITRAN surface", () => {
  it("keeps HITRAN key management while hiding LLM credential controls", async () => {
    mocks.appMode.value = "enterprise";
    mocks.apiGet.mockResolvedValue({ data: [] });
    const wrapper = mountTab({ hitranOnly: true });
    await flushPromises();

    expect(wrapper.find("#hitran-key").exists()).toBe(true);
    expect(wrapper.find("#llm-key").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("Sherpa Model Configuration");
  });
});


describe("personal HITRAN credentials", () => {
  it.each(["local", "demo", "pro"])("saves, validates and deletes without retrieving the secret: %s", async (profile) => {
    mocks.appMode.value = profile === "local" ? "local" : "enterprise";
    mocks.appConfig.value = { demo: profile === "demo" };
    mocks.apiPost.mockReset();
    mocks.apiPost.mockResolvedValue({ data: { valid: true } });
    mocks.apiDelete.mockReset();
    mocks.apiDelete.mockResolvedValue({});
    let saved = false;
    mocks.apiGet.mockImplementation((url: string) => Promise.resolve({
      data: url === "/api-keys" ? (saved ? [{ service_name: "hitran", last_used_at: null }] : []) : {},
    }));
    const wrapper = mountTab({ hitranOnly: profile !== "local" });
    await flushPromises();
    await wrapper.find("#hitran-key").setValue("personal-test-key");
    saved = true;
    await wrapper.findAll("button").find(b => b.text() === "Save HITRAN Key")!.trigger("click");
    await flushPromises();
    expect(mocks.apiPost).toHaveBeenCalledWith("/api-keys", { service_name: "hitran", key: "personal-test-key" });
    expect((wrapper.find("#hitran-key").element as HTMLInputElement).value).toBe("");
    await wrapper.findAll("button").find(b => b.text() === "Validate Key")!.trigger("click");
    await flushPromises();
    expect(mocks.apiPost).toHaveBeenCalledWith("/api-keys/hitran/validate", { key: null });
    saved = false;
    await wrapper.findAll("button").find(b => b.text() === "Delete HITRAN Key")!.trigger("click");
    await flushPromises();
    expect(mocks.apiDelete).toHaveBeenCalledWith("/api-keys/hitran");
    expect(wrapper.text()).not.toContain("personal-test-key");
    wrapper.unmount();
    vi.unstubAllGlobals();
  });
});

describe("deleting a saved key", () => {
  afterEach(() => { mocks.advisorEnabled = false; });

  beforeEach(() => {
    mocks.appMode.value = "local";
    mocks.appConfig.value = { demo: false };
    mocks.apiDelete.mockReset();
    mocks.confirmAction.mockReset();
    mocks.advisorEnabled = true;
    mocks.apiGet.mockImplementation((url: string) => Promise.resolve({
      data: url === "/api-keys" ? [{ service_name: "openai", last_used_at: null }] : {},
    }));
  });

  it("deletes nothing when the confirmation is declined", async () => {
    mocks.confirmAction.mockResolvedValueOnce(false);
    const wrapper = mountTab();
    await flushPromises();
    await wrapper.find('button[aria-label$="API key"]').trigger("click");
    await flushPromises();
    expect(mocks.confirmAction).toHaveBeenCalledWith(expect.objectContaining({ acceptLabel: "Delete key", destructive: true }));
    expect(mocks.apiDelete).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("never deletes once Settings has gone, even if the dialog is then accepted", async () => {
    const { pendingConfirmation, settleConfirmation } = await import("@/composables/useConfirmAction");
    mocks.realConfirm = true;
    try {
      const wrapper = mountTab();
      await flushPromises();
      await wrapper.find('button[aria-label$="API key"]').trigger("click");
      expect(pendingConfirmation.value?.options.acceptLabel).toBe("Delete key");

      // Browser Back: the page unmounts while its dialog is open.
      wrapper.unmount();
      expect(pendingConfirmation.value).toBeNull();
      settleConfirmation(true);
      await flushPromises();
      expect(mocks.apiDelete).not.toHaveBeenCalled();
    } finally {
      mocks.realConfirm = false;
    }
  });

  it("reports a failed delete beside the saved keys, not in a browser alert", async () => {
    const alert = vi.fn();
    vi.stubGlobal("alert", alert);
    mocks.confirmAction.mockResolvedValueOnce(true);
    mocks.apiDelete.mockRejectedValueOnce(new Error("offline"));
    const wrapper = mountTab();
    await flushPromises();
    await wrapper.find('button[aria-label$="API key"]').trigger("click");
    await flushPromises();
    expect(mocks.apiDelete).toHaveBeenCalledOnce();
    expect(wrapper.find('[role="alert"]').text()).toContain("Could not delete the");
    expect(alert).not.toHaveBeenCalled();
    wrapper.unmount();
    vi.unstubAllGlobals();
  });
});
