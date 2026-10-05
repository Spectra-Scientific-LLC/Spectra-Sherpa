/* eslint-disable vue/one-component-per-file */
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  loadConfig: vi.fn().mockResolvedValue(true),
  isFeatureEnabled: vi.fn().mockReturnValue(true),
  toastAdd: vi.fn(),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  appConfig: {
    __v_isRef: true,
    value: {
      mode: "enterprise",
      subscription: { plan: "demo" },
      features: {
        apiTokenSettings: false,
        chatAssistant: false,
        sherpaAdvisor: false,
        nistDownloads: false,
        sherpaPeakId: false,
        sherpaCodeGen: false,
        sherpaWriteReport: false,
        sherpaAgenticTools: false,
        sherpaDataStory: false,
        sherpaFullContext: false,
      },
    },
  },
}));

vi.mock("primevue/usetoast", () => ({
  useToast: () => ({
    add: mocks.toastAdd,
  }),
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appConfig: mocks.appConfig,
    siteProfile: { __v_isRef: true, value: "enterprise" },
    loadConfig: mocks.loadConfig,
    isFeatureEnabled: mocks.isFeatureEnabled,
  }),
}));

vi.mock("@/api/client", () => ({
  default: {
    get: mocks.apiGet,
    post: mocks.apiPost,
  },
}));

vi.mock("@/composables/useDemoMode", () => ({
  useDemoMode: () => ({
    isDemoMode: { value: false },
  }),
}));

const ButtonStub = defineComponent({
  name: "PrimeButton",
  inheritAttrs: false,
  props: {
    label: { type: String, default: "" },
    disabled: { type: Boolean, default: false },
    loading: { type: Boolean, default: false },
  },
  emits: ["click"],
  template: `
    <button
      v-bind="$attrs"
      :disabled="disabled || loading"
      @click="$emit('click', $event)"
    >
      {{ label }}
      <slot />
    </button>
  `,
});

const InputTextStub = defineComponent({
  name: "InputText",
  inheritAttrs: false,
  props: {
    modelValue: { type: String, default: "" },
  },
  emits: ["update:modelValue"],
  template: `
    <input
      v-bind="$attrs"
      :value="modelValue"
      @input="$emit('update:modelValue', $event.target && $event.target.value ? $event.target.value : '')"
    />
  `,
});

const TagStub = defineComponent({
  name: "Tag",
  props: {
    value: { type: String, default: "" },
  },
  template: '<span class="tag-stub">{{ value }}</span>',
});

const DialogStub = defineComponent({
  name: "PrimeDialog",
  props: {
    visible: { type: Boolean, default: false },
  },
  template: '<div v-if="visible"><slot /><slot name="footer" /></div>',
});

import IntegrationsTab from "@/views/settings/IntegrationsTab.vue";

describe("IntegrationsTab", () => {
  beforeEach(() => {
    mocks.loadConfig.mockResolvedValue(true);
    mocks.isFeatureEnabled.mockReturnValue(true);
    mocks.toastAdd.mockReset();
    mocks.apiPost.mockReset();
    mocks.apiGet.mockReset();
    mocks.appConfig.value = {
      mode: "enterprise",
      subscription: { plan: "demo" },
      features: {
        apiTokenSettings: false,
        chatAssistant: false,
        sherpaAdvisor: false,
        nistDownloads: false,
        sherpaPeakId: false,
        sherpaCodeGen: false,
        sherpaWriteReport: false,
        sherpaAgenticTools: false,
        sherpaDataStory: false,
        sherpaFullContext: false,
      },
    };

    mocks.apiGet.mockImplementation((url: string) => {
      if (url === "/config/spectrasherpa") {
        return Promise.resolve({
          data: {
            serverUrl: "https://demo.example.com",
            apiKey: "ss_demo_1234",
            configured: true,
            source: "environment",
          },
        });
      }
      if (url === "/config/spectrasherpa/user") {
        return Promise.resolve({
          data: {
            label: "Demo Deployment",
            plan: "demo",
            plan_status: "active",
            entitlements: ["chat"],
          },
        });
      }
      if (url === "/config/spectrasherpa/keys") {
        return Promise.resolve({
          data: {
            keys: [{ provider: "openai", display_name: "OpenAI", model: "gpt-5", available: true }],
          },
        });
      }
      if (url === "/egress/defaults") {
        return Promise.resolve({
          data: {
            allow_llm_chat: true,
            allow_llm_context: false,
            allow_nist_queries: true,
            allow_hitran_queries: true,
            allow_export: true,
            allow_spectrasherpa_sync: false,
          },
        });
      }
      throw new Error(`Unhandled GET ${url}`);
    });
  });

  it("exposes privacy controls without loading product enrollment routes", async () => {
    const wrapper = mount(IntegrationsTab);
    await flushPromises();
    expect(wrapper.text()).toContain("NIST WebBook Queries");
    expect(wrapper.text()).toContain("HITRAN/HAPI Queries");
    expect(wrapper.text()).not.toContain("Validate Connection");
    expect(mocks.apiGet.mock.calls.map(([url]) => url)).toEqual(["/egress/defaults"]);
  });

  it("never offers or probes a hosted-service connection in the desktop app", async () => {
    mocks.appConfig.value = { ...mocks.appConfig.value, mode: "local", desktop: true };
    const wrapper = mount(IntegrationsTab, {
      global: {
        stubs: { InputText: InputTextStub, Button: ButtonStub, Tag: TagStub, Dialog: DialogStub },
      },
    });

    await flushPromises();

    expect(wrapper.text()).not.toContain("SpectraSherpa Cloud");
    expect(wrapper.text()).toContain("It does not connect to Spectra Scientific services.");
    expect(mocks.apiGet.mock.calls.map(([url]) => url)).toEqual(["/egress/defaults"]);
  });

  it("can render only Data & Privacy without loading deployment connection state", async () => {
    const wrapper = mount(IntegrationsTab, {
      props: { privacyOnly: true },
      global: {
        stubs: {
          InputText: InputTextStub,
          Button: ButtonStub,
          Tag: TagStub,
          Dialog: DialogStub,
        },
      },
    });

    await flushPromises();

    expect(wrapper.text()).toContain("Data & Privacy");
    expect(wrapper.text()).toContain("NIST WebBook Queries");
    expect(wrapper.text()).toContain("HITRAN/HAPI Queries");
    expect(wrapper.text()).not.toContain("Connect to a SpectraSherpa Cloud server");
    expect(wrapper.text()).not.toContain("Connect & Enable Hybrid");
    expect(wrapper.text()).not.toContain("Validate Connection");
    expect(mocks.apiGet).not.toHaveBeenCalledWith("/config/spectrasherpa");
    expect(mocks.apiGet).toHaveBeenCalledWith("/egress/defaults");
  });
});
