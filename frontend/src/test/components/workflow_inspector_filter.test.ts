import { shallowMount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { describe, expect, it, vi } from "vitest";
import WorkflowInspector from "@/views/workflow-builder/WorkflowInspector.vue";

vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: vi.fn() }) }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => ({ currentProjectId: 1 }) }));
vi.mock("@/stores/workflow", () => ({ useWorkflowStore: () => ({
  nodes: [], edges: [], workflowId: 1,
  getNodeMetadata: () => ({ label: "Filter", parameters: [] }),
  validateNodeParams: () => [], fetchReferenceDatasets: vi.fn(),
}) }));

const inputs = [{ nodeId: "source", port: "default", toPort: "X", label: "Source",
  data: { data: [[1, 2], [3, 4]], metadata: { n_samples: 2, n_features: 2 } } }];

describe("Filter inspection is read-only", () => {
  it.each([
    { field: "source_inclusion", pattern: "", match_mode: "contains" },
    { field: "sample_label", pattern: "retained specimen", match_mode: "equals" },
    { field: "sample_table", sample_table_column: "saved_column", pattern: "A" },
    { field: "intensity", intensity_threshold: 7, intensity_operator: "gte" },
  ])("preserves saved $field when inputs appear or disappear", async (params) => {
    const original = structuredClone(params);
    const node = { id: "filter_1", type: "data.filter_samples", label: "Filter", x: 0, y: 0, params };
    const wrapper = shallowMount(WorkflowInspector, {
      props: { selectedNode: null, nodeOutput: null, isOpen: true, inputConnections: [] },
      global: { directives: { tooltip: () => undefined }, stubs: {
        QuickPlotModal: defineComponent({ template: "<div />" }),
        DataTableModal: defineComponent({ template: "<div />" }),
      } },
    });
    await wrapper.setProps({ selectedNode: node, inputConnections: inputs });
    expect(wrapper.emitted("update-params")).toBeUndefined();
    await wrapper.setProps({ inputConnections: [] });
    await wrapper.setProps({ inputConnections: inputs });
    await wrapper.setProps({ selectedNode: null });
    await wrapper.setProps({ selectedNode: node });
    expect(wrapper.emitted("update-params")).toBeUndefined();
    expect(params).toEqual(original);
    if (params.field === "source_inclusion") {
      expect(wrapper.text()).toContain("Source inclusion is applied by the workflow");
      const button = wrapper.findAll("button").find(b => b.text().includes("By index"));
      expect(button).toBeDefined();
      await button!.trigger("click");
      const updates = wrapper.emitted("update-params")!;
      expect(updates).toHaveLength(1);
      expect(updates[0][1]).toMatchObject({ field: "sample_index", pattern: "1-2", match_mode: "in_list" });
    }
    wrapper.unmount();
  });
});
