import { describe, it, expect, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import { createRouter, createMemoryHistory } from "vue-router";
import RunDetailContent from "@/views/models/RunDetailContent.vue";
const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/api/client", () => ({ default: { get } }));
vi.mock("@/stores/advisor", () => ({
  useAdvisorStore: () => ({ switchScope: vi.fn().mockResolvedValue(null) }),
}));
vi.mock("@/stores/project", () => ({
  useProjectStore: () => ({ currentProjectId: 1, ensureProjectForBrowserTab: async () => {} }),
}));
describe("Saved run authority characterization", () => {
  it("GSC-11: Saved parameters displays the explicit graph rather than the effective snapshot", async () => {
    get.mockImplementation(async (url: string) => {
      if (url === "/runs/42")
        return { data: { id: 42, params_snapshot: { pca: { n_components: 2, scale: false } } } };
      if (url.endsWith("/evidence"))
        return {
          data: {
            run: {
              id: 42,
              project_id: 1,
              name: "Synthetic PCA",
              status: "completed",
              run_kind: "training",
            },
            evidence: {
              qualification: "qualified",
              outputs: {
                __workflow__: { definition: { state: "exact", storage: "file" } },
                pca: { scores: { state: "exact", storage: "file" } },
              },
            },
            node_statuses: { pca: "completed" },
          },
        };
      if (url.endsWith("/__workflow__/definition"))
        return {
          data: {
            value: {
              schema_version: 1,
              nodes: [{ node_id: "pca", node_type: "model.pca", label: "PCA", parameters: {} }],
              edges: [],
            },
          },
        };
      if (url.endsWith("/pca/scores"))
        return {
          data: {
            value: [
              [1, 2],
              [3, 4],
            ],
          },
        };
      throw new Error(url);
    });
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/runs/:runId", component: RunDetailContent }],
    });
    await router.push("/runs/42?project=1&view=Validation&node=pca");
    await router.isReady();
    const w = mount(RunDetailContent, {
      global: {
        plugins: [router],
        stubs: {
          Button: true,
          SelectButton: true,
          ProgressSpinner: true,
          Dropdown: true,
          ContextualActions: true,
          QuickPlotModal: true,
        },
      },
    });
    await flushPromises();
    expect(w.text()).toContain("Saved parameters");
    expect(w.text()).not.toContain("n_components");
    expect(get.mock.calls.some((c) => c[0] === "/runs/42")).toBe(false);
    w.unmount();
  });
});
