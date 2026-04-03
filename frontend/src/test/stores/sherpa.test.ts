import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { reactive } from "vue";

const mockWs = {
  readyState: WebSocket.OPEN,
  send: vi.fn(),
};

const mockLlmStore = reactive({
  wsRef: mockWs as unknown as WebSocket,
  connect: vi.fn<() => Promise<void>>(),
  connectionStatus: "connected" as "disconnected" | "connecting" | "connected",
});

const mockWorkflowStore = reactive({
  workflowId: 5,
  workflowName: "Test workflow",
  workflowDescription: "Test description",
  currentTemplateId: "template-1",
  nodes: [] as Array<Record<string, unknown>>,
  edges: [] as Array<Record<string, unknown>>,
  lastExecutionResults: null as Record<string, Record<string, unknown>> | null,
  lastExecutionDiagnostics: {} as Record<string, Record<string, unknown>>,
  getNodeMetadata: vi.fn((nodeType: string) => {
    if (nodeType === "model.pls") {
      return {
        label: "PLS",
        description: "Partial least squares model",
        output_type: "PLSModel",
        parameters: [
          {
            name: "n_components",
            label: "Components",
            description: "Number of latent variables",
          },
        ],
      };
    }
    if (nodeType === "data.source") {
      return {
        label: "Load Data",
        description: "Dataset source",
        output_type: "Dataset",
        parameters: [],
      };
    }
    return null;
  }),
});

const mockDataStore = reactive({
  catalogDatasetInfo: null as Record<string, unknown> | null,
});

vi.mock("@/stores/llm", () => ({
  useLlmStore: () => mockLlmStore,
}));

vi.mock("@/stores/workflow", () => ({
  useWorkflowStore: () => mockWorkflowStore,
}));

vi.mock("@/stores/data", () => ({
  useDataStore: () => mockDataStore,
}));

import { SHERPA_WS_EVENT } from "@/lib/sherpaWs";
import { useNotificationStore } from "@/stores/notification";
import { useSherpaStore } from "@/stores/sherpa";

