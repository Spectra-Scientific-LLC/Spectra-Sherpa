import { shallowMount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { describe, expect, it, vi } from "vitest";
import WorkflowInspector from "@/views/workflow-builder/WorkflowInspector.vue";

const metadata = {
  label: "Normalize",
  parameters: [
    { name: "method", label: "Method", param_type: "select", default: "snv", required: true,
      options: [{ label: "SNV", value: "snv" }, { label: "Scale", value: "scale" }] },
    { name: "scale_method", label: "Scale Method", param_type: "select", default: "max",
      options: ["max", "area", "minmax"], visible_when: { method: ["scale"] } },
    { name: "std_ddof", label: "SNV standard-deviation convention", param_type: "select", default: 0,
      category: "advanced", options: [{ label: "Population", value: 0 }, { label: "Sample", value: 1 }],
      visible_when: { method: ["snv"] } },
  ],
};
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: vi.fn() }) }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => ({ currentProjectId: 1 }) }));
vi.mock("@/stores/workflow", () => ({ useWorkflowStore: () => ({
  nodes: [], edges: [], workflowId: 1,
  getNodeMetadata: () => metadata, validateNodeParams: () => [], fetchReferenceDatasets: vi.fn(),
}) }));

describe("Normalize inspector", () => {
  const mountInspector = () => shallowMount(WorkflowInspector, {
    props: { selectedNode: null, nodeOutput: null, isOpen: true },
    global: {
      directives: { tooltip: () => undefined },
      stubs: {
        Dropdown: defineComponent({ name: "Dropdown", props: ["modelValue", "options", "placeholder"],
          emits: ["update:modelValue", "change"], template: "<div />" }),
        QuickPlotModal: defineComponent({ template: "<div />" }),
        DataTableModal: defineComponent({ template: "<div />" }),
      },
    },
  });
  const node = {
    id: "normalize_1", type: "preprocess.normalize", label: "Normalize", x: 0, y: 0,
    params: { method: "snv", std_ddof: 1, scale_method: "max" },
  };

  it.each(["max", "area", "minmax"])("saves admitted scale/%s and clears hidden SNV settings", async (scaleMethod) => {
    const wrapper = mountInspector();
    await wrapper.setProps({ selectedNode: node });
    const method = wrapper.findAllComponents({ name: "Dropdown" }).find(d =>
      d.props("placeholder") === "Select method");
    expect(method).toBeDefined();
    expect(method!.props("options")).toEqual(metadata.parameters[0].options);
    method!.vm.$emit("update:modelValue", "scale");
    method!.vm.$emit("change");
    await wrapper.vm.$nextTick();
    const scale = wrapper.findAllComponents({ name: "Dropdown" }).find(d =>
      d.props("placeholder") === "Select scale method");
    expect(scale).toBeDefined();
    expect(scale!.props("options").map((o: { value: string }) => o.value)).toEqual(["max", "area", "minmax"]);
    scale!.vm.$emit("update:modelValue", scaleMethod);
    scale!.vm.$emit("change");
    const updates = wrapper.emitted("update-params")!;
    expect(updates.at(-1)).toEqual(["normalize_1", { method: "scale", scale_method: scaleMethod, std_ddof: 0 }]);

    method!.vm.$emit("update:modelValue", "snv");
    method!.vm.$emit("change");
    await wrapper.vm.$nextTick();
    expect(wrapper.emitted("update-params")!.at(-1)).toEqual([
      "normalize_1", { method: "snv", scale_method: "max", std_ddof: 0 },
    ]);
    expect(wrapper.text()).not.toContain("Scale Method");
    wrapper.unmount();
  });
});
