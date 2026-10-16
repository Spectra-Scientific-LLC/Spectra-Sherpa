import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, Fragment, h, nextTick, ref, type Component } from "vue";
import { createMemoryHistory, createRouter, RouterView } from "vue-router";
import PrimeVue from "primevue/config";
import TabPanel from "primevue/tabpanel";
import { afterEach, describe, expect, it, vi } from "vitest";
import Sidebar from "@/components/Sidebar.vue";
import WorkspaceTabs from "@/components/workspace/WorkspaceTabs.vue";
import { createWorkspaceNavigation, provideWorkspaceNavigation } from "@/composables/useWorkspaceNavigation";
import { usePrimaryNavigation } from "@/composables/usePrimaryNavigation";
import RouteIndependentWorkspace from "@/test/fixtures/RouteIndependentWorkspace.vue";

vi.mock("@/stores/auth", () => ({ useAuthStore: () => ({ user: { capabilities: { admin: false } } }) }));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({ appMode: ref("enterprise"), siteProfile: ref("demo") }),
}));
vi.mock("@/composables/useDemoMode", () => ({ useDemoMode: () => ({ isDemoMode: ref(true) }) }));

afterEach(() => usePrimaryNavigation().clear());

async function workspace(pageOverride?: Component) {
  const selected = ref("history");
  const blocked = ref(true);
  const draft = ref("unsaved question");
  const collapsed = ref(false);
  const showGuidance = ref(false);
  const onNavigate = vi.fn();
  let navigation!: ReturnType<typeof createWorkspaceNavigation>;
  const page = pageOverride ?? defineComponent({
    setup: () => () => h(WorkspaceTabs, {
      modelValue: selected.value,
      tabIds: ["history", "blocked", "batch", ...(showGuidance.value ? ["guidance"] : [])],
      labels: { batch: "Batch" },
      "onUpdate:modelValue": (id: string) => { selected.value = id; },
    }, { default: () => [
      h(TabPanel, { header: "History" }, () => h("input", {
        value: draft.value, "aria-label": "Draft",
        onInput: (event: Event) => { draft.value = (event.target as HTMLInputElement).value; },
      })),
      h(Fragment, {}, [
        h(TabPanel, { header: "Unavailable", disabled: blocked.value }, () => "Blocked"),
        h(TabPanel, {}, { header: () => h("strong", "Custom visual header"), default: () => "Batch panel" }),
      ]),
      ...(showGuidance.value ? [h(TabPanel, { header: "Guidance" }, () => "Guidance panel")] : []),
    ] }),
  });
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/runs", component: page },
      { path: "/runs/:runId", component: page },
      { path: "/project", component: { template: "<p>Project</p>" } },
      { path: "/campaigns", component: page },
      { path: "/:pathMatch(.*)*", component: { template: "<p>Other</p>" } },
    ],
  });
  await router.push("/runs");
  await router.isReady();
  const shell = defineComponent({
    setup() {
      navigation = provideWorkspaceNavigation();
      return () => h("div", [
        h(Sidebar, { collapsed: collapsed.value, onNavigate, onExpand: () => { collapsed.value = false; } }),
        h(RouterView),
      ]);
    },
  });
  const view = mount(shell, { global: { plugins: [router, PrimeVue] } });
  await flushPromises();
  return { view, router, selected, blocked, draft, collapsed, navigation, showGuidance, onNavigate };
}

