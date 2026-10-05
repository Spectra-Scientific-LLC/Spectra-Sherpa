import { afterEach, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { createMemoryHistory, createRouter } from "vue-router";
import { api } from "@/api";
import { useAppConfig } from "@/composables/useAppConfig";
import { bootServerModules, __resetServerModulesForTests } from "@/boot/serverModules";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
afterEach(() => { __resetServerModulesForTests(); vi.restoreAllMocks(); });
it("refreshes cached backend configuration after a product transition", async () => {
  setActivePinia(createPinia());
  const stylesheet = document.createElement("link");
  stylesheet.setAttribute("data-server-styles", "");
  document.head.appendChild(stylesheet);
  const state = (enrolled: boolean) => ({ mode: "local", llms: {},
    features: { sherpaAdvisor: enrolled },
    uiExtensions: [{ id: "product", url: "/ui/product.js", contractVersion: 1, bootstrap: true, required: true }] });
  vi.mocked(api.get).mockResolvedValue({ data: state(false) });
  await useAppConfig().loadConfig(true);
  let reload: () => Promise<unknown> = async () => {};
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/", component: { template: "<div />" } }] });
  await bootServerModules(router, { importModule: async () => ({ contextualActionsVersion: 1, register: ctx => { reload = ctx.reloadConfig; } }) });
  expect(api.get).toHaveBeenCalledTimes(1);
  vi.mocked(api.get).mockResolvedValue({ data: state(true) });
  await reload();
  expect(api.get).toHaveBeenCalledTimes(2);
  expect(useAppConfig().config.value?.features.sherpaAdvisor).toBe(true);
  vi.mocked(api.get).mockResolvedValue({ data: state(false) });
  await reload();
  expect(api.get).toHaveBeenCalledTimes(3);
  expect(useAppConfig().config.value?.features.sherpaAdvisor).toBe(false);
});
