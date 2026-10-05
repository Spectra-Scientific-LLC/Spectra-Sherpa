import { shallowMount } from "@vue/test-utils";
import { defineComponent, reactive } from "vue";
import { describe, expect, it, vi } from "vitest";

import WorkflowInspector from "@/views/workflow-builder/WorkflowInspector.vue";

// The split node's own declarations: a distance space governs only the two
// methods that measure sample dissimilarity, and a seed only the two that draw
// at random.
const nodeMetadata = reactive({
  label: "Train/Test Split",
  parameters: [
    {
      name: "test_size",
      label: "Test Size",
      param_type: "number",
      default: 0.2,
      required: true,
      visible_when: {
        split_method: ["random", "stratified", "sequential", "kennard_stone", "duplex", "spxy"],
      },
    },
    {
      name: "split_method",
      label: "Split Method",
      param_type: "select",
      options: ["random", "stratified", "sequential", "group_holdout", "kennard_stone", "duplex", "spxy"],
      default: "random",
      required: true,
    },
    {
      name: "held_out_groups",
      label: "Held-Out Groups",
      param_type: "string_list",
      default: [],
      description: "Exact values of the bound grouping column to place in the test partition.",
      required: false,
      visible_when: { split_method: ["group_holdout"] },
    },
    {
      name: "random_seed",
      label: "Random Seed",
      param_type: "number",
      default: 42,
      required: false,
      visible_when: { split_method: ["random", "stratified"] },
    },
    {
      name: "n_components",
      label: "PCA Components",
      param_type: "number",
      default: 0,
      required: false,
      category: "advanced",
      visible_when: { split_method: ["kennard_stone", "duplex"] },
    },
  ],
  execution_contract: { digest: "a".repeat(64), payload: {} },
});

const workflowStore = reactive({
  nodes: [] as Array<{ id: string; params: Record<string, unknown> }>,
  edges: [] as Array<{ from: string; to: string }>,
  workflowId: 1,
  getNodeMetadata: vi.fn(() => nodeMetadata),
  validateNodeParams: vi.fn(() => []),
  fetchReferenceDatasets: vi.fn(),
  executeTrial: vi.fn(),
});

vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: vi.fn() }) }));
vi.mock("@/stores/workflow", () => ({ useWorkflowStore: () => workflowStore }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => ({ currentProjectId: 1 }) }));