describe("active workspace sidebar sections", () => {
  it("republishes a reused compiled Vue page even when its stable tabs do not read the route", async () => {
    const { view, router, navigation } = await workspace(RouteIndependentWorkspace);
    await router.push("/runs/A");
    await flushPromises();
    const instance = view.getComponent(RouteIndependentWorkspace).vm.$.uid;
    await view.get('input[aria-label="Retained draft"]').setValue("Keep my edits");
    await router.push("/runs/B");
    await flushPromises();
    expect(view.getComponent(RouteIndependentWorkspace).vm.$.uid).toBe(instance);
    expect(navigation.entry.value?.path).toBe("/runs/B");
    expect(view.findAll(".nav-child").map(button => button.text())).toEqual(["History", "Batch"]);
    await view.findAll(".nav-child")[1].trigger("click");
    expect(view.get('[role="region"]:not([style*="display: none"])').text()).toBe("Batch panel");
    await view.findAll(".nav-child")[0].trigger("click");
    expect((view.get('input[aria-label="Retained draft"]').element as HTMLInputElement).value).toBe("Keep my edits");
    view.unmount();
  });

  it("signals drawer dismissal only for an enabled navigation choice", async () => {
    const { view, onNavigate } = await workspace();
    await view.get(".sidebar-header").trigger("click");
    // Dispatch directly as well as through the test utility to exercise the
    // guard even if a disabled native control's click bubbles in a browser.
    view.findAll(".nav-child")[1].element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(onNavigate).not.toHaveBeenCalled();
    await view.findAll(".nav-child")[2].trigger("click");
    expect(onNavigate).toHaveBeenCalledTimes(1);
    await view.get('a[aria-label="Project"]').trigger("click");
    expect(onNavigate).toHaveBeenCalledTimes(2);
    view.unmount();
  });

  it("updates conditional sections without shifting existing destinations", async () => {
    const { view, showGuidance, selected } = await workspace();
    showGuidance.value = true;
    await flushPromises();
    expect(view.findAll(".nav-child").map(button => button.text())).toEqual(["History", "Unavailable", "Batch", "Guidance"]);
    await view.findAll(".nav-child")[3].trigger("click");
    expect(selected.value).toBe("guidance");
    selected.value = "batch";
    showGuidance.value = false;
    await flushPromises();
    expect(view.findAll(".nav-child")).toHaveLength(3);
    expect(view.get('.nav-child[aria-current="true"]').text()).toBe("Batch");
    view.unmount();
  });

  it("projects real labels and disabled states and reuses the page's selection handler", async () => {
    const { view, selected, navigation, blocked, draft } = await workspace();
    expect(view.findAll(".nav-children")).toHaveLength(1);
    expect(view.get(".nav-children").attributes("aria-label")).toBe("Runs sections");
    expect(view.findAll(".nav-child").map(button => button.text())).toEqual(["History", "Unavailable", "Batch"]);
    expect(view.get(".workspace-tabs").classes()).toContain("workspace-tabs--sidebar");
    expect(view.findAll(".nav-child")[1].attributes("disabled")).toBeDefined();
    navigation.entry.value!.select("blocked");
    expect(selected.value).toBe("history");
    await view.get('input[aria-label="Draft"]').setValue("Keep my edits");
    await view.findAll(".nav-child")[2].trigger("click");
    await nextTick();
    expect(selected.value).toBe("batch");
    expect(view.findAll(".nav-child")[2].attributes("aria-current")).toBe("true");
    expect(view.get('[role="region"]:not([style*="display: none"])').text()).toBe("Batch panel");
    expect(view.get('[role="region"]:not([style*="display: none"])').attributes("aria-label")).toBe("Batch");
    expect(view.get('[role="region"]:not([style*="display: none"])').attributes("id")).toBe(view.findAll(".nav-child")[2].attributes("aria-controls"));
    expect(view.find('[role="tablist"]').exists()).toBe(false);
    expect(view.get(".p-tabview-nav-container").attributes("hidden")).toBeDefined();
    await view.findAll(".nav-child")[0].trigger("click");
    expect(draft.value).toBe("Keep my edits");
    blocked.value = false;
    await nextTick();
    await nextTick();
    expect(view.findAll(".nav-child")[1].attributes("disabled")).toBeUndefined();
    view.unmount();
    expect(navigation.entry.value).toBeNull();
  });

  it("tracks programmatic page selection and exposes sections from collapsed navigation", async () => {
    const { view, selected, collapsed } = await workspace();
    selected.value = "batch";
    await nextTick();
    await nextTick();
    expect(view.get('.nav-child[aria-current="true"]').text()).toBe("Batch");
    collapsed.value = true;
    await nextTick();
    expect(view.find(".nav-children").exists()).toBe(false);
    await view.get('[aria-label="Expand Runs sections"]').trigger("click");
    expect(collapsed.value).toBe(false);
    expect(view.find(".nav-children").exists()).toBe(true);
    view.unmount();
  });

  it("removes stale sections and supports contributor-owned Optimize and run-detail routes", async () => {
    const { view, router, navigation } = await workspace();
    await router.push("/runs/42");
    await flushPromises();
    expect(view.get(".nav-children").attributes("aria-label")).toBe("Runs sections");
    await router.push("/project");
    await flushPromises();
    expect(view.find(".nav-children").exists()).toBe(false);
    expect(navigation.entry.value).toBeNull();
    usePrimaryNavigation().addItems([{ to: "/campaigns", label: "Optimize", icon: "pi pi-chart-line" }], "campaign");
    await router.push("/campaigns");
    await flushPromises();
    expect(view.findAll(".nav-children")).toHaveLength(1);
    expect(view.get(".nav-children").attributes("aria-label")).toBe("Optimize sections");
    usePrimaryNavigation().removeItems("campaign");
    await nextTick();
    expect(view.find(".nav-children").exists()).toBe(false);
    view.unmount();
  });

  it("does not allow old-page teardown to erase the current page's registration", () => {
    const navigation = createWorkspaceNavigation();
    const old = Symbol(), current = Symbol();
    const entry = { path: "/runs", selected: "batch", items: [], select: vi.fn() };
    navigation.publish(old, entry);
    navigation.publish(current, { ...entry, path: "/campaigns" });
    navigation.release(old);
    expect(navigation.entry.value?.path).toBe("/campaigns");
    navigation.release(current);
    expect(navigation.entry.value).toBeNull();
  });
});
