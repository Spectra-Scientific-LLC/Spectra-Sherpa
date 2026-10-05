import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent } from "vue";

const mocks = vi.hoisted(() => ({
  appMode: { __v_isRef: true, value: "enterprise" as string },
  routerPush: vi.fn(),
  projectStore: {
    currentProjectId: null as number | null,
    ensureProjectForBrowserTab: vi.fn(async () => null as { id: number; name: string } | null),
  },
  adapter: {
    getMemoryMap: vi.fn(async () => ({
      project_id: 42,
      nodes: [],
      edges: [],
    })),
  },
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({
    push: mocks.routerPush,
  }),
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appMode: mocks.appMode,
  }),
}));

vi.mock("@/stores/project", async () => {
  const { reactive } = await import("vue");
  mocks.projectStore = reactive(mocks.projectStore);
  return { useProjectStore: () => mocks.projectStore };
});

vi.mock("@/lib/advisorMemoryAdapter", () => ({
  getAdvisorMemoryAdapter: () => mocks.adapter,
}));

import MemoryMapView from "@/views/project/MemoryMapView.vue";

const ButtonStub = defineComponent({
  name: "ButtonStub",
  inheritAttrs: false,
  props: {
    label: { type: String, default: "" },
    loading: { type: Boolean, default: false },
  },
  emits: ["click"],
  template: `<button v-bind="$attrs" @click="$emit('click')"><slot>{{ label }}</slot></button>`,
});

const ProgressSpinnerStub = defineComponent({
  name: "ProgressSpinner",
  template: `<span data-test="spinner"></span>`,
});

function mountView() {
  return mount(MemoryMapView, {
    global: {
      stubs: {
        Button: ButtonStub,
        ProgressSpinner: ProgressSpinnerStub,
      },
      directives: {
        tooltip: () => undefined,
      },
    },
  });
}

describe("MemoryMapView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.appMode.value = "enterprise";
    mocks.projectStore.currentProjectId = null;
    mocks.projectStore.ensureProjectForBrowserTab.mockImplementation(async () => {
      mocks.projectStore.currentProjectId = 42;
      return { id: 42, name: "Recovered project" };
    });
    mocks.adapter.getMemoryMap.mockResolvedValue({
      project_id: 42,
      nodes: [],
      edges: [],
    });
  });

  it("rehydrates the active project before loading the memory map", async () => {
    mountView();
    await flushPromises();

    expect(mocks.projectStore.ensureProjectForBrowserTab).toHaveBeenCalled();
    expect(mocks.adapter.getMemoryMap).toHaveBeenCalledWith(42);
  });

  it("shows a non-error unavailable state in local mode", async () => {
    mocks.appMode.value = "local";
    mocks.projectStore.currentProjectId = 42;
    mocks.projectStore.ensureProjectForBrowserTab.mockResolvedValue({ id: 42, name: "Local project" });
    mocks.adapter.getMemoryMap.mockResolvedValue(null);

    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.find(".error-banner").exists()).toBe(false);
    expect(wrapper.text()).toContain("Memory Map unavailable");
  });

  it("renders the empty graph state for a project with no memory", async () => {
    mocks.projectStore.currentProjectId = 42;

    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.text()).toContain("No memory yet");
  });

  it("renders populated memory nodes and incoming edges", async () => {
    mocks.projectStore.currentProjectId = 42;
    mocks.adapter.getMemoryMap.mockResolvedValue({
      project_id: 42,
      nodes: [
        {
          id: 1,
          tab_key: "data",
          subscope_key: "explore",
          node_type: "subtab",
          title: "Explore",
          badges: {
            topic_count: 1,
            fact_count: 2,
            last_compaction_at: null,
            stale_descendant_count: 0,
          },
        },
        {
          id: 2,
          tab_key: "workflow",
          subscope_key: "sheet:9",
          node_type: "sheet",
          title: "PLS-DA",
          badges: {
            topic_count: 3,
            fact_count: 4,
            last_compaction_at: "2026-05-08T12:00:00Z",
            stale_descendant_count: 1,
          },
        },
      ],
      edges: [
        {
          id: 10,
          source_node_id: 1,
          target_node_id: 2,
          edge_type: "relevant_to",
          weight: 1.5,
        },
      ],
    });

    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.text()).toContain("Data");
    expect(wrapper.text()).toContain("Explore");
    expect(wrapper.text()).toContain("Workflow");
    expect(wrapper.text()).toContain("PLS-DA");
    expect(wrapper.text()).toContain("Influenced by:");
    expect(wrapper.text()).toContain("w1.5");
  });

  it("renders request failures as an error banner", async () => {
    mocks.projectStore.currentProjectId = 42;
    mocks.adapter.getMemoryMap.mockRejectedValue(new Error("network down"));

    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.find(".error-banner").exists()).toBe(true);
    expect(wrapper.text()).toContain("network down");
  });

  it("navigates back to the project page", async () => {
    const wrapper = mountView();
    await flushPromises();

    await wrapper.find("button").trigger("click");

    expect(mocks.routerPush).toHaveBeenCalledWith("/project");
  });
  it("keeps current Runs, Optimize and legacy scopes visible without routine Refresh", async () => {
    mocks.adapter.getMemoryMap.mockResolvedValue({ project_id: 42, nodes: ["models", "optimization", "legacy-scope"].map((tab, i) => ({
      id: i + 1, tab_key: tab, subscope_key: "overview", node_type: "subtab", title: tab,
      badges: { topic_count: 1, fact_count: 0, last_compaction_at: null, stale_descendant_count: 0 },
    })), edges: [] });
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.findAll(".node-card")).toHaveLength(3);
    expect(wrapper.text()).toContain("Optimize");
    expect(wrapper.text()).toContain("Runs");
    expect(wrapper.findAll("button").some(b => b.text() === "Refresh")).toBe(false);
  });

  it("discards an old project's delayed response", async () => {
    let finish!: (value: any) => void;
    mocks.adapter.getMemoryMap.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = mountView();
    await flushPromises();
    mocks.projectStore.currentProjectId = 77;
    mocks.adapter.getMemoryMap.mockResolvedValue({ project_id: 77, nodes: [], edges: [] });
    await flushPromises();
    finish({ project_id: 42, nodes: [{ id: 1, tab_key: "project", subscope_key: "overview", title: "Old private scope", badges: { topic_count: 1, fact_count: 1, stale_descendant_count: 0 } }], edges: [] });
    await flushPromises();
    expect(wrapper.text()).not.toContain("Old private scope");
    expect(wrapper.text()).toContain("No memory yet");
    wrapper.unmount();
  });

});
