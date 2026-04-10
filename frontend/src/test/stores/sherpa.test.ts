import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { reactive } from "vue";
import { dispatchSherpaEvent } from "@/lib/sherpaEvents";

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
  fileInfo: null as Record<string, unknown> | null,
});

vi.mock("@/stores/llm", () => ({
  useLlmStore: () => mockLlmStore,
}));

vi.mock("@/stores/workflow", () => ({
  useWorkflowStore: () => mockWorkflowStore,
}));

vi.mock("@/stores/data", () => ({
  useDataStore: () => mockDataStore,
  summarizeDatasetForSherpaContext: (datasetInfo: Record<string, unknown> | null) => {
    if (!datasetInfo) {
      return null;
    }
    const metadata =
      datasetInfo.metadata && typeof datasetInfo.metadata === "object"
        ? (datasetInfo.metadata as Record<string, unknown>)
        : {};
    const xAxis =
      datasetInfo.x_axis && typeof datasetInfo.x_axis === "object"
        ? (datasetInfo.x_axis as Record<string, unknown>)
        : {};
    const xData = Array.isArray(xAxis.data)
      ? xAxis.data.filter((value): value is number => typeof value === "number")
      : [];
    return {
      label: typeof datasetInfo.label === "string" ? datasetInfo.label : null,
      source: typeof datasetInfo.source === "string" ? datasetInfo.source : null,
      description:
        typeof datasetInfo.description === "string" ? datasetInfo.description : null,
      n_samples: typeof datasetInfo.n_samples === "number" ? datasetInfo.n_samples : null,
      n_features: typeof datasetInfo.n_features === "number" ? datasetInfo.n_features : null,
      is_time_series:
        typeof datasetInfo.is_time_series === "boolean"
          ? datasetInfo.is_time_series
          : typeof metadata.is_time_series === "boolean"
            ? metadata.is_time_series
            : null,
      is_spectra:
        typeof datasetInfo.is_spectra === "boolean"
          ? datasetInfo.is_spectra
          : typeof metadata.is_spectra === "boolean"
            ? metadata.is_spectra
            : null,
      technique:
        typeof datasetInfo.technique === "string"
          ? datasetInfo.technique
          : typeof metadata.spectral_technique === "string"
            ? metadata.spectral_technique
            : null,
      x_title:
        typeof datasetInfo.x_title === "string"
          ? datasetInfo.x_title
          : typeof xAxis.title === "string"
            ? xAxis.title
            : null,
      x_units:
        typeof datasetInfo.x_units === "string"
          ? datasetInfo.x_units
          : typeof xAxis.units === "string"
            ? xAxis.units
            : typeof metadata.x_units === "string"
              ? metadata.x_units
              : null,
      x_min: xData.length > 0 ? xData[0] : null,
      x_max: xData.length > 0 ? xData[xData.length - 1] : null,
      data_quantity:
        typeof datasetInfo.data_quantity === "string"
          ? datasetInfo.data_quantity
          : typeof metadata.data_quantity === "string"
            ? metadata.data_quantity
            : null,
      value_units:
        typeof metadata.value_units === "string" ? metadata.value_units : null,
      metadata_summary: {
        data_type: typeof metadata.data_type === "string" ? metadata.data_type : null,
        spectral_technique:
          typeof metadata.spectral_technique === "string"
            ? metadata.spectral_technique
            : null,
        file_name: null,
        has_wavenumber_axis: xData.length > 0,
      },
    };
  },
}));

import { SHERPA_WS_EVENT } from "@/lib/sherpaWs";
import { useNotificationStore } from "@/stores/notification";
import { useSherpaStore } from "@/stores/sherpa";

const lastRequestId = (): string | null => {
  if (!mockWs.send.mock.calls.length) {
    return null;
  }
  const payload = JSON.parse(mockWs.send.mock.calls.at(-1)?.[0] as string);
  return payload?.payload?.request_id ?? null;
};