describe("WorkflowInspector method-scoped parameters", () => {
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

  const splitNode = (params: Record<string, unknown>) => ({
    id: "partition_1",
    type: "data.train_test_split",
    label: "Train/Test Split",
    x: 0,
    y: 0,
    params,
  });

  it("refuses stratified splitting against an upstream continuous target", async () => {
    // The staging graph: a source declaring a continuous Moisture target feeds
    // the split node, exactly as the PLS calibration sheet wires it.
    workflowStore.nodes = [
      { id: "source_1", params: { target_type: "continuous", selected_target: "Moisture" } },
      { id: "partition_1", params: { split_method: "stratified" } },
    ];
    workflowStore.edges = [{ from: "source_1", to: "partition_1" }];

    const wrapper = mountInspector();
    await wrapper.setProps({ selectedNode: splitNode({ split_method: "stratified" }) });
    await wrapper.vm.$nextTick();

    const messages = wrapper.vm.validationErrors.map((error: { message: string }) => error.message);
    expect(messages.join(" ")).toContain("requires a categorical target");

    // Random splitting needs no classes, so it is admitted against the same target.
    wrapper.vm.localParams.split_method = "random";
    await wrapper.vm.$nextTick();
    expect(
      wrapper.vm.validationErrors.some((error: { message: string }) =>
        error.message.includes("requires a categorical target"),
      ),
    ).toBe(false);

    // With nothing upstream declaring a target type, there is no evidence of a
    // conflict and none is claimed. This keeps the walk above load-bearing.
    workflowStore.edges = [];
    wrapper.vm.localParams.split_method = "stratified";
    await wrapper.vm.$nextTick();
    expect(
      wrapper.vm.validationErrors.some((error: { message: string }) =>
        error.message.includes("requires a categorical target"),
      ),
    ).toBe(false);

    workflowStore.nodes = [];
  });

  it("hides the settings the chosen method does not govern", async () => {
    const wrapper = mountInspector();
    await wrapper.setProps({ selectedNode: splitNode({ split_method: "stratified" }) });

    const shown = [...wrapper.vm.basicParams, ...wrapper.vm.advancedParams].map(
      (param: { name: string }) => param.name,
    );
    // Stratified sampling draws at random, so its seed applies; it has no
    // distance space, so the PCA projection does not.
    expect(shown).toContain("random_seed");
    expect(shown).not.toContain("n_components");

    await wrapper.setProps({ selectedNode: splitNode({ split_method: "kennard_stone" }) });
    const ksShown = [...wrapper.vm.basicParams, ...wrapper.vm.advancedParams].map(
      (param: { name: string }) => param.name,
    );
    expect(ksShown).toContain("n_components");
    expect(ksShown).not.toContain("random_seed");
  });

  it("returns an out-of-scope value to its default rather than saving it on", async () => {
    const wrapper = mountInspector();
    // The shipped PLS calibration sheet: Kennard-Stone with five PCA components.
    await wrapper.setProps({
      selectedNode: splitNode({ split_method: "kennard_stone", n_components: 5 }),
    });
    expect(wrapper.vm.localParams.n_components).toBe(5);

    // The scientist switches to stratified sampling, which has no distance space.
    wrapper.vm.localParams.split_method = "stratified";
    wrapper.vm.emitParams();
    await wrapper.vm.$nextTick();

    expect(wrapper.vm.localParams.n_components).toBe(0);
    const emitted = wrapper.emitted("update-params");
    expect(emitted).toBeTruthy();
    const [, params] = emitted![emitted!.length - 1] as [string, Record<string, unknown>];
    // What is stored equals what will run: no leftover behind a hidden control.
    expect(params.n_components).toBe(0);
    expect(params.split_method).toBe("stratified");
  });

  it("scopes the named holdout to group holdout and warns softly until groups are selected", async () => {
    const wrapper = mountInspector();
    // Provide a connected dataset with the sample table on the wire so the
    // inspector can offer a dropdown of the exact group values.
    workflowStore.edges = [{ from: "source_1", to: "partition_1" }];
    workflowStore.nodes = [
      {
        id: "source_1",
        params: {
          target_type: "continuous",
          selected_target: "Moisture",
          group_column: "instrument",
        },
      },
    ];
    await wrapper.setProps({
      selectedNode: splitNode({ split_method: "group_holdout" }),
      inputConnections: [
        {
          toPort: "X",
          data: {
            value: {
              type: "SherpaDataset",
              sample_axis: {
                sample_table: [
                  { name: "instrument", values: ["M5", "MP5", "M5", "MP5"] },
                ],
              },
              extra: { supervision_binding: { group_column: "instrument" } },
            },
          },
        },
      ],
    });
    await wrapper.vm.$nextTick();

    const shown = [...wrapper.vm.basicParams, ...wrapper.vm.advancedParams].map(
      (param: { name: string }) => param.name,
    );
    expect(shown).toContain("held_out_groups");
    expect(shown).not.toContain("test_size");
    expect(shown).not.toContain("random_seed");

    // No hard validation error for an empty selection, just the yellow hint.
    const heldOutErrors = wrapper.vm.validationErrors.filter(
      (error: { param_name: string }) => error.param_name === "held_out_groups",
    );
    expect(heldOutErrors).toHaveLength(0);

    const hint = wrapper.find(".param-warning");
    expect(hint.exists()).toBe(true);
    expect(hint.text()).toContain("Exact values of the bound grouping column");

    // With the sample table present, a dropdown is rendered instead of a text field.
    expect(wrapper.find("inputtext").exists()).toBe(false);
    expect(wrapper.find("multi-select-stub").exists()).toBe(true);

    wrapper.vm.localParams.held_out_groups = ["MP5"];
    wrapper.vm.emitParams();
    await wrapper.vm.$nextTick();

    expect(wrapper.find(".param-warning").exists()).toBe(false);

    // Switching back to random retires the named holdout with the control.
    wrapper.vm.localParams.split_method = "random";
    wrapper.vm.emitParams();
    await wrapper.vm.$nextTick();
    expect(wrapper.vm.localParams.held_out_groups).toEqual([]);
    const emitted = wrapper.emitted("update-params");
    const [, params] = emitted![emitted!.length - 1] as [string, Record<string, unknown>];
    expect(params.held_out_groups).toEqual([]);
  });
});
