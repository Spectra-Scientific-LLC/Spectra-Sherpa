import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useProjectStore } from "@/stores/project";
import { useWorkflowStore } from "@/stores/workflow";
import type { ProjectDetail, StarterPlan } from "@/types";
import SimplifiedDashboard from "@/views/dashboard/SimplifiedDashboard.vue";

const mocks = vi.hoisted(() => ({
  routerPush: vi.fn(),
  routerReplace: vi.fn(),
  toastAdd: vi.fn(),
  route: { hash: "" },
  starter: null as null | { emit: (event: string, payload: unknown) => void },
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: mocks.routerPush, replace: mocks.routerReplace }),
  useRoute: () => mocks.route,
}));

vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: mocks.toastAdd }) }));

const appMode = vi.hoisted(() => ({ value: "enterprise" }));
vi.mock("@/composables/useAppConfig", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/composables/useAppConfig")>();
  const { computed } = await import("vue");
  return {
    ...original,
    useAppConfig: () => ({ ...original.useAppConfig(), appMode: computed(() => appMode.value) }),
  };
});

vi.mock("@/views/dashboard/StarterPanel.vue", () => ({
  default: {
    name: "StarterPanel",
    props: ["activeProject", "isLocalMode", "starting"],
    emits: ["start", "overview"],
    mounted() {
      mocks.starter = { emit: (event: string, payload: unknown) => this.$emit(event, payload) };
    },
    template: '<div data-test="starter-panel">{{ activeProject ? activeProject.name : "no goal" }}</div>',
  },
}));

const PLAN: StarterPlan = {
  schema_version: "spectra-starter-plan/1",
  goal: "Explore my lavender oils",
  intent: "explore",
  intent_label: "Explore and compare samples",
  summary: "",
  confidence: 0.8,
  source: "rules",
  template_slug: "pca",
  template_name: "PCA",
  steps: [{ key: "project", title: "Create", detail: "", action_id: null, completion: "has_project" }],
  dataset: null,
  dataset_options: [],
};

const created = (patch: Partial<ProjectDetail> = {}): ProjectDetail => ({
  id: 41,
  name: "Lavender",
  description: null,
  parent_id: null,
  metadata: {},
  technique: null,
  sample_type: null,
  experiment_count: 0,
  workflow_count: 0,
  script_count: 0,
  model_count: 0,
  children_count: 0,
  version_count: 0,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
  experiments: [],
  data_sources: [],
  workflows: [],
  advisor_channels: [],
  scripts: [],
  models: [],
  children: [],
  ...patch,
});

async function mountDashboard() {
  const projectStore = useProjectStore();
  const workflowStore = useWorkflowStore();
  vi.spyOn(projectStore, "ensureProjectForBrowserTab").mockResolvedValue(null);
  vi.spyOn(projectStore, "fetchProjects").mockResolvedValue(undefined);
  vi.spyOn(projectStore, "fetchArchivedProjects").mockResolvedValue([]);
  vi.spyOn(projectStore, "createProject").mockResolvedValue(created());
  vi.spyOn(projectStore, "fetchProject").mockResolvedValue(created());
  vi.spyOn(projectStore, "linkExperiment").mockResolvedValue(undefined);
  vi.spyOn(workflowStore, "fetchTemplates").mockResolvedValue([]);
  vi.spyOn(workflowStore, "fetchCompatibilityMatrix").mockResolvedValue(null);
  workflowStore.templates = [
    {
      id: 7,
      slug: "pca",
      name: "PCA",
      description: "PCA",
      category: "exploratory",
      status: "ready",
      status_detail: null,
      data_modalities: ["spectra"],
      template_data: { nodes: [], edges: [], status: "ready" },
      is_active: true,
      created_at: "2026-09-01T00:00:00Z",
      updated_at: "2026-09-01T00:00:00Z",
    },
  ] as never;
  workflowStore.compatibilityMatrix = {
    schema_version: "spectra-sherpa-reference-template-matrix/1",
    dataset_count: 1,
    template_count: 1,
    pair_count: 1,
    datasets: [
      {
        source: "builtin",
        name: "lavender-essential-oil-v1",
        dataset_id: "builtin:lavender-essential-oil-v1",
        label: "Lavender Essential Oil FTIR Corpus v1",
        technique: "FTIR",
      },
    ],
    matrix: [],
  } as never;
  const wrapper = mount(SimplifiedDashboard, {
    global: {
      plugins: [PrimeVue],
      stubs: { Dialog: true, Dropdown: true, InputText: true, Tag: true, TemplateGallery: true },
    },
  });
  await flushPromises();
  return { wrapper, projectStore };
}

