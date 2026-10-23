import { flushPromises, shallowMount, type VueWrapper } from "@vue/test-utils";
import { defineComponent, reactive } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import WorkflowInspector from "@/views/workflow-builder/WorkflowInspector.vue";
import WorkspaceState from "@/components/workspace/WorkspaceState.vue";

const { apiGet, toastAdd } = vi.hoisted(() => ({ apiGet: vi.fn(), toastAdd: vi.fn() }));
vi.mock("@/api/client", () => ({ default: { get: apiGet } }));
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: toastAdd }) }));
const auth = reactive({ user: { id: 1 }, token: "session-A", get sessionRevision() { return this.token; } });
const project = reactive({ currentProjectId: 1 });
const workbook = reactive({ projectId: 1, activeSheet: { workflowId: 9, trialId: undefined as string | undefined } });
const metadata = {
  label: "Input", parameters: [],
  output_ports: [{ name: "default", label: "Data" }],
};
const workflow = reactive({
  workflowId: 9, restoredRunId: 31 as number | null, executionEvidenceScope: "restored_summary",
  nodes: [], edges: [], lastExecutionResultDescriptors: {},
  getNodeMetadata: vi.fn(() => metadata), validateNodeParams: vi.fn(() => []),
  fetchReferenceDatasets: vi.fn(),
});
vi.mock("@/stores/auth", () => ({ useAuthStore: () => auth }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => project }));
vi.mock("@/stores/workbook", () => ({ useWorkbookStore: () => workbook }));
vi.mock("@/stores/workflow", () => ({ useWorkflowStore: () => workflow }));

