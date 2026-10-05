import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRunsStore } from "@/stores/runs";
import { useProjectStore } from "@/stores/project";
import { useWorkflowStore } from "@/stores/workflow";
import type { ProjectDetail } from "@/types";
import SimplifiedDashboard from "@/views/dashboard/SimplifiedDashboard.vue";

const mocks = vi.hoisted(() => ({
  routerPush: vi.fn(),
  routerReplace: vi.fn(),
  toastAdd: vi.fn(),
  route: { hash: "#storage" },
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: mocks.routerPush, replace: mocks.routerReplace }),
  useRoute: () => mocks.route,
}));

vi.mock("primevue/usetoast", () => ({
  useToast: () => ({ add: mocks.toastAdd }),
}));

vi.mock("@/views/workflow-builder/TemplateGallery.vue", () => ({
  default: {
    name: "TemplateGallery",
    props: {
      selectedTemplateId: { type: Number, default: null },
      selectedDatasetId: { type: String, default: null },
      requireDatasetSelection: { type: Boolean, default: false },
      showHeader: { type: Boolean, default: true },
    },
    emits: ["select"],
    methods: {
      selectTemplate() {
        this.$emit("select", {
          id: 7,
          slug: "pca",
          name: "PCA",
          description: "Principal component analysis",
          category: "exploratory",
          status: "ready",
          status_detail: null,
          data_modalities: ["spectra"],
          template_data: { nodes: [], edges: [], status: "ready" },
          is_active: true,
          created_at: "2026-09-01T00:00:00Z",
          updated_at: "2026-09-01T00:00:00Z",
        });
      },
    },
    template:
      '<button data-test="template-start" :disabled="requireDatasetSelection && !selectedDatasetId" @click="selectTemplate">Start Template</button>',
  },
}));

const createdProject = (): ProjectDetail => ({
  id: 99,
  name: "Lavender Essential Oil FTIR Corpus v1 PCA",
  description: null,
  parent_id: null,
  metadata: {},
  technique: "FTIR",
  sample_type: null,
  experiment_count: 0,
  workflow_count: 0,
  script_count: 0,
  model_count: 0,
  children_count: 0,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
  experiments: [],
  data_sources: [],
  workflows: [],
  advisor_channels: [],
  scripts: [],
  models: [],
  children: [],
});

