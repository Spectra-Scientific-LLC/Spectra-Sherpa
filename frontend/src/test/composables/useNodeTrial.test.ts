import { describe, it, expect, vi, beforeEach } from "vitest";
import { ref, defineComponent, h } from "vue";
import { mount } from "@vue/test-utils";
import {
  useNodeTrial,
  STORAGE_KEY,
} from "@/views/workflow-builder/node-detail/composables/useNodeTrial";

const postMock = vi.fn();
vi.mock("@/api/client", () => ({
  default: { post: (...args: unknown[]) => postMock(...args) },
}));

class FakeChannel {
  onmessage: ((e: MessageEvent) => void) | null = null;
  postMessage = vi.fn();
  close = vi.fn();
  constructor(public name: string) {}
}

beforeEach(() => {
  postMock.mockReset();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).BroadcastChannel = FakeChannel;
  sessionStorage.clear();
});

function makeToast() {
  return { add: vi.fn(), remove: vi.fn(), removeGroup: vi.fn(), removeAllGroups: vi.fn() };
}

function harness(opts: {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  nodeData: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  params?: Record<string, any>;
  addLog?: ReturnType<typeof vi.fn>;
  normalizeNodeOutput?: ReturnType<typeof vi.fn>;
}) {
  const nodeData = ref(opts.nodeData);
  const localParams = ref(opts.params ?? {});
  const nodeType = ref("model.pca");
  const addLog = opts.addLog ?? vi.fn();
  const normalizeNodeOutput =
    opts.normalizeNodeOutput ?? vi.fn((r) => ({ data: r, metadata: {} }));
  const toast = makeToast();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let api: any;
  const Comp = defineComponent({
    setup() {
      api = useNodeTrial({
        nodeData,
        localParams,
        nodeType,
        addLog,
        normalizeNodeOutput,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        toast: toast as any,
      });
      return () => h("div");
    },
  });
  const wrapper = mount(Comp);
  return { wrapper, api: () => api, addLog, toast, normalizeNodeOutput, nodeData, localParams };
}

describe("useNodeTrial", () => {
  it("broadcastParamsUpdate writes to sessionStorage with merged params", () => {
    const { api } = harness({ nodeData: { id: 7, type: "model.pca", params: { x: 1 } }, params: { x: 2 } });
    api().broadcastParamsUpdate();
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "{}");
    expect(saved.id).toBe(7);
    expect(saved.params).toEqual({ x: 2 });
    expect(saved._saved).toBe(true);
  });

  it("handleRunTrial short-circuits when nodeData is missing", async () => {
    const { api, addLog } = harness({ nodeData: null });
    await api().handleRunTrial();
    expect(addLog).not.toHaveBeenCalled();
    expect(postMock).not.toHaveBeenCalled();
  });

  it("handleRunTrial throws-and-logs when workflowNodes is empty", async () => {
    const { api, addLog } = harness({
      nodeData: { id: 1, type: "model.pca", workflowNodes: [], workflowEdges: [] },
    });
    await api().handleRunTrial();
    const calls = addLog.mock.calls.map((c) => c[0]);
    expect(calls).toContain("error");
  });

  it("handleRunTrial posts a trial payload and normalizes the result on success", async () => {
    postMock.mockResolvedValueOnce({ data: { status: "ok", result: { foo: "bar" } } });
    const normalizeNodeOutput = vi.fn(() => ({ data: [[1, 2]], metadata: {} }));
    const { api, normalizeNodeOutput: n, nodeData } = harness({
      nodeData: {
        id: 1,
        type: "model.pca",
        workflowNodes: [{ id: 1, type: "model.pca", params: {} }],
        workflowEdges: [],
        params: {},
      },
      params: { n_components: 3 },
      normalizeNodeOutput,
    });
    await api().handleRunTrial();
    expect(postMock).toHaveBeenCalledWith(
      "/workflows/trial/execute",
      expect.objectContaining({ target_node_id: "1", trial_params: { n_components: 3 } }),
    );
    expect(n).toHaveBeenCalledWith({ foo: "bar" });
    expect(nodeData.value.output).toEqual({ data: [[1, 2]], metadata: {} });
  });

  it("handleRunTrial surfaces API errors via toast + log", async () => {
    postMock.mockRejectedValueOnce({ response: { data: { detail: "boom" } } });
    const { api, toast, addLog } = harness({
      nodeData: {
        id: 1,
        type: "model.pca",
        workflowNodes: [{ id: 1, type: "model.pca" }],
        workflowEdges: [],
      },
    });
    await api().handleRunTrial();
    expect(addLog).toHaveBeenCalledWith("error", "Trial failed", "boom");
    expect(toast.add).toHaveBeenCalledWith(expect.objectContaining({ severity: "error" }));
  });
});