const node = () => ({
  id: "source_1", type: "data.file_load", label: "Input", x: 0, y: 0,
  params: { source: "csv", legacy: { choices: ["recorded"] }, metadata: { species: [{ name: "Original" }] } },
});
const output = () => ({
  data: [[-1]], metadata: { persisted_preview: true }, primary_port: "default",
  ports: { default: { data: [[-1]], metadata: {}, value: { type: "SherpaDataset", data: [[-1]], metadata: {} } } },
  presentation_contract: { digest: "a".repeat(64), payload: {
    schema_version: "spectrasherpa-node-presentation/1", default_presentation: "spectra",
    presentations: [{ presentation_id: "spectra", label: "Spectra", kind: "spectral_dataset",
      source_ports: ["default"], modes: ["plot", "table"], description: "" }],
  } },
});
const response = (n: number) => ({ data: { value: { type: "SherpaDataset", data: [[n]], metadata: { sample_labels: [`Sample ${n}`] } } } });
function deferred() {
  let resolve!: (value: ReturnType<typeof response>) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<ReturnType<typeof response>>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const modal = defineComponent({ props: ["modelValue", "nodeOutput", "evidenceError"], template: "<div />" });
let wrappers: VueWrapper[] = [];
function mountInspector() {
  const wrapper = shallowMount(WorkflowInspector, {
    props: { selectedNode: node(), nodeOutput: output(), isOpen: true },
    global: { directives: { tooltip: () => undefined }, stubs: {
      QuickPlotModal: modal, DataTableModal: modal, WorkspaceState: false,
    } },
  });
  wrappers.push(wrapper);
  return wrapper;
}
beforeEach(() => {
  apiGet.mockReset(); toastAdd.mockReset();
  auth.user.id = 1; auth.token = "session-A";
  project.currentProjectId = 1; workbook.projectId = 1;
  workbook.activeSheet.workflowId = 9; workbook.activeSheet.trialId = undefined;
  workflow.workflowId = 9; workflow.restoredRunId = 31; workflow.executionEvidenceScope = "restored_summary";
  workflow.validateNodeParams.mockReturnValue([]);
});
afterEach(() => { for (const wrapper of wrappers) wrapper.unmount(); wrappers = []; });

describe("Inspector retained evidence request ownership", () => {
  const transitions = [
    ["run", () => { workflow.restoredRunId = 32; }, () => { workflow.restoredRunId = 31; }],
    ["project", () => { project.currentProjectId = 2; }, () => { project.currentProjectId = 1; }],
    ["workbook", () => { workbook.projectId = 2; }, () => { workbook.projectId = 1; }],
    ["sheet", () => { workbook.activeSheet.workflowId = 10; }, () => { workbook.activeSheet.workflowId = 9; }],
    ["trial", () => { workbook.activeSheet.trialId = "trial-A"; }, () => { workbook.activeSheet.trialId = undefined; }],
    ["workflow", () => { workflow.workflowId = 10; }, () => { workflow.workflowId = 9; }],
    ["user", () => { auth.user.id = 2; }, () => { auth.user.id = 1; }],
    ["credential", () => { auth.token = "session-B"; }, () => { auth.token = "session-A"; }],
  ] as const;

  it.each(transitions)("rejects delayed %s A→B→A success and closes old dialogs synchronously", async (_name, away, back) => {
    const wrapper = mountInspector();
    const vm = wrapper.vm as any;
    const old = deferred();
    apiGet.mockReturnValueOnce(old.promise);
    const opening = vm.openDataTable();
    expect(apiGet.mock.calls[0][1].signal.aborted).toBe(false);
    vm.showQuickPlotModal = true;
    vm.showMetadataModal = true;
    away();
    expect(vm.showQuickPlotModal).toBe(false);
    expect(vm.showMetadataModal).toBe(false);
    back(); // no Vue render tick between transitions
    expect(apiGet.mock.calls[0][1].signal.aborted).toBe(true);
    old.resolve(response(100));
    await opening; await flushPromises();
    expect(vm.showDataTableModal).toBe(false);
    expect(vm.quickPlotNodeOutput?.data).not.toEqual([[100]]);
    expect(vm.quickPlotLoading).toBe(false);
  });

  it.each(["plot", "table"])("does not let a stale %s error/finally clear a newer request or show a toast", async (view) => {
    const wrapper = mountInspector(); const vm = wrapper.vm as any;
    const old = deferred(), current = deferred();
    apiGet.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const open = () => view === "plot" ? vm.openQuickPlot() : vm.openDataTable();
    const first = open();
    workflow.restoredRunId = 32;
    const second = open();
    old.reject(new Error("old run failed"));
    await first; await flushPromises();
    expect(vm.quickPlotLoading).toBe(true);
    expect(vm.quickPlotEvidenceError).toBe("");
    expect(vm.showQuickPlotModal).toBe(false);
    expect(vm.showDataTableModal).toBe(false);
    expect(toastAdd).not.toHaveBeenCalled();
    current.resolve(response(200));
    await second; await flushPromises();
    expect(vm.quickPlotNodeOutput.data).toEqual([[200]]);
    expect(vm.quickPlotLoading).toBe(false);
    expect(view === "plot" ? vm.showQuickPlotModal : vm.showDataTableModal).toBe(true);
  });

  it.each(transitions)("does not open a trial after a delayed %s scope change", async (_name, away, back) => {
    const wrapper = mountInspector(); const vm = wrapper.vm as any;
    const old = deferred(); apiGet.mockReturnValueOnce(old.promise);
    const opening = vm.openToRunTrials();
    away(); back();
    old.resolve(response(100));
    await opening;
    expect(wrapper.emitted("open-trial")).toBeUndefined();
    expect(toastAdd).not.toHaveBeenCalled();
  });

  it("keeps a missing exact detail result unavailable rather than handing off its preview", async () => {
    const wrapper = mountInspector(); const vm = wrapper.vm as any;
    apiGet.mockRejectedValueOnce(new Error("Retained evidence missing"));
    await vm.openToRunTrials();
    expect(wrapper.emitted("open-trial")).toBeUndefined();
    expect(vm.quickPlotEvidenceError).toContain("exact retained output is unavailable");
    expect(toastAdd).toHaveBeenCalledWith(expect.objectContaining({ summary: "Data unavailable" }));
  });

  it("opens an unexecuted node for editing and trial without inventing retained output", async () => {
    const wrapper = mountInspector();
    await wrapper.setProps({ nodeOutput: null });
    await (wrapper.vm as any).openToRunTrials();
    const [detail] = wrapper.emitted("open-trial")!.at(-1)! as any[];
    expect(detail.output).toBeNull();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("opens an unexecuted connected node when an ancestor's retained result is unavailable", async () => {
    const wrapper = mountInspector();
    await wrapper.setProps({ nodeOutput: null, inputConnections: [{ nodeId: "ancestor", nodeType: "data.file_load",
      nodeLabel: "Ancestor", port: "default", toPort: "X", data: output() }] });
    apiGet.mockRejectedValueOnce(new Error("Ancestor retention unavailable"));
    await (wrapper.vm as any).openToRunTrials();
    const [detail] = wrapper.emitted("open-trial")!.at(-1)! as any[];
    expect(detail.output).toBeNull();
    expect(detail.inputConnections[0].data).toBeNull();
    expect(detail.inputData).toBeNull();
    expect(toastAdd).not.toHaveBeenCalled();
  });

  it("rejects a node change while retained Data View loads", async () => {
    const wrapper = mountInspector(); const vm = wrapper.vm as any;
    const old = deferred(); apiGet.mockReturnValueOnce(old.promise);
    const opening = vm.openDataTable();
    await wrapper.setProps({ selectedNode: { ...node(), id: "source_2" } });
    old.resolve(response(100));
    await opening;
    expect(vm.showDataTableModal).toBe(false);
    expect(vm.quickPlotNodeOutput?.data).not.toEqual([[100]]);
  });

  it("supersedes a same-context request without letting its late success replace the current table", async () => {
    const wrapper = mountInspector(); const vm = wrapper.vm as any;
    const old = deferred(), current = deferred();
    apiGet.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const first = vm.openQuickPlot();
    const second = vm.openDataTable();
    expect(apiGet.mock.calls[0][1].signal.aborted).toBe(true);
    current.resolve(response(200));
    await second;
    old.resolve(response(100));
    await first;
    expect(vm.quickPlotNodeOutput.data).toEqual([[200]]);
    expect(vm.showDataTableModal).toBe(true);
    expect(vm.showQuickPlotModal).toBe(false);
    expect(vm.quickPlotLoading).toBe(false);
  });

  it("invalidates presentation changes even when switched back before rendering", async () => {
    const wrapper = mountInspector(); const vm = wrapper.vm as any;
    const old = deferred(); apiGet.mockReturnValueOnce(old.promise);
    const opening = vm.openQuickPlot();
    const previous = vm.selectedPresentationId;
    vm.selectedPresentationId = "other"; vm.selectedPresentationId = previous;
    old.resolve(response(100));
    await opening;
    expect(vm.showQuickPlotModal).toBe(false);
  });

  it("rejects retained hydration when its connected input binding changes", async () => {
    const wrapper = mountInspector(); const vm = wrapper.vm as any;
    const old = deferred(); apiGet.mockReturnValueOnce(old.promise);
    const opening = vm.openQuickPlot();
    await wrapper.setProps({ inputConnections: [{
      nodeId: "replacement", nodeType: "data.file_load", nodeLabel: "Replacement",
      port: "default", toPort: "X", data: null,
    }] });
    old.resolve(response(100));
    await opening;
    expect(vm.showQuickPlotModal).toBe(false);
    expect(vm.quickPlotNodeOutput?.data).not.toEqual([[100]]);
  });

  it("refuses current missing retained evidence rather than displaying the summary as a table", async () => {
    const wrapper = mountInspector(); const vm = wrapper.vm as any;
    apiGet.mockRejectedValueOnce(new Error("missing retained output"));
    await vm.openDataTable(); await flushPromises();
    expect(vm.showDataTableModal).toBe(false);
    expect(vm.quickPlotNodeOutput).toBeNull();
    expect(wrapper.findAllComponents(WorkspaceState).some(state => state.props("kind") === "unavailable")).toBe(true);
    expect(toastAdd).toHaveBeenCalledOnce();
  });

  it("does not use a compact history summary as evidence when run identity is missing", async () => {
    const wrapper = mountInspector(); const vm = wrapper.vm as any;
    workflow.restoredRunId = null;
    await vm.openDataTable();
    expect(apiGet).not.toHaveBeenCalled();
    expect(vm.showDataTableModal).toBe(false);
    expect(vm.quickPlotNodeOutput).toBeNull();
    expect(vm.quickPlotEvidenceError).toContain("identity");
  });

  it("aborts on unmount and suppresses later errors and modal reopening", async () => {
    const wrapper = mountInspector(); const vm = wrapper.vm as any;
    const old = deferred(); apiGet.mockReturnValueOnce(old.promise);
    const opening = vm.openDataTable();
    wrapper.unmount(); wrappers = [];
    expect(apiGet.mock.calls[0][1].signal.aborted).toBe(true);
    old.reject(new Error("after dispose"));
    await opening;
    expect(toastAdd).not.toHaveBeenCalled();
    expect(vm.showDataTableModal).toBe(false);
  });
});

describe("Inspector parameter draft boundary", () => {
  it("detaches nested legacy parameters, metadata and emitted updates from saved nodes and retained evidence", async () => {
    const wrapper = mountInspector(); const vm = wrapper.vm as any;
    const saved = wrapper.props("selectedNode")!;
    const retained = wrapper.props("nodeOutput");
    const retainedBefore = JSON.stringify(retained);
    vm.localParams.legacy.choices.push("draft");
    vm.localMetadata.species[0].name = "Edited";
    expect(saved.params.legacy.choices).toEqual(["recorded"]);
    expect(saved.params.metadata.species[0].name).toBe("Original");
    vm.emitParams();
    const sent = wrapper.emitted("update-params")!.at(-1)![1] as any;
    vm.localParams.legacy.choices.push("later");
    expect(sent.legacy.choices).toEqual(["recorded", "draft"]);
    expect(JSON.stringify(retained)).toBe(retainedBefore);
  });

  it("resets a dirty same-node draft on sheet scope change and preserves live edits on a late server refresh", async () => {
    const wrapper = mountInspector(); const vm = wrapper.vm as any;
    vm.localParams.legacy.choices.push("draft");
    await wrapper.setProps({ selectedNode: { ...node(), params: { ...node().params, source: "server-refresh" } } });
    expect(vm.localParams.legacy.choices).toEqual(["recorded", "draft"]);
    workbook.activeSheet.workflowId = 10;
    expect(vm.localParams.legacy.choices).toEqual(["recorded"]);
    expect(vm.localParams.source).toBe("server-refresh");
    expect(wrapper.emitted("update-params")).toBeUndefined();
  });

  it("continues canonical validation and emits parameters before execution without changing retained output", () => {
    const wrapper = mountInspector(); const vm = wrapper.vm as any;
    workflow.validateNodeParams.mockReturnValueOnce([{ param_name: "source", message: "Invalid source" }] as never[]);
    vm.executeNode();
    expect(wrapper.emitted("execute-node")).toBeUndefined();
    vm.executeNode();
    expect(wrapper.emitted("execute-node")).toEqual([["source_1"]]);
    expect(wrapper.emitted("update-params")).toHaveLength(1);
    expect(wrapper.props("nodeOutput")?.data).toEqual([[-1]]);
  });

  it("clears prior-context validation errors before the replacement sheet is rendered", () => {
    const wrapper = mountInspector(); const vm = wrapper.vm as any;
    workflow.validateNodeParams.mockReturnValueOnce([{ param_name: "source", message: "Old sheet error" }] as never[]);
    vm.validateParams();
    expect(vm.validationErrors).toHaveLength(1);
    workbook.activeSheet.workflowId = 10;
    expect(vm.validationErrors).toEqual([]);
  });
});
