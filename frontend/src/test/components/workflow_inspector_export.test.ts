import { shallowMount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import WorkflowInspector from "@/views/workflow-builder/WorkflowInspector.vue";

const metadata = { label: "Prepare Export", parameters: [
  { name: "filename", label: "Filename", param_type: "text", default: "output.csv", required: true },
  { name: "format", label: "Format", param_type: "select", default: "csv", required: true, options: ["csv", "json", "jdx"] },
] };
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: vi.fn() }) }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => ({ user: { id: 1 }, token: "local" }) }));
vi.mock("@/stores/workbook", () => ({ useWorkbookStore: () => ({ projectId: 1, activeSheet: { id: "sheet-1" } }) }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => ({ currentProjectId: 1 }) }));
vi.mock("@/stores/workflow", () => ({ useWorkflowStore: () => ({
  nodes: [], edges: [], workflowId: 1, getNodeMetadata: () => metadata,
  validateNodeParams: () => [], fetchReferenceDatasets: vi.fn(),
}) }));

describe("export format editing", () => {
  it.each(["json", "jdx"])("changes the suffix with %s and blocks the earlier CSV artifact", async (format) => {
    const suffix = format === "jdx" ? "zip" : format;
    const oldArtifact = { format: "csv", filename: "preprocessed.csv", shape: [1, 3] };
    const wrapper = shallowMount(WorkflowInspector, {
      props: { selectedNode: null, nodeOutput: null, isOpen: true },
      global: { directives: { tooltip: () => undefined }, stubs: {
        Button: { name: "TestButton", props: { label: String, disabled: Boolean }, template: '<button :disabled="disabled">{{ label }}</button>' },
        Dropdown: { name: "Dropdown", props: { modelValue: String, options: Array, placeholder: String },
          emits: ["update:modelValue", "change"], template: "<div />" },
        QuickPlotModal: { template: "<div />" },
        DataTableModal: { template: "<div />" },
      } },
    });
    await wrapper.setProps({ selectedNode: { id: "export_1", type: "output.export", label: "Export", x: 0, y: 0,
      params: { filename: "preprocessed.csv", format: "csv" } }, nodeOutput: { artifact: oldArtifact } });
    const download = () => wrapper.findAllComponents({ name: "TestButton" }).find(b => b.props("label") === "Download Prepared File")!;
    expect(download().props("disabled")).toBe(false);
    const choice = wrapper.findAllComponents({ name: "Dropdown" }).find(d => d.props("placeholder") === "Select format")!;
    choice.vm.$emit("update:modelValue", format);
    choice.vm.$emit("change");
    await wrapper.vm.$nextTick();
    expect(wrapper.emitted("update-params")!.at(-1)).toEqual(["export_1", { filename: `preprocessed.${suffix}`, format }]);
    expect(download().props("disabled")).toBe(true);
    expect(wrapper.text()).toContain("Export settings changed");
    await wrapper.setProps({ nodeOutput: { artifact: { ...oldArtifact, filename: `preprocessed.${suffix}`, format } } });
    expect(download().props("disabled")).toBe(false);
    wrapper.unmount();
  });
});