describe("SimplifiedDashboard Starter tab", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    window.sessionStorage.clear();
    mocks.route.hash = "";
    appMode.value = "enterprise";
  });

  it("opens Starter for first-time users unless a hash picks another tab", async () => {
    const { wrapper } = await mountDashboard();
    const tabs = wrapper.findAll('[role="tab"]');
    expect(tabs[0].text()).toBe("Starter");
    expect(tabs[1].attributes("aria-selected")).toBe("true");
    mocks.starter!.emit("overview", { is_first_run: true });
    await flushPromises();
    expect(mocks.routerReplace).toHaveBeenLastCalledWith({ hash: "#starter" });
    expect(tabs[0].attributes("aria-selected")).toBe("true");

    mocks.routerReplace.mockClear();
    mocks.route.hash = "#archive";
    mocks.starter!.emit("overview", { is_first_run: true });
    await flushPromises();
    expect(mocks.routerReplace).not.toHaveBeenCalled();
  });

  it("starts a goal with a reference dataset through the analysis starter", async () => {
    const { projectStore } = await mountDashboard();
    mocks.starter!.emit("start", {
      plan: PLAN,
      name: "Lavender",
      dataset: {
        key: "builtin:lavender-essential-oil-v1",
        label: "Lavender Essential Oil FTIR Corpus v1",
        kind: "reference",
        source: "builtin",
        technique: "FTIR",
        availability: "distributed_reference",
        experiment_id: null,
      },
    });
    await flushPromises();
    expect(projectStore.createProject).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Lavender",
        goal: "Explore my lavender oils",
        goal_plan: PLAN,
        metadata: {
          analysis_starter: expect.objectContaining({
            dataset_id: "builtin:lavender-essential-oil-v1",
            template_slug: "pca",
          }),
        },
      }),
    );
    expect(window.sessionStorage.getItem("sherpa:data-entry-mode")).toBe("analysis-starter");
    expect(mocks.routerPush).toHaveBeenLastCalledWith({ path: "/data", query: { tab: "import" } });
  });

  it("links the user's own dataset and hands it and the planned starter to the Data page", async () => {
    const { projectStore } = await mountDashboard();
    mocks.starter!.emit("start", {
      plan: PLAN,
      name: "Own data",
      dataset: {
        key: "experiment:12",
        label: "Batch",
        kind: "experiment",
        source: "experiment",
        technique: null,
        availability: null,
        experiment_id: 12,
      },
    });
    await flushPromises();
    expect(projectStore.createProject).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Own data", goal_plan: PLAN, metadata: undefined }),
    );
    expect(projectStore.linkExperiment).toHaveBeenCalledWith(41, 12);
    expect(mocks.routerPush).toHaveBeenLastCalledWith({ path: "/data", query: { tab: "my-dataset" } });
    expect(window.sessionStorage.getItem("sherpa:data-entry-mode")).toBe("analysis-starter");
    expect(JSON.parse(window.sessionStorage.getItem("sherpa:data-entry-dataset-intent") || "null")).toEqual({
      schema_version: "spectra-analysis-starter-dataset-intent/1",
      project_id: 41,
      dataset_id: "experiment:12",
      source: "experiment",
      name: "Batch",
      label: "Batch",
      imported_experiment_id: 12,
      template_slug: "pca",
    });
  });

  it("starts a goal without data in local mode on Upload, keeping the planned starter", async () => {
    appMode.value = "local";
    const { projectStore } = await mountDashboard();
    mocks.starter!.emit("start", { plan: PLAN, name: "Files later", dataset: null });
    await flushPromises();
    expect(projectStore.createProject).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Files later", goal: PLAN.goal }),
    );
    expect(mocks.routerPush).toHaveBeenLastCalledWith({ path: "/data", query: { tab: "upload" } });
    expect(JSON.parse(window.sessionStorage.getItem("sherpa:data-entry-dataset-intent") || "null")).toMatchObject({
      project_id: 41,
      source: "upload",
      template_slug: "pca",
      imported_experiment_id: null,
    });
  });

  it("refuses a goal without data outside local mode", async () => {
    const { projectStore } = await mountDashboard();
    mocks.starter!.emit("start", { plan: PLAN, name: "Files later", dataset: null });
    await flushPromises();
    expect(projectStore.createProject).not.toHaveBeenCalled();
    expect(mocks.toastAdd).toHaveBeenCalledWith(expect.objectContaining({ summary: "Choose a Dataset" }));
  });

  it("shows the active project's goal in Starter", async () => {
    const { wrapper, projectStore } = await mountDashboard();
    expect(wrapper.get('[data-test="starter-panel"]').text()).toBe("no goal");
    projectStore.currentProject = created({ name: "With goal", goal: PLAN.goal, goal_plan: PLAN });
    await flushPromises();
    expect(wrapper.get('[data-test="starter-panel"]').text()).toBe("With goal");
  });
});
