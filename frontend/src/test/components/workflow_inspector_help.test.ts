import { flushPromises, shallowMount } from "@vue/test-utils";
import { defineComponent, reactive } from "vue";
import { describe, expect, it, vi } from "vitest";

import WorkflowInspector from "@/views/workflow-builder/WorkflowInspector.vue";

const nodeMetadata = reactive({
  label: "Principal Component Analysis",
  parameters: [],
  execution_contract: {
    digest: "a".repeat(64),
    payload: { help_reference: "docs/nodes/exploratory.md" },
  },
});

const workflowStore = reactive({
  nodes: [],
  edges: [],
  workflowId: 1 as number | null,
  getNodeMetadata: vi.fn(() => nodeMetadata),
  validateNodeParams: vi.fn(() => []),
  fetchReferenceDatasets: vi.fn(),
  executeTrial: vi.fn(),
  saveWorkflow: vi.fn(async () => 77),
});

const routerPush = vi.fn();

vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: vi.fn() }) }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: routerPush }) }));
vi.mock("@/stores/workflow", () => ({ useWorkflowStore: () => workflowStore }));
vi.mock("@/stores/project", () => ({
  useProjectStore: () => ({ currentProjectId: 1 }),
}));

const selectedNode = {
  id: "pca_1",
  type: "model.pca",
  label: "PCA",
  x: 0,
  y: 0,
  params: {},
};

describe("WorkflowInspector node help", () => {
  const mountInspector = () =>
    shallowMount(WorkflowInspector, {
      props: { selectedNode: null, nodeOutput: null, isOpen: true },
      global: {
        directives: { tooltip: () => undefined },
        stubs: {
          QuickPlotModal: defineComponent({ template: "<div />" }),
          DataTableModal: defineComponent({ template: "<div />" }),
        },
      },
    });

  it("renders the selected node contract as a keyboard-native secure new-tab link", async () => {
    const wrapper = mountInspector();
    await wrapper.setProps({ selectedNode });

    const link = wrapper.get('[data-testid="inspector-node-help"]');
    expect(link.element.tagName).toBe("A");
    expect(link.attributes("href")).toBe("https://docs.spectrascientific.ai/nodes/exploratory/");
    expect(link.attributes("target")).toBe("_blank");
    expect(link.attributes("rel")).toBe("noopener noreferrer");
    expect(link.text()).toBe("?");
    expect(link.attributes("title")).toContain("Learn about this node");
    expect(link.attributes("aria-label")).toContain("opens in a new tab");
  });

  it("fails closed when the selected node contract has no safe help authority", async () => {
    nodeMetadata.execution_contract.payload.help_reference = "../../private.md";
    const wrapper = mountInspector();
    await wrapper.setProps({ selectedNode });

    expect(wrapper.find('[data-testid="inspector-node-help"]').exists()).toBe(false);
    nodeMetadata.execution_contract.payload.help_reference = "docs/nodes/exploratory.md";
  });

  it("persists a blank sheet before configuring its first collection selection", async () => {
    workflowStore.workflowId = null;
    workflowStore.saveWorkflow.mockClear();
    routerPush.mockClear();
    const wrapper = mountInspector();
    await wrapper.setProps({
      selectedNode: {
        ...selectedNode,
        id: "collection_load_1",
        type: "data.collection_load",
        label: "Collection Load",
      },
    });

    await wrapper.get('[data-testid="configure-sheet-data"]').trigger("click");
    await flushPromises();

    expect(workflowStore.saveWorkflow).toHaveBeenCalledWith({
      createVersion: false,
      projectId: 1,
    });
    expect(routerPush).toHaveBeenCalledWith({
      path: "/data",
      query: {
        tab: "my-dataset",
        workflow: "77",
        source_node: "collection_load_1",
        project_id: "1",
      },
    });
    workflowStore.workflowId = 1;
  });

  it("hides generic axis selectors when an output node receives a declared visualization", async () => {
    const wrapper = mountInspector();
    await wrapper.setProps({
      selectedNode: { ...selectedNode, type: "output.plot", label: "PCA Scores" },
      nodeOutput: {
        data: [{ type: "scatter", x: [1], y: [2] }],
        metadata: {},
        ports: {
          visualization: {
            data: [{ type: "scatter", x: [1], y: [2] }],
            metadata: {},
            value: { data: [{ type: "scatter", x: [1], y: [2] }], layout: {} },
          },
        },
        presentation_contract: {
          digest: "b".repeat(64),
          payload: {
            schema_version: "spectrasherpa-node-presentation/1",
            default_presentation: "plot",
            presentations: [
              {
                presentation_id: "plot",
                label: "Plot",
                kind: "visualization",
                source_ports: ["visualization"],
                modes: ["plot"],
                description: "Declared visualization.",
              },
            ],
          },
        },
      },
    });

    expect(wrapper.text()).not.toContain("X-Axis");
    expect(wrapper.text()).not.toContain("Y-Axis");
    expect(wrapper.text()).toContain("No adjustable parameters");
  });

  it("labels PCA statistics by component and reports cumulative variance", async () => {
    const wrapper = mountInspector();
    const rows = [
      { pc: 1, mean: 0, std: 0.5163 },
      { pc: 2, mean: 0, std: 0.3284 },
      { pc: 3, mean: 0, std: 0.0874 },
    ];
    await wrapper.setProps({
      selectedNode: { ...selectedNode, type: "stats.summary", label: "Summarize Scores" },
      nodeOutput: {
        data: rows,
        metadata: {},
        ports: {
          default: {
            data: rows,
            value: { data: rows },
            metadata: {
              type: "PCA",
              summary: {
                n_observations: 50,
                n_components: 3,
                total_variance_explained: 0.982729,
              },
            },
          },
        },
        presentation_contract: {
          digest: "c".repeat(64),
          payload: {
            schema_version: "spectrasherpa-node-presentation/1",
            default_presentation: "summary",
            presentations: [
              {
                presentation_id: "summary",
                label: "Summary",
                kind: "statistics_summary",
                source_ports: ["default"],
                modes: ["record"],
                description: "PCA score summary.",
              },
            ],
          },
        },
      },
    });

    expect(wrapper.text()).toContain("PC1");
    expect(wrapper.text()).toContain("PC2");
    expect(wrapper.text()).toContain("PC3");
    expect(wrapper.text()).toContain("50 samples × 3 components; 98.3% variance explained");
  });
});
