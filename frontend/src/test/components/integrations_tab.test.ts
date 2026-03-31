/* eslint-disable vue/one-component-per-file */
import { flushPromises, mount } from '@vue/test-utils';
import { defineComponent } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  loadConfig: vi.fn().mockResolvedValue(true),
  isFeatureEnabled: vi.fn().mockReturnValue(true),
  toastAdd: vi.fn(),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  appConfig: {
    __v_isRef: true,
    value: {
      mode: 'enterprise',
      subscription: { plan: 'demo' },
      features: {
        apiTokenSettings: false,
        cloudOffload: false,
        chatAssistant: false,
        sherpaAdvisor: false,
        pluginSystem: true,
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

vi.mock('primevue/usetoast', () => ({
  useToast: () => ({
    add: mocks.toastAdd,
  }),
}));

vi.mock('@/composables/useAppConfig', () => ({
  useAppConfig: () => ({
    appConfig: mocks.appConfig,
    loadConfig: mocks.loadConfig,
    isFeatureEnabled: mocks.isFeatureEnabled,
  }),
}));

vi.mock('@/api/client', () => ({
  default: {
    get: mocks.apiGet,
    post: mocks.apiPost,
  },
}));

const ButtonStub = defineComponent({
  name: 'PrimeButton',
  inheritAttrs: false,
  props: {
    label: { type: String, default: '' },
    disabled: { type: Boolean, default: false },
    loading: { type: Boolean, default: false },
  },
  emits: ['click'],
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
  name: 'InputText',
  inheritAttrs: false,
  props: {
    modelValue: { type: String, default: '' },
  },
  emits: ['update:modelValue'],
  template: `
    <input
      v-bind="$attrs"
      :value="modelValue"
      @input="$emit('update:modelValue', $event.target && $event.target.value ? $event.target.value : '')"
    />
  `,
});

const TagStub = defineComponent({
  name: 'Tag',
  props: {
    value: { type: String, default: '' },
  },
  template: '<span class="tag-stub">{{ value }}</span>',
});

const DialogStub = defineComponent({
  name: 'PrimeDialog',
  props: {
    visible: { type: Boolean, default: false },
  },
  template: '<div v-if="visible"><slot /><slot name="footer" /></div>',
});

import IntegrationsTab from '@/views/settings/IntegrationsTab.vue';

describe('IntegrationsTab', () => {
  beforeEach(() => {
    mocks.loadConfig.mockResolvedValue(true);
    mocks.isFeatureEnabled.mockReturnValue(true);
    mocks.toastAdd.mockReset();
    mocks.apiPost.mockReset();
    mocks.apiGet.mockReset();
    mocks.appConfig.value = {
      mode: 'enterprise',
      subscription: { plan: 'demo' },
      features: {
        apiTokenSettings: false,
        cloudOffload: false,
        chatAssistant: false,
        sherpaAdvisor: false,
        pluginSystem: true,
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
      if (url === '/config/spectrasherpa') {
        return Promise.resolve({
          data: {
            serverUrl: 'https://demo.example.com',
            apiKey: 'ss_demo_1234',
            configured: true,
            source: 'environment',
          },
        });
      }
      if (url === '/config/spectrasherpa/user') {
        return Promise.resolve({
          data: {
            label: 'Demo Deployment',
            plan: 'demo',
            plan_status: 'active',
            entitlements: ['chat'],
          },
        });
      }
      if (url === '/config/spectrasherpa/keys') {
        return Promise.resolve({
          data: {
            keys: [{ provider: 'openai', display_name: 'OpenAI', model: 'gpt-5', available: true }],
          },
        });
      }
      throw new Error(`Unhandled GET ${url}`);
    });
  });

  it('shows Validate Connection for configured enterprise deployments and validates on click', async () => {
    const wrapper = mount(IntegrationsTab, {
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

    expect(wrapper.text()).toContain('Validate Connection');
    expect(wrapper.text()).toContain('Refresh');
    expect(wrapper.text()).not.toContain('Test Connection');

    const validateButton = wrapper.findAll('button').find((button) => button.text().includes('Validate Connection'));
    expect(validateButton).toBeDefined();

    await validateButton!.trigger('click');
    await flushPromises();

    const userCalls = mocks.apiGet.mock.calls.filter(([url]) => url === '/config/spectrasherpa/user');
    const keyCalls = mocks.apiGet.mock.calls.filter(([url]) => url === '/config/spectrasherpa/keys');

    expect(userCalls).toHaveLength(2);
    expect(keyCalls).toHaveLength(2);
    expect(wrapper.text()).toContain('Connection successful!');
    expect(wrapper.text()).toContain('Deployment: Demo Deployment');
    expect(wrapper.text()).toContain('Plan: demo');
    expect(wrapper.text()).toContain('1 managed LLM provider(s) available');
  });
});
