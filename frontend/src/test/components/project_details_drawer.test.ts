/* eslint-disable vue/one-component-per-file */
import { mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectDetailsDrawer from "@/components/ProjectDetailsDrawer.vue";
import type { ProjectDetail } from "@/types";

const mocks = vi.hoisted(() => ({
  routerPush: vi.fn(),
  toastAdd: vi.fn(),
  projectStore: {
    currentProjectId: 1 as number | null,
    currentProject: null as ProjectDetail | null,
    selectProject: vi.fn(),
  },
  workbookStore: {
    activeSheet: { workflowId: 10 },
    selectWorkflowSheet: vi.fn(),
  },
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({
    push: mocks.routerPush,
  }),
}));

vi.mock("primevue/usetoast", () => ({
  useToast: () => ({
    add: mocks.toastAdd,
  }),
}));

vi.mock("@/stores/project", () => ({
  useProjectStore: () => mocks.projectStore,
}));

vi.mock("@/stores/workbook", () => ({
  useWorkbookStore: () => mocks.workbookStore,
}));

const SidebarStub = defineComponent({
  name: "Sidebar",
  props: {
    visible: { type: Boolean, default: false },
  },
  template: `
    <aside v-if="visible">
      <slot name="header" />
      <slot />
    </aside>
  `,
});

const ButtonStub = defineComponent({
  name: "PrimeButtonStub",
  props: {
    label: { type: String, default: "" },
    icon: { type: String, default: "" },
    title: { type: String, default: "" },
  },
  template: `<button type="button" :title="title"><slot />{{ label }}</button>`,
});

const TagStub = defineComponent({
  name: "Tag",
  props: ["value"],
  template: `<span>{{ value }}</span>`,
});

const BadgeStub = defineComponent({
  name: "Badge",
  props: ["value"],
  template: `<span>{{ value }}</span>`,
});

const makeProject = (): ProjectDetail => ({
  id: 1,
  name: "Demo Project",
  description: "Project with workflows",
  parent_id: null,
  technique: "FTIR",
  sample_type: null,
  experiment_count: 0,
  workflow_count: 2,
  script_count: 0,
  model_count: 0,
  children_count: 0,
  version_count: 0,
  created_at: "2026-05-01T00:00:00Z",
  updated_at: "2026-05-01T00:00:00Z",
  metadata: {},
  experiments: [],
  data_sources: [
    {
      id: 100,
      project_id: 1,
      display_name: "Sklearn: Wine",
      source_type: "example",
      source_ref: "sklearn:wine",
      fingerprint: "sklearn:wine",
      color: "#3b82f6",
      metadata: {},
      sort_order: 0,
      created_at: "2026-05-01T00:00:00Z",
      updated_at: "2026-05-01T00:00:00Z",
    },
  ],
  workflows: [
    {
      id: 10,
      name: "PCA Analysis",
      description: null,
      status: "draft",
      integrity_hash: null,
      primary_data_source_id: 100,
      data_source_ids: [100],
      created_from_template_name: "PCA Exploration",
    },
    { id: 20, name: "PLS Model", description: null, status: "draft", integrity_hash: null },
  ],
  advisor_channels: [],
  scripts: [],
  models: [],
  children: [],
});

const mountDrawer = () =>
  mount(ProjectDetailsDrawer, {
    props: {
      modelValue: true,
    },
    global: {
      stubs: {
        Sidebar: SidebarStub,
        Button: ButtonStub,
        Tag: TagStub,
        Badge: BadgeStub,
      },
    },
  });

describe("ProjectDetailsDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.projectStore.currentProjectId = 1;
    mocks.projectStore.currentProject = makeProject();
    mocks.projectStore.selectProject.mockResolvedValue(undefined);
    mocks.workbookStore.activeSheet = { workflowId: 10 };
    mocks.workbookStore.selectWorkflowSheet.mockResolvedValue(undefined);
    mocks.routerPush.mockResolvedValue(undefined);
  });

  it("opens a listed workflow as the active workbook sheet", async () => {
    const wrapper = mountDrawer();

    await wrapper.findAll(".workflow-item")[1].trigger("click");

    expect(mocks.workbookStore.selectWorkflowSheet).toHaveBeenCalledWith(20, 1);
    expect(mocks.routerPush).toHaveBeenCalledWith("/workflow");
    expect(wrapper.emitted("update:modelValue")).toEqual([[false]]);
  });

  it("renders the current project workflow list", () => {
    const wrapper = mountDrawer();

    expect(wrapper.text()).toContain("Workflows (2)");
    expect(wrapper.text()).toContain("PCA Analysis");
    expect(wrapper.text()).toContain("PLS Model");
  });

  it("renders project data sources and workflow provenance", () => {
    const wrapper = mountDrawer();

    expect(wrapper.text()).toContain("Data Sources (1)");
    expect(wrapper.text()).toContain("Sklearn: Wine");
    expect(wrapper.text()).toContain("SheetsPCA Analysis");
    expect(wrapper.text()).toContain("Data: Sklearn: Wine");
    expect(wrapper.text()).toContain("Created from PCA Exploration");
  });
});