describe("Sherpa Store communication state", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
    mockWs.send.mockReset();
    mockLlmStore.connect.mockReset();
    mockLlmStore.connect.mockResolvedValue(undefined);
    mockLlmStore.connectionStatus = "connected";
    mockWorkflowStore.workflowId = 5;
    mockWorkflowStore.workflowName = "Test workflow";
    mockWorkflowStore.workflowDescription = "Test description";
    mockWorkflowStore.currentTemplateId = "template-1";
    mockWorkflowStore.nodes = [];
    mockWorkflowStore.edges = [];
    mockWorkflowStore.lastExecutionResults = null;
    mockWorkflowStore.lastExecutionDiagnostics = {};
    mockWorkflowStore.getNodeMetadata.mockClear();
    mockDataStore.catalogDatasetInfo = null;
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("shows a delayed status notification when Sherpa chat is still preparing", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();

    await sherpa.sendMessage("tell me about PCA");
    await vi.advanceTimersByTimeAsync(4000);

    expect(sherpa.state).toBe("chatting");
    expect(notifications.notifications[0]?.title).toBe("Sherpa Advisor");
    expect(notifications.notifications[0]?.message).toBe(
      "Sherpa Advisor is preparing a response."
    );
  });

  it("does not show the delayed preparing notice after chat streaming starts", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();
    sherpa.init();

    await sherpa.sendMessage("tell me about PCA");
    window.dispatchEvent(new CustomEvent("sherpa-ws-message", { detail: { type: SHERPA_WS_EVENT.chatStart } }));
    await vi.advanceTimersByTimeAsync(4000);

    expect(sherpa.messages.at(-1)?.role).toBe("assistant");
    expect(notifications.notifications).toHaveLength(0);

    sherpa.dispose();
  });

  it("resets the chat timeout when Sherpa activity continues", async () => {
    const sherpa = useSherpaStore();
    sherpa.init();

    await sherpa.sendMessage("Does it make sense to use MCR-ALS upon non-time-series spectra data?");
    window.dispatchEvent(new CustomEvent("sherpa-ws-message", { detail: { type: SHERPA_WS_EVENT.chatStart } }));

    await vi.advanceTimersByTimeAsync(119_000);
    window.dispatchEvent(
      new CustomEvent("sherpa-ws-message", {
        detail: { type: SHERPA_WS_EVENT.chatChunk, chunk: "Yes, it can." },
      })
    );

    await vi.advanceTimersByTimeAsync(119_000);
    expect(sherpa.state).toBe("chatting");
    expect(sherpa.messages.some((m) => m.content.includes("timed out"))).toBe(false);

    await vi.advanceTimersByTimeAsync(2_000);
    expect(sherpa.state).toBe("idle");
    expect(sherpa.messages.at(-1)?.content).toContain("Chat response timed out");

    sherpa.dispose();
  });

  it("recovers Sherpa chat state on shared socket transport failure", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();
    sherpa.init();

    await sherpa.sendMessage("tell me about PCA");
    window.dispatchEvent(
      new CustomEvent("app-ws-transport", {
        detail: {
          kind: "closed",
          detail: "Connection lost during Sherpa request. Please try again.",
        },
      })
    );

    expect(sherpa.state).toBe("idle");
    expect(sherpa.messages.at(-1)?.content).toContain("Connection lost during Sherpa request");
    expect(notifications.notifications[0]?.severity).toBe("warning");
    expect(notifications.notifications[0]?.title).toBe("Sherpa Advisor");

    sherpa.dispose();
  });

  it("allows Sherpa chat without a workflow for general questions", async () => {
    const sherpa = useSherpaStore();
    mockWorkflowStore.workflowId = null;
    mockWorkflowStore.workflowName = "Untitled";

    await sherpa.sendMessage("tell me about PCA");

    expect(mockLlmStore.connect).toHaveBeenCalledOnce();
    expect(mockWs.send).toHaveBeenCalledOnce();
    const payload = JSON.parse(mockWs.send.mock.calls[0][0] as string);
    expect(payload.action).toBe("sherpa_chat");
    expect(payload.payload.workflow_id).toBeNull();
    expect(payload.payload.workflow_context.workflow_id).toBeNull();
  });

  it("includes execution results in Sherpa workflow context for metric questions", async () => {
    const sherpa = useSherpaStore();
    mockWorkflowStore.nodes = [
      {
        id: "data_1",
        type: "data.source",
        x: 0,
        y: 0,
        params: { experiment_id: 42 },
        executionState: { output_shape: [569, 30], status: "completed" },
      },
      {
        id: "pls_1",
        type: "model.pls",
        x: 250,
        y: 0,
        params: { n_components: 3 },
        executionState: { status: "completed", output_type: "PLSModel" },
      },
    ];
    mockWorkflowStore.edges = [{ from: "data_1", to: "pls_1" }];
    mockWorkflowStore.lastExecutionResults = {
      data_1: {
        type: "SherpaDataset",
        n_samples: 569,
        n_features: 30,
      },
      pls_1: {
        type: "PLSModel",
        shape: [569, 2],
        metadata: {
          accuracy: 0.97,
          model_name: "breast-cancer-pls",
          ignored: { nested: true },
        },
      },
    };
    mockWorkflowStore.lastExecutionDiagnostics = {
      pls_1: {
        accuracy: 0.97,
        precision: 0.96,
      },
    };

    await sherpa.sendMessage("What is the prediction accuracy?", true);

    const payload = JSON.parse(mockWs.send.mock.calls[0][0] as string);
    expect(payload.action).toBe("sherpa_chat_with_tools");
    expect(payload.payload.workflow_context.n_samples).toBe(569);
    expect(payload.payload.workflow_context.n_features).toBe(30);
    expect(payload.payload.workflow_context.diagnostics).toEqual({
      pls_1: {
        accuracy: 0.97,
        precision: 0.96,
      },
    });
    expect(payload.payload.workflow_context.results_summary).toEqual({
      data_1: {
        type: "SherpaDataset",
        shape: null,
        n_samples: 569,
        n_features: 30,
        metadata: null,
      },
      pls_1: {
        type: "PLSModel",
        shape: [569, 2],
        n_samples: null,
        n_features: null,
        metadata: {
          accuracy: 0.97,
          model_name: "breast-cancer-pls",
        },
      },
    });
  });

  it("completes a Sherpa agentic round trip without leaving the chat in a timeout state", async () => {
    const sherpa = useSherpaStore();
    sherpa.init();

    await sherpa.sendMessage("Explain the test result", true);

    window.dispatchEvent(new CustomEvent("sherpa-ws-message", { detail: { type: SHERPA_WS_EVENT.chatStart } }));
    window.dispatchEvent(
      new CustomEvent("sherpa-ws-message", {
        detail: {
          type: SHERPA_WS_EVENT.toolStart,
          tool_name: "describe_node",
        },
      })
    );
    window.dispatchEvent(
      new CustomEvent("sherpa-ws-message", {
        detail: {
          type: SHERPA_WS_EVENT.toolResult,
          tool_name: "describe_node",
          summary: "Node details loaded",
        },
      })
    );
    window.dispatchEvent(
      new CustomEvent("sherpa-ws-message", {
        detail: {
          type: SHERPA_WS_EVENT.chatChunk,
          chunk: "The model accuracy is 97%.",
        },
      })
    );
    window.dispatchEvent(new CustomEvent("sherpa-ws-message", { detail: { type: SHERPA_WS_EVENT.chatDone } }));

    await vi.advanceTimersByTimeAsync(121_000);

    expect(sherpa.state).toBe("idle");
    expect(sherpa.messages.at(-1)?.content).toContain("97%");
    expect(sherpa.messages.some((m) => m.content.includes("timed out"))).toBe(false);
    expect(sherpa.activeTools).toEqual([
      {
        tool_name: "describe_node",
        status: "completed",
        result: undefined,
      },
    ]);

    sherpa.dispose();
  });

  it("surfaces demo Sherpa limit errors even when upgrade_url is empty", () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();
    sherpa.init();

    window.dispatchEvent(
      new CustomEvent("sherpa-ws-message", {
        detail: {
          type: SHERPA_WS_EVENT.error,
          limit_type: "sherpa",
          message: "Demo Sherpa interaction limit reached (200 interactions per session)",
          upgrade_url: "",
        },
      })
    );

    expect(sherpa.lastSyncError).toBe(
      "Demo Sherpa interaction limit reached (200 interactions per session)"
    );
    expect(sherpa.messages.at(-1)?.content).toBe(
      "Demo Sherpa interaction limit reached (200 interactions per session)"
    );
    expect(notifications.notifications[0]?.message).toBe(
      "Demo Sherpa interaction limit reached (200 interactions per session)"
    );

    sherpa.dispose();
  });

  it("handles Sherpa decision acknowledgements explicitly", () => {
    const sherpa = useSherpaStore();
    sherpa.init();

    window.dispatchEvent(
      new CustomEvent("sherpa-ws-message", {
        detail: {
          type: SHERPA_WS_EVENT.decisionAck,
          payload: {
            delivered: true,
            suggestion_id: "rec-1",
          },
        },
      })
    );

    expect(sherpa.messages.at(-1)?.content).toBe(
      "Sherpa Advisor recorded your decision."
    );

    sherpa.dispose();
  });

  it("accepts positive Sherpa status events as active sync state", () => {
    const sherpa = useSherpaStore();
    sherpa.init();

    window.dispatchEvent(
      new CustomEvent("sherpa-ws-message", {
        detail: {
          type: SHERPA_WS_EVENT.status,
          payload: {
            connected: true,
            stage: "analyzing",
          },
        },
      })
    );

    expect(sherpa.state).toBe("syncing");

    sherpa.dispose();
  });
});
