import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, nextTick } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DataStoryCard from "@/views/data/DataStoryCard.vue";
import type { SherpaDatasetDict } from "@/types";

const mocks = vi.hoisted(() => ({
  enabled: true,
  localChat: false,
  mode: { value: "enterprise" },
  store: {
    dataStoryContext: "",
    dataStoryLoading: false,
    dataStoryText: null as string | null,
    generateDataStory: vi.fn(),
    invalidateDataStory: vi.fn(),
  },
}));

vi.mock("@/stores/data", () => ({ useDataStore: () => mocks.store }));
vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appMode: mocks.mode,
    isFeatureEnabled: (feature: string) => feature === "chatAssistant" ? mocks.localChat : mocks.enabled,
  }),
}));
vi.mock("primevue/button", () => ({
  default: defineComponent({
    props: ["label", "disabled"],
    emits: ["click"],
    template: '<button :disabled="disabled" @click="$emit(\'click\')">{{ label }}</button>',
  }),
}));
vi.mock("primevue/inputtext", () => ({
  default: defineComponent({
    props: ["modelValue", "disabled", "placeholder"],
    emits: ["update:modelValue", "keydown"],
    template: '<input :value="modelValue" :disabled="disabled" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" @keydown="$emit(\'keydown\', $event)" />',
  }),
}));

describe("Data Story card", () => {
  it("renders scientific Markdown while keeping generated HTML inert", () => {
    mocks.store.dataStoryText = "**16 scans**\n\n<script>alert('unsafe')</script>";
    const wrapper = mount(DataStoryCard, { props: { sourceKey: "lavender", ready: true } });
    expect(wrapper.find("strong").text()).toBe("16 scans");
    expect(wrapper.find("script").exists()).toBe(false);
    wrapper.unmount();
  });
  beforeEach(() => {
    mocks.enabled = true;
    mocks.localChat = false;
    mocks.mode.value = "enterprise";
    mocks.store.dataStoryContext = "";
    mocks.store.dataStoryLoading = false;
    mocks.store.dataStoryText = null;
    mocks.store.generateDataStory.mockReset();
    mocks.store.invalidateDataStory.mockReset();
  });

  it("generates once for an inspected source and accepts a specific question", async () => {
    const wrapper = mount(DataStoryCard, { props: { sourceKey: "corn-m5", ready: false } });
    expect(mocks.store.generateDataStory).not.toHaveBeenCalled();
    await wrapper.setProps({ ready: true });
    await flushPromises();
    expect(mocks.store.generateDataStory).toHaveBeenCalledTimes(1);
    await wrapper.setProps({ ready: false });
    await wrapper.setProps({ ready: true });
    expect(mocks.store.generateDataStory).toHaveBeenCalledTimes(1);

    await wrapper.find("input").setValue("What do the batches mean?");
    expect(mocks.store.generateDataStory).toHaveBeenCalledTimes(1);
    await wrapper.find("button").trigger("click");
    expect(mocks.store.dataStoryContext).toBe("What do the batches mean?");
    expect(mocks.store.generateDataStory).toHaveBeenCalledTimes(2);
  });

  it("does not send a story request when the deployment has no LLM capability", async () => {
    mocks.enabled = false;
    const wrapper = mount(DataStoryCard, { props: { sourceKey: "corn-m5", ready: true } });
    await nextTick();
    expect(wrapper.text()).toContain("unavailable for this deployment");
    expect(mocks.store.generateDataStory).not.toHaveBeenCalled();
    expect(wrapper.find("button").exists()).toBe(false);
    expect(wrapper.classes()).toContain("data-story-card--unavailable");
  });

  it("uses a configured local BYO chat endpoint without claiming managed entitlement", async () => {
    mocks.enabled = false;
    mocks.localChat = true;
    mocks.mode.value = "local";
    const wrapper = mount(DataStoryCard, { props: { sourceKey: "corn-m5", ready: true } });
    await flushPromises();
    expect(wrapper.text()).not.toContain("unavailable");
    expect(wrapper.text()).not.toContain("Samples · spectral origin · useful metadata");
    expect(mocks.store.generateDataStory).toHaveBeenCalledTimes(1);
    expect(wrapper.find("button").attributes("disabled")).toBeUndefined();
  });

  it("uses the parsed source and invalidates an older story only when source files change", async () => {
    const first = { n_samples: 33 } as SherpaDatasetDict;
    const second = { n_samples: 34 } as SherpaDatasetDict;
    const wrapper = mount(DataStoryCard, { props: {
      sourceKey: "m5-one", ready: true, inspectedSource: first,
    } });
    await flushPromises();
    expect(mocks.store.generateDataStory).toHaveBeenCalledWith(
      first,
      { cacheKey: "m5-one", force: false },
    );
    await wrapper.setProps({ sourceKey: "m5-two", inspectedSource: second });
    await flushPromises();
    expect(mocks.store.invalidateDataStory).toHaveBeenCalledTimes(2);
    expect(mocks.store.generateDataStory).toHaveBeenLastCalledWith(
      second,
      { cacheKey: "m5-two", force: false },
    );
    await wrapper.setProps({ inspectedSource: first });
    await flushPromises();
    expect(mocks.store.generateDataStory).toHaveBeenCalledTimes(2);
    await wrapper.setProps({ sourceKey: "m5-one" });
    await flushPromises();
    expect(mocks.store.generateDataStory).toHaveBeenLastCalledWith(
      first, { cacheKey: "m5-one", force: false },
    );
  });
});
