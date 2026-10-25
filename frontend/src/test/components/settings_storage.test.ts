import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { createMemoryHistory, createRouter } from "vue-router";
import { describe, expect, it, vi } from "vitest";
import SettingsContent from "@/views/settings/SettingsContent.vue";
import { useRunsStore } from "@/stores/runs";

const config = vi.hoisted(() => ({
  mode: { value: "local" },
  profile: { value: "local" },
  demo: { value: false },
}));
vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appMode: config.mode,
    siteProfile: config.profile,
    isFeatureEnabled: () => false,
  }),
}));
vi.mock("@/composables/useDemoMode", () => ({ useDemoMode: () => ({ isDemoMode: config.demo }) }));

describe("Settings Storage", () => {
  it.each(["local", "demo", "pro"])("owns Storage and its deep link in %s", async (profile) => {
    config.mode.value = profile === "local" ? "local" : "enterprise";
    config.profile.value = profile;
    config.demo.value = profile === "demo";
    const pinia = createPinia();
    setActivePinia(pinia);
    const reclaim = vi.spyOn(useRunsStore(), "reclaimStorage").mockResolvedValue({
      removed_files: 1,
      used_bytes: 10,
      quota_bytes: 100,
      grace_seconds: 86400,
    });
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/settings", component: SettingsContent }],
    });
    await router.push("/settings?tab=storage");
    await router.isReady();
    const wrapper = mount(SettingsContent, {
      global: {
        plugins: [pinia, PrimeVue, router],
        stubs: {
          ApiKeysTab: true,
          IntegrationsTab: true,
          PlateFormatSettingsSection: true,
          DisplayPreferencesSection: true,
          GuidanceSettingsSection: true,
        },
      },
    });
    await flushPromises();
    const tabs = wrapper.findAll('[role="tab"]');
    expect(tabs.map((t) => t.text())).toContain("Storage");
    expect(tabs.find((t) => t.text() === "Storage")?.attributes("aria-selected")).toBe("true");
    expect(wrapper.text()).toContain("Reclaim unused outputs across your projects");
    expect(reclaim).not.toHaveBeenCalled();
    await wrapper
      .findAll("button")
      .find((b) => b.text() === "Reclaim Storage")!
      .trigger("click");
    await flushPromises();
    expect(reclaim).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain("Removed 1 unreferenced files");
    await tabs[0].trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.query.tab).toBe(
      profile === "local" ? "api-keys" : "preferences",
    );
    wrapper.unmount();
  });
});
