import { mount, shallowMount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import api from "@/api/client";
import WorkflowInspector from "@/views/workflow-builder/WorkflowInspector.vue";
import SettingsPanel from "@/views/workflow-builder/node-detail/panels/SettingsPanel.vue";
import { useWorkflowStore } from "@/stores/workflow";
import type { NodeTypeMetadata } from "@/types";

vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: vi.fn() }) }));
vi.mock("@/api/client", () => ({
  default: { get: vi.fn().mockResolvedValue({ data: [] }), post: vi.fn() },
}));
const metadata: NodeTypeMetadata = {
  node_type: "analysis.peak_finding",
  category: "exploratory",
  label: "Peak Finding",
  description: "",
  input_types: [],
  output_type: "dict",
  parameters: [
    {
      name: "prominence",
      label: "Prominence",
      param_type: "number",
      default: null,
      min_value: 0,
      step: 0.01,
      required: false,
    },
    {
      name: "consensus_tolerance",
      label: "Consensus Tolerance",
      param_type: "number",
      default: 0,
      min_value: 0,
      step: 0.1,
      required: false,
      category: "advanced",
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  setActivePinia(createPinia());
  useWorkflowStore().nodeLibrary.set(metadata.node_type, metadata);
});

describe("scientific parameter editors use the entered value", () => {
  it("Inspector saves decimals, advanced values, and refuses invalid execution drafts", async () => {
    const wrapper = shallowMount(WorkflowInspector, {
      props: { selectedNode: null, nodeOutput: null, isOpen: true },
      global: {
        directives: { tooltip: () => undefined },
        stubs: {
          ScientificNumberInput: false,
          Accordion: defineComponent({ template: "<div><slot /></div>" }),
          AccordionTab: defineComponent({ template: "<div><slot /></div>" }),
        },
      },
    });
    const node = {
      id: "peaks",
      type: metadata.node_type,
      label: "Peak Finding",
      x: 0,
      y: 0,
      params: { prominence: null, consensus_tolerance: 0 },
    };
    await wrapper.setProps({ selectedNode: node });
    const prominence = wrapper.get('input[id="parameter-prominence"]');
    for (const text of ["0", "0.", "0.5"]) await prominence.setValue(text);
    expect(prominence.element.value).toBe("0.5");
    expect(wrapper.emitted("update-params")?.at(-1)?.[1]).toMatchObject({ prominence: 0.5 });
    await wrapper.get('input[id="parameter-consensus_tolerance"]').setValue("1e-8");
    expect(wrapper.emitted("update-params")?.at(-1)?.[1]).toMatchObject({
      consensus_tolerance: 1e-8,
    });
    for (const invalid of ["1e-", "-0.5", "1e-400"]) {
      await prominence.setValue(invalid);
      expect(wrapper.vm.hasValidationErrors).toBe(true);
      wrapper.vm.executeNode();
      expect(wrapper.emitted("execute-node")).toBeUndefined();
    }
    await prominence.setValue("0.123456789");
    wrapper.vm.executeNode();
    expect(wrapper.emitted("execute-node")?.at(-1)).toEqual(["peaks"]);
    const params = wrapper.emitted("update-params")?.at(-1)?.[1];
    expect(JSON.parse(JSON.stringify(params))).toMatchObject({
      prominence: 0.123456789,
      consensus_tolerance: 1e-8,
    });
  });

  it("expanded SettingsPanel preserves fractional digits and passes drafts to common validation", async () => {
    const wrapper = mount(SettingsPanel, {
      props: {
        expanded: true,
        settingsCount: 1,
        params: [{ name: "prominence", label: "Prominence", type: "number", min: 0, step: 0.01 }],
        localParams: { prominence: null },
        hasValidationErrors: false,
        displayedValidationErrors: [],
        getParamError: () => null,
      },
    });
    const input = wrapper.get("input#prominence");
    for (const text of ["0", "0.", "0.5", "0.123456789", "1e-9", "1e-"]) {
      await input.setValue(text);
      const [name, value] = wrapper.emitted("updateParam")!.at(-1)!;
      await wrapper.setProps({ localParams: { [name as string]: value } });
      await input.trigger("blur");
      expect(input.element.value).toBe(text);
      if (text === "1e-") {
        expect(
          useWorkflowStore().validateNodeParams(metadata.node_type, { prominence: value }),
        ).toHaveLength(1);
      } else {
        expect(value).toBe(Number(text));
      }
    }
  });

  it("metadata numeric drafts cannot execute as stale or clamped values", async () => {
    const store = useWorkflowStore();
    store.nodeLibrary.set("data.synthetic_curve", {
      ...metadata,
      node_type: "data.synthetic_curve",
      parameters: [],
    });
    const wrapper = shallowMount(WorkflowInspector, {
      props: { selectedNode: null, nodeOutput: null, isOpen: true },
      global: { directives: { tooltip: () => undefined } },
    });
    await wrapper.setProps({
      selectedNode: {
        id: "source",
        type: "data.synthetic_curve",
        label: "Source",
        x: 0,
        y: 0,
        params: {},
      },
    });
    wrapper.vm.localMetadata.conditions.pressure_atm = "1e-";
    wrapper.vm.emitMetadata();
    expect(wrapper.emitted("update-params")?.at(-1)?.[1]).toMatchObject({
      metadata: { conditions: { pressure_atm: "1e-" } },
    });
    wrapper.vm.executeNode();
    expect(wrapper.emitted("execute-node")).toBeUndefined();
    wrapper.vm.localMetadata.conditions.pressure_atm = 0.123456789;
    wrapper.vm.emitMetadata();
    wrapper.vm.executeNode();
    expect(wrapper.emitted("execute-node")?.at(-1)).toEqual(["source"]);
  });
});

describe("execution entry point numeric gates", () => {
  it.each(["1e-", "1e-400", -0.5])(
    "refuses draft %s in a workflow, node dependency, and trial",
    async (value) => {
      const store = useWorkflowStore();
      store.nodes = [
        {
          id: "peaks",
          type: metadata.node_type,
          label: "Peaks",
          x: 0,
          y: 0,
          params: { prominence: value },
        },
        { id: "output", type: "output.plot", label: "Plot", x: 0, y: 0, params: {} },
      ];
      store.edges = [{ id: "edge", from: "peaks", to: "output" }];
      await expect(store.executeWorkflow()).rejects.toThrow("Prominence");
      await expect(store.executeNode("output")).rejects.toThrow("Prominence");
      const result = await store.executeTrial("output", {});
      expect(result.status).toBe("error");
      expect(result.error).toContain("Prominence");
      expect(api.post).not.toHaveBeenCalled();
    },
  );

  it("checks trial overrides instead of the saved parameter", async () => {
    const store = useWorkflowStore();
    store.nodes = [
      {
        id: "peaks",
        type: metadata.node_type,
        label: "Peaks",
        x: 0,
        y: 0,
        params: { prominence: 0.5 },
      },
    ];
    const result = await store.executeTrial("peaks", { prominence: "1e-" });
    expect(result.status).toBe("error");
    expect(api.post).not.toHaveBeenCalled();
  });

  it("allows explicit blank optional filters and checks required fields", () => {
    const store = useWorkflowStore();
    expect(store.validateNodeParams(metadata.node_type, { prominence: null })).toEqual([]);
    expect(store.validateNodeParams(metadata.node_type, { prominence: 0.5 })).toEqual([]);
    const withRequired = {
      ...metadata,
      parameters: [
        ...metadata.parameters,
        {
          name: "required_number",
          param_type: "number",
          label: "Required Number",
          required: true,
          default: 0,
        },
      ],
    };
    store.nodeLibrary.set(metadata.node_type, withRequired);
    expect(store.validateNodeParams(metadata.node_type, {})).toEqual([]);
    expect(store.validateNodeParams(metadata.node_type, { required_number: null })).toHaveLength(1);
  });
});