const emitSherpa = (payload: Record<string, unknown>) => {
  dispatchSherpaEvent(payload as { type: string; request_id?: string | null });
};

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
    mockDataStore.fileInfo = null;
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
      "Sherpa request sent. Waiting for server acknowledgement."
    );
  });

  it("does not show the delayed preparing notice after chat streaming starts", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();
    sherpa.init();

    await sherpa.sendMessage("tell me about PCA");
    emitSherpa({ type: SHERPA_WS_EVENT.chatStart, request_id: lastRequestId() });
    await vi.advanceTimersByTimeAsync(4000);

    expect(sherpa.messages.at(-1)?.role).toBe("assistant");
    expect(
      notifications.notifications.some(
        (notification) => notification.message === "Sherpa Advisor is preparing a response."
      )
    ).toBe(false);

    sherpa.dispose();
  });

  it("resets the chat timeout when Sherpa activity continues", async () => {
    const sherpa = useSherpaStore();
    sherpa.init();

    await sherpa.sendMessage("Does it make sense to use MCR-ALS upon non-time-series spectra data?");
    emitSherpa({ type: SHERPA_WS_EVENT.chatStart, request_id: lastRequestId() });

    await vi.advanceTimersByTimeAsync(119_000);
    emitSherpa({
      type: SHERPA_WS_EVENT.chatChunk,
      request_id: lastRequestId(),
      chunk: "Yes, it can.",
    });

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
    // The scientific-keys allowlist promotes 'accuracy' from metadata
    // to the top level so the server-side context builder can summarize it.
    // 'model_name' stays only under metadata (not a scientific key).
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
        accuracy: 0.97,
        metadata: {
          accuracy: 0.97,
          model_name: "breast-cancer-pls",
        },
      },
    });
  });

  it("falls back to inspected file metadata for Sherpa dataset context", async () => {
    const sherpa = useSherpaStore();
    mockWorkflowStore.nodes = [
      {
        id: "data_1",
        type: "data.source",
        x: 0,
        y: 0,
        params: {},
        executionState: { output_shape: [120, 2048], status: "completed" },
      },
    ];
    mockDataStore.fileInfo = {
      n_samples: 120,
      n_features: 2048,
      x_axis: {
        data: [4000, 3998, 3996],
        title: "Wavenumber",
        units: "cm^-1",
      },
      metadata: {
        spectral_technique: "FTIR",
        is_spectra: true,
        data_quantity: "Absorbance",
        value_units: "AU",
      },
    };

    await sherpa.sendMessage("Explain the PCA result");

    const payload = JSON.parse(mockWs.send.mock.calls[0][0] as string);
    expect(payload.payload.workflow_context.dataset_context).toEqual({
      label: null,
      source: null,
      description: null,
      n_samples: 120,
      n_features: 2048,
      is_time_series: null,
      is_spectra: true,
      technique: "FTIR",
      x_title: "Wavenumber",
      x_units: "cm^-1",
      x_min: 4000,
      x_max: 3996,
      data_quantity: "Absorbance",
      value_units: "AU",
      metadata_summary: {
        data_type: null,
        spectral_technique: "FTIR",
        file_name: null,
        has_wavenumber_axis: true,
      },
    });
  });

  it("completes a Sherpa agentic round trip without leaving the chat in a timeout state", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();
    sherpa.init();

    await sherpa.sendMessage("Explain the test result", true);
    const requestId = lastRequestId();

    emitSherpa({ type: SHERPA_WS_EVENT.chatStart, request_id: requestId });
    emitSherpa({
      type: SHERPA_WS_EVENT.toolStart,
      request_id: requestId,
      tool_name: "describe_node",
      timing: {
        elapsed_ms: 4200,
        since_last_event_ms: 4200,
      },
    });
    emitSherpa({
      type: SHERPA_WS_EVENT.toolResult,
      request_id: requestId,
      tool_name: "describe_node",
      summary: "Node details loaded",
      timing: {
        elapsed_ms: 5100,
        since_last_event_ms: 900,
      },
    });
    emitSherpa({
      type: SHERPA_WS_EVENT.chatChunk,
      request_id: requestId,
      chunk: "The model accuracy is 97%.",
      timing: {
        elapsed_ms: 5600,
        since_last_event_ms: 500,
      },
    });
    emitSherpa({
      type: SHERPA_WS_EVENT.chatDone,
      request_id: requestId,
      timing: {
        elapsed_ms: 6200,
        since_last_event_ms: 600,
      },
    });

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
    expect(
      notifications.notifications.some((notification) =>
        notification.message.includes("Sherpa tool started")
        && notification.message.includes("describe_node")
        && notification.message.includes("server 4.2s, +4.2s")
      )
    ).toBe(true);
    expect(
      notifications.notifications.some((notification) =>
        notification.message.includes("Sherpa response received")
        && notification.message.includes("The model accuracy is 97%.")
        && notification.message.includes("server 6.2s, +0.6s")
      )
    ).toBe(true);

    sherpa.dispose();
  });

  it("logs the last visible Sherpa activity when chat times out", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();
    sherpa.init();

    await sherpa.sendMessage("Why is this taking so long?", true);
    const requestId = lastRequestId();
    emitSherpa({ type: SHERPA_WS_EVENT.chatStart, request_id: requestId });
    emitSherpa({
      type: SHERPA_WS_EVENT.toolStart,
      request_id: requestId,
      tool_name: "describe_node",
    });

    await vi.advanceTimersByTimeAsync(120_000);

    expect(sherpa.state).toBe("idle");
    expect(notifications.notifications[0]?.message).toContain(
      "Sherpa Advisor timed out while waiting for tool: describe_node"
    );

    sherpa.dispose();
  });

  it("reports a timeout before server acknowledgement when no chat start arrives", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();

    await sherpa.sendMessage("Explain my PCA result");
    await vi.advanceTimersByTimeAsync(120_000);

    expect(sherpa.state).toBe("idle");
    expect(notifications.notifications[0]?.message).toContain(
      "Sherpa Advisor timed out before the server acknowledged the request."
    );
  });

  it("treats an authorizing status event as a server acknowledgement", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();
    sherpa.init();

    await sherpa.sendMessage("Explain my PCA result");
    emitSherpa({
      type: SHERPA_WS_EVENT.status,
      request_id: lastRequestId(),
      payload: {
        connected: true,
        stage: "authorizing",
      },
      timing: {
        elapsed_ms: 1200,
        since_last_event_ms: 1200,
      },
    });

    await vi.advanceTimersByTimeAsync(120_000);

    expect(sherpa.state).toBe("idle");
    expect(
      notifications.notifications.some((notification) =>
        notification.message.includes("Sherpa server acknowledged the request.")
        && notification.message.includes("server 1.2s, +1.2s")
      )
    ).toBe(true);
    expect(notifications.notifications[0]?.message).toContain(
      "Sherpa Advisor timed out. Last activity: Sherpa server acknowledged the request."
    );

    sherpa.dispose();
  });

  it("surfaces demo Sherpa limit errors even when upgrade_url is empty", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();
    await sherpa.syncWorkflow();
    const requestId = lastRequestId();

    emitSherpa({
      type: SHERPA_WS_EVENT.error,
      request_id: requestId,
      limit_type: "sherpa",
      message: "Demo Sherpa interaction limit reached (200 interactions per session)",
      upgrade_url: "",
      remaining: 0,
      session_expiry_hours: 24,
    });

    expect(sherpa.lastSyncError).toBe(
      "Demo Sherpa interaction limit reached (200 interactions per session)"
    );
    expect(sherpa.messages.at(-1)?.content).toBe(
      "Demo Sherpa interaction limit reached (200 interactions per session)\nRemaining: 0\nUsage resets after 24 hours of inactivity."
    );
    expect(notifications.notifications[0]?.message).toBe(
      "Demo Sherpa interaction limit reached (200 interactions per session) Remaining: 0 Usage resets after 24 hours of inactivity."
    );
    expect(notifications.notifications[0]?.detail).toBe(
      "Remaining: 0\nUsage resets after 24 hours of inactivity."
    );
  });

  it("handles Sherpa decision acknowledgements explicitly", () => {
    const sherpa = useSherpaStore();
    sherpa.init();

    emitSherpa({
      type: SHERPA_WS_EVENT.decisionAck,
      payload: {
        delivered: true,
        suggestion_id: "rec-1",
      },
    });

    expect(sherpa.messages.at(-1)?.content).toBe(
      "Sherpa Advisor recorded your decision."
    );

    sherpa.dispose();
  });

  it("accepts positive Sherpa status events as active sync state", async () => {
    const sherpa = useSherpaStore();
    await sherpa.syncWorkflow();
    emitSherpa({
      type: SHERPA_WS_EVENT.status,
      request_id: lastRequestId(),
      payload: {
        connected: true,
        stage: "analyzing",
      },
    });

    expect(sherpa.state).toBe("syncing");
  });

  it("creates an assistant bubble if a Sherpa chunk arrives before chatStart", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();
    sherpa.init();

    await sherpa.sendMessage("Explain PCA");
    const payload = JSON.parse(mockWs.send.mock.calls[0][0] as string);

    emitSherpa({
      type: SHERPA_WS_EVENT.chatChunk,
      request_id: payload.payload.request_id,
      chunk: "PC1 explains most of the variance.",
    });

    expect(sherpa.messages.at(-1)?.role).toBe("assistant");
    expect(sherpa.messages.at(-1)?.content).toBe("PC1 explains most of the variance.");
    expect(
      notifications.notifications.some((notification) =>
        notification.message.includes("Sherpa recovered a missing response start")
      )
    ).toBe(true);

    sherpa.dispose();
  });

  it("adds a chat-visible system message when a Sherpa tool fails", async () => {
    const sherpa = useSherpaStore();
    sherpa.init();

    await sherpa.sendMessage("Explain this workflow", true);
    const payload = JSON.parse(mockWs.send.mock.calls[0][0] as string);

    emitSherpa({
      type: SHERPA_WS_EVENT.toolResult,
      request_id: payload.payload.request_id,
      tool_name: "describe_node",
      success: false,
      summary: "Node metadata lookup timed out.",
      error_category: "timeout",
    });

    expect(sherpa.messages.at(-1)?.content).toContain(
      "Sherpa tool failed (timeout): describe_node."
    );

    sherpa.dispose();
  });

  it("shows a system message when Sherpa reaches the tool round limit", async () => {
    const sherpa = useSherpaStore();
    sherpa.init();

    await sherpa.sendMessage("Explain this workflow", true);
    const payload = JSON.parse(mockWs.send.mock.calls[0][0] as string);

    emitSherpa({
      type: SHERPA_WS_EVENT.status,
      request_id: payload.payload.request_id,
      payload: {
        connected: true,
        stage: "tool_round_limit",
        detail: "Sherpa exhausted 2 tool rounds and is making a final response without more tool calls.",
      },
    });

    expect(sherpa.messages.at(-1)?.content).toContain(
      "Sherpa exhausted 2 tool rounds"
    );

    sherpa.dispose();
  });

  it("surfaces Sherpa sync timeouts in notifications", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();

    await sherpa.syncWorkflow();
    await vi.advanceTimersByTimeAsync(180_000);

    expect(sherpa.state).toBe("idle");
    expect(notifications.notifications[0]?.message).toBe(
      "Sherpa sync timed out. The service may be unavailable."
    );
  });

  it("does not send duplicate sync requests while a sync is already running", async () => {
    const sherpa = useSherpaStore();

    await sherpa.syncWorkflow();
    await sherpa.syncWorkflow();

    expect(mockWs.send).toHaveBeenCalledTimes(1);
  });

  it("fails closed on malformed Sherpa events instead of leaving the store stuck", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();
    await sherpa.sendMessage("Malformed event test");

    emitSherpa({
      type: SHERPA_WS_EVENT.chatChunk,
      request_id: lastRequestId(),
      chunk: null,
    });

    expect(sherpa.state).toBe("error");
    expect(sherpa.messages.at(-1)?.content).toContain(
      "Sherpa event handling failed: Sherpa chat chunk payload was missing text."
    );
    expect(notifications.notifications[0]?.message).toContain(
      "Sherpa event handling failed: Sherpa chat chunk payload was missing text."
    );
  });

  // ----------------------------------------------------------------------
  // Regression guards for the workflow context payload.
  //
  // These tests lock in the contract that buildSyncPayload sends ENOUGH
  // information for the server-side context builder to answer user
  // questions without hallucinating. Each assertion corresponds to a
  // specific real bug we hit during the Sherpa hardening work.
  // ----------------------------------------------------------------------

  const getLastSyncPayload = (): Record<string, unknown> | null => {
    const lastCall = mockWs.send.mock.calls.at(-1)?.[0] as string | undefined;
    if (!lastCall) return null;
    const parsed = JSON.parse(lastCall);
    return (parsed?.payload?.workflow_context as Record<string, unknown>) ?? null;
  };

  it("sends effective node parameters (defaults merged with overrides)", async () => {
    // Simulate a node with a user override that leaves another param unset.
    mockWorkflowStore.getNodeMetadata.mockImplementation((nodeType: string) => {
      if (nodeType === "selection.sample_partition") {
        return {
          label: "Sample Partition",
          description: "Split data",
          output_type: "Partition",
          parameters: [
            { name: "method", label: "Method", description: "Split method", default: "stratified" },
            { name: "test_size", label: "Test Size", description: "Fraction", default: 0.2 },
            { name: "random_seed", label: "Seed", description: "RNG seed", default: 42 },
          ],
        };
      }
      return null;
    });
    mockWorkflowStore.nodes = [
      {
        id: "partition_1",
        type: "selection.sample_partition",
        params: { test_size: 0.25 }, // user override; method and random_seed not set
        executionState: { status: "completed" },
      },
    ];

    const sherpa = useSherpaStore();
    await sherpa.sendMessage("what is the partition config");

    const ctx = getLastSyncPayload();
    expect(ctx).toBeTruthy();
    const nodes = ctx?.nodes as Array<Record<string, unknown>>;
    const partitionNode = nodes.find((n) => n.node_id === "partition_1");
    expect(partitionNode).toBeDefined();
    const params = partitionNode?.parameters as Record<string, unknown>;
    // User override wins
    expect(params.test_size).toBe(0.25);
    // Defaults filled in so the server-side context builder shows all params
    expect(params.method).toBe("stratified");
    expect(params.random_seed).toBe(42);
  });

  it("preserves scientific scalars and salient_features in results_summary", async () => {
    mockWorkflowStore.nodes = [
      {
        id: "plsda_1",
        type: "classification.plsda",
        params: { n_components: 2 },
        executionState: { status: "completed", output_shape: [105, 2] },
      },
    ];
    mockWorkflowStore.lastExecutionResults = {
      plsda_1: {
        type: "PLS_DA",
        n_samples: 105,
        n_features: 2,
        accuracy: 0.98,
        confusion_matrix: [
          [35, 0, 0],
          [0, 33, 2],
          [0, 1, 34],
        ],
        salient_features: {
          method: "vip",
          features: [{ position: 1720.0, importance: 2.1 }],
          x_units: "cm-1",
        },
        metadata: {
          n_components: 2,
          deep_nested: { should_be_dropped: true }, // nested dicts in metadata are NOT preserved
        },
      },
    };

    const sherpa = useSherpaStore();
    await sherpa.sendMessage("tell me about results");

    const ctx = getLastSyncPayload();
    const summary = (ctx?.results_summary as Record<string, Record<string, unknown>>)?.plsda_1;
    expect(summary).toBeTruthy();

    // Scientific scalars preserved from the top level
    expect(summary.type).toBe("PLS_DA");
    expect(summary.n_samples).toBe(105);
    expect(summary.accuracy).toBe(0.98);
    // Arrays (confusion matrix) preserved
    expect(summary.confusion_matrix).toEqual([
      [35, 0, 0],
      [0, 33, 2],
      [0, 1, 34],
    ]);
    // Salient features: the chemistry-aware path MUST round-trip.
    // Before the fix this was silently dropped and the server's
    // extract_salient_features_context() was dead code.
    expect(summary.salient_features).toBeTruthy();
    expect((summary.salient_features as Record<string, unknown>).method).toBe("vip");
    // Nested metadata dicts are NOT preserved (the filter keeps primitives).
    const metadata = summary.metadata as Record<string, unknown>;
    expect(metadata.n_components).toBe(2);
    expect(metadata.deep_nested).toBeUndefined();
  });

  it("treats persisted results as completed when executionState is still pending", async () => {
    mockWorkflowStore.getNodeMetadata.mockImplementation((nodeType: string) => {
      if (nodeType === "classification.plsda") {
        return {
          label: "PLS-DA",
          description: "Classification model",
          output_type: "PLSModel",
          parameters: [
            { name: "n_components", label: "Components", description: "Latent variables", default: 2 },
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
    });
    mockWorkflowStore.nodes = [
      {
        id: "data_1",
        type: "data.source",
        params: {},
        executionState: { status: "completed", output_shape: [150, 4], output_type: "SherpaDataset" },
      },
      {
        id: "model_1",
        type: "classification.plsda",
        params: { n_components: 2 },
        executionState: { status: "pending" },
      },
    ];
    mockWorkflowStore.lastExecutionResults = {
      data_1: {
        type: "SherpaDataset",
        n_samples: 150,
        n_features: 4,
      },
      model_1: {
        type: "PLS_DA",
        shape: [150, 2],
      },
    };

    const sherpa = useSherpaStore();
    await sherpa.sendMessage("tell me all nodes in this workflow");

    const ctx = getLastSyncPayload();
    const nodes = ctx?.nodes as Array<Record<string, unknown>>;
    const modelNode = nodes.find((node) => node.node_id === "model_1");
    expect(modelNode).toBeTruthy();
    expect(modelNode?.execution_status).toBe("completed");
    expect(modelNode?.result_shape).toEqual([150, 2]);
    expect(modelNode?.output_type).toBe("PLS_DA");
  });
});