describe("SimplifiedDashboard analysis starters", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    window.sessionStorage.clear();
  });

  it.each(["", "#archive", "#storage"])(
    "keeps project and storage actions available from Dashboard (%s)",
    async (hash) => {
      mocks.route.hash = hash;
      const projectStore = useProjectStore();
      const workflowStore = useWorkflowStore();
      vi.spyOn(projectStore, "ensureProjectForBrowserTab").mockResolvedValue(null);
      vi.spyOn(projectStore, "fetchProjects").mockResolvedValue(undefined);
      vi.spyOn(projectStore, "fetchArchivedProjects").mockResolvedValue([]);
      vi.spyOn(projectStore, "createProject").mockResolvedValue(createdProject());
      vi.spyOn(projectStore, "fetchProject").mockResolvedValue(createdProject());
      vi.spyOn(workflowStore, "fetchTemplates").mockResolvedValue([]);
      vi.spyOn(workflowStore, "fetchCompatibilityMatrix").mockResolvedValue(null);
      vi.spyOn(workflowStore, "instantiateTemplate").mockResolvedValue({
        workflowId: 123,
        projectId: 99,
        slug: "pca",
      });
      workflowStore.compatibilityMatrix = {
        schema_version: "spectra-sherpa-reference-template-matrix/1",
        dataset_count: 4,
        template_count: 1,
        pair_count: 4,
        datasets: [
          {
            source: "builtin",
            name: "lavender-essential-oil-v1",
            dataset_id: "builtin:lavender-essential-oil-v1",
            label: "Lavender Essential Oil FTIR Corpus v1",
            technique: "FTIR",
          },
          {
            source: "synthetic",
            name: "Synthetic_atmospheric-6",
            dataset_id: "synthetic:Synthetic_atmospheric-6",
            label: "Synthetic atmospheric mixture",
          },
          {
            source: "sklearn",
            name: "iris",
            dataset_id: "sklearn:iris",
            label: "Iris",
          },
          {
            source: "registered",
            name: "public-corn-m5-moisture-v1",
            dataset_id: "registered:public-corn-m5-moisture-v1",
            label: "Eigenvector Corn M5",
          },
        ],
        matrix: [],
      };

      const scroll = vi.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(() => {});
      const reclaim = vi.spyOn(useRunsStore(), "reclaimStorage").mockResolvedValue({
        removed_files: 1,
        used_bytes: 10,
        quota_bytes: 100,
        grace_seconds: 86400,
      });
      const wrapper = mount(SimplifiedDashboard, {
        global: {
          plugins: [PrimeVue],
          stubs: {
            Button: {
              props: ["label", "disabled", "loading"],
              emits: ["click"],
              template:
                '<button :disabled="disabled" @click="$emit(\'click\', $event)">{{ label }}</button>',
            },
            Dialog: {
              props: ["visible"],
              template: '<div v-if="visible"><slot /></div>',
            },
            Dropdown: {
              props: ["modelValue", "options", "optionLabel", "optionValue", "placeholder"],
              emits: ["update:modelValue"],
              methods: {
                updateValue(event: Event) {
                  this.$emit("update:modelValue", (event.target as HTMLSelectElement).value);
                },
              },
              template:
                '<select data-test="dataset-dropdown" :value="modelValue || \'\'" @change="updateValue"><option value="">{{ placeholder }}</option><option v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</option></select>',
            },
            InputText: true,
            Tag: true,
          },
        },
      });
      await flushPromises();
      const tabs = wrapper.findAll('[role="tab"]');
      expect(tabs.map((tab) => tab.text())).toEqual(["Your Project", "Archive", "Storage"]);
      expect(wrapper.findAll('.workspace-header .responsive-header-actions__full button').map(button => button.text())).toEqual(["New Analysis", "Import Project", "Project"]);
      const archiveChooser = wrapper.get('input[accept=".sherpa,.spectrapy,.zip"]');
      const openArchiveChooser = vi.spyOn(archiveChooser.element as HTMLInputElement, "click").mockImplementation(() => {});
      await wrapper.findAll('.workspace-header .responsive-header-actions__full button')[1].trigger("click");
      expect(openArchiveChooser).toHaveBeenCalledOnce();
      expect(wrapper.find('.current-strip__meta button').exists()).toBe(false);
      if (hash === "#storage") {
        expect(scroll).toHaveBeenCalledWith({ block: "start" });
        expect(scroll.mock.instances).toContain(wrapper.get("#storage").element);
        expect(tabs[2].attributes("aria-selected")).toBe("true");
      } else if (hash === "#archive") {
        expect(tabs[1].attributes("aria-selected")).toBe("true");
      } else {
        expect(tabs[0].attributes("aria-selected")).toBe("true");
        expect(wrapper.findAll('[role="tabpanel"]')[1].attributes("style")).toContain("display: none");
        await tabs[2].trigger("click");
        await flushPromises();
        expect(mocks.routerReplace).toHaveBeenCalledWith({ hash: "#storage" });
      }
      expect(reclaim).not.toHaveBeenCalled();
      expect(wrapper.get("#storage").text()).toContain("across your projects");
      await wrapper.get("#storage button").trigger("click");
      await flushPromises();
      expect(reclaim).toHaveBeenCalledExactlyOnceWith();

      await wrapper
        .findAll("button")
        .find((button) => button.text() === "New Analysis")!
        .trigger("click");
      expect(wrapper.text()).toContain("Synthetic atmospheric mixture · Spectra synthetic");
      expect(wrapper.text()).toContain("Iris · scikit-learn");
      expect(wrapper.text()).toContain("Eigenvector Corn M5 · user-acquired");
      await wrapper
        .get('[data-test="dataset-dropdown"]')
        .setValue("builtin:lavender-essential-oil-v1");
      await wrapper.get('[data-test="template-start"]').trigger("click");
      await flushPromises();

      expect(projectStore.createProject).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Lavender Essential Oil FTIR Corpus v1 PCA",
          metadata: {
            analysis_starter: expect.objectContaining({
              dataset_id: "builtin:lavender-essential-oil-v1",
              source: "builtin",
              name: "lavender-essential-oil-v1",
              template_slug: "pca",
            }),
          },
        }),
      );
      expect(workflowStore.instantiateTemplate).not.toHaveBeenCalled();
      expect(window.sessionStorage.getItem("sherpa:data-entry-mode")).toBe("analysis-starter");
      expect(mocks.routerPush).toHaveBeenCalledWith({ path: "/data", query: { tab: "import" } });

      await tabs[0].trigger("click");
      expect(mocks.routerReplace).toHaveBeenLastCalledWith({ hash: "" });
      projectStore.projects = [{ ...createdProject(), version_count: 0 }];
      await flushPromises();
      await wrapper.get('[aria-label="Archive project"]').trigger("click");
      expect(wrapper.text()).toContain("You can restore it from Archive");

      projectStore.archivedProjects = [{ ...createdProject(), version_count: 0 }];
      await flushPromises();
      await tabs[1].trigger("click");
      expect(mocks.routerReplace).toHaveBeenLastCalledWith({ hash: "#archive" });
      await wrapper
        .findAll("button")
        .find((button) => button.text() === "Permanently delete")!
        .trigger("click");
      expect(wrapper.text()).toContain("internal read-only provenance record");
    },
  );
});
