import { SHERPA_RESPONSE_TIMEOUT_MS, SHERPA_SYNC_TIMEOUT_MS } from "@/lib/sherpaTimeouts";
import { installAdvisorTransport } from "@/lib/advisorTransport";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { reactive, ref } from "vue";
import { dispatchSherpaEvent } from "@/lib/sherpaEvents";

const mockApi = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

const mockWs = {
  readyState: WebSocket.OPEN,
  send: vi.fn(),
};

const mockAppConfig = ref<Record<string, unknown>>({});
const mockTransport = { prepareContext: vi.fn(), loadConversation: vi.fn(), deleteConversation: vi.fn(), confirmProposal: vi.fn() };
let disposeTransport: (() => void) | undefined;
const mockAppMode = ref("enterprise");
const mockSiteProfile = ref("demo");

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({ appMode: mockAppMode, siteProfile: mockSiteProfile, appConfig: mockAppConfig }),
}));

const mockLlmStore = reactive({
  wsRef: mockWs as unknown as WebSocket,
  connect: vi.fn<() => Promise<void>>(),
  connectionStatus: "connected" as "disconnected" | "connecting" | "connected",
});

const mockWorkflowStore = reactive({
  workflowId: 5,
  executionEvidenceScope: "live_full", restoredRunId: 5,
  isWorkflowStale: false,
  lastExecutionParams: {} as Record<string, Record<string, unknown>>,
  workflowName: "Test workflow",
  workflowDescription: "Test description",
  currentTemplateId: "template-1",
  nodes: [] as Array<Record<string, unknown>>,
  edges: [] as Array<Record<string, unknown>>,
  lastExecutionResults: null as Record<string, Record<string, unknown>> | null,
  lastExecutionDiagnostics: {} as Record<string, Record<string, unknown>>,
  lastExecutionPresentations: {} as Record<string, unknown>,
  executeStoredWorkflow: vi.fn(),
  loadWorkflow: vi.fn(async () => undefined),
  hasUnsavedChanges: false,
  getNodeMetadata: vi.fn((nodeType: string) => {
    if (nodeType === "model.fitted_pls") {
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
    if (nodeType === "data.file_load") {
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
  captureAdvisorDatasetContext: vi.fn<() => Record<string, unknown> | null>(() => null),
  catalogDatasetInfo: null as Record<string, unknown> | null,
  fileInfo: null as Record<string, unknown> | null,
});

const mockAdvisorStore = reactive({
  activeChannelId: 10 as number | null,
  activeNodeId: null as number | null,
  get activeChannel() {
    return (
      mockAdvisorStore.channels.find((item) => item.id === mockAdvisorStore.activeChannelId) ?? null
    );
  },
  channels: [
    {
      id: 10,
      project_id: 42,
      workflow_id: 20,
      channel_type: "sheet",
      title: "SIMCA",
      color: null,
      conversation_id: "conv-parent",
    },
    {
      id: 40,
      project_id: 42,
      workflow_id: 30,
      channel_type: "sheet",
      title: "AI PLS-DA",
      color: null,
      conversation_id: "conv-ai",
    },
  ] as Array<Record<string, unknown>>,
  loadAdvisorChannels: vi.fn(async () => mockAdvisorStore.channels),
  updateChannel: vi.fn(async (channelId: number, payload: Record<string, unknown>) => {
    const channel = mockAdvisorStore.channels.find((item) => item.id === channelId);
    if (channel) {
      Object.assign(channel, payload);
    }
    return channel ?? null;
  }),
});

const mockWorkbookStore = reactive({
  projectId: 42 as number | null,
  refreshSheets: vi.fn(async () => undefined),
  selectWorkflowSheet: vi.fn(async () => undefined),
});

const mockWorkflowBuilderConfigStore = reactive({
  autoExecute: false,
});

vi.mock("@/stores/llm", () => ({
  useLlmStore: () => mockLlmStore,
}));

vi.mock("@/api/client", () => ({
  default: mockApi,
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
      dataset_id: typeof datasetInfo.dataset_id === "string" ? datasetInfo.dataset_id : null,
      label: typeof datasetInfo.label === "string" ? datasetInfo.label : null,
      source: typeof datasetInfo.source === "string" ? datasetInfo.source : null,
      dataset_name: typeof datasetInfo.name === "string" ? datasetInfo.name : null,
      description: typeof datasetInfo.description === "string" ? datasetInfo.description : null,
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
      value_units: typeof metadata.value_units === "string" ? metadata.value_units : null,
      feature_names: Array.isArray(datasetInfo.feature_names)
        ? (datasetInfo.feature_names as string[])
        : null,
      target_names: Array.isArray(datasetInfo.target_names)
        ? (datasetInfo.target_names as string[])
        : null,
      metadata_summary: {
        data_type: typeof metadata.data_type === "string" ? metadata.data_type : null,
        spectral_technique:
          typeof metadata.spectral_technique === "string" ? metadata.spectral_technique : null,
        file_name: null,
        has_wavenumber_axis: xData.length > 0,
      },
    };
  },
}));

vi.mock("@/stores/advisor", () => ({
  useAdvisorStore: () => mockAdvisorStore,
}));

vi.mock("@/stores/workbook", () => ({
  useWorkbookStore: () => mockWorkbookStore,
}));

vi.mock("@/stores/workflowBuilderConfig", () => ({
  useWorkflowBuilderConfigStore: () => mockWorkflowBuilderConfigStore,
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
  disposeTransport?.();
  mockAppConfig.value = {};
  disposeTransport = installAdvisorTransport(mockTransport);
    vi.useFakeTimers();
    setActivePinia(createPinia());
    mockWs.send.mockReset();
    mockApi.get.mockReset();
    mockApi.post.mockReset();
    mockApi.put.mockReset();
    mockApi.delete.mockReset();
    mockLlmStore.connect.mockReset();
    mockLlmStore.connect.mockResolvedValue(undefined);
    mockLlmStore.connectionStatus = "connected";
    mockAppMode.value = "enterprise";
    mockSiteProfile.value = "demo";
    mockWorkflowStore.workflowId = 5;
    mockWorkflowStore.workflowName = "Test workflow";
    mockWorkflowStore.workflowDescription = "Test description";
    mockWorkflowStore.currentTemplateId = "template-1";
    mockWorkflowStore.nodes = [];
    mockWorkflowStore.edges = [];
    mockWorkflowStore.lastExecutionResults = null;
    mockWorkflowStore.lastExecutionDiagnostics = {};
    mockWorkflowStore.executeStoredWorkflow.mockReset();
    mockWorkflowStore.getNodeMetadata.mockClear();
    mockDataStore.catalogDatasetInfo = null;
    mockDataStore.fileInfo = null;
    mockDataStore.captureAdvisorDatasetContext.mockReset().mockReturnValue(null);
    mockAdvisorStore.activeChannelId = 10;
    mockAdvisorStore.channels = [
      {
        id: 10,
        project_id: 42,
        workflow_id: 20,
        channel_type: "sheet",
        title: "SIMCA",
        color: null,
        conversation_id: "conv-parent",
      },
      {
        id: 40,
        project_id: 42,
        workflow_id: 30,
        channel_type: "sheet",
        title: "AI PLS-DA",
        color: null,
        conversation_id: "conv-ai",
      },
    ];
    mockAdvisorStore.loadAdvisorChannels.mockClear();
    mockAdvisorStore.updateChannel.mockClear();
    mockWorkbookStore.projectId = 42;
    mockWorkbookStore.refreshSheets.mockClear();
    mockWorkbookStore.selectWorkflowSheet.mockClear();
    mockWorkflowBuilderConfigStore.autoExecute = false;
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("clears Pro chat at a project boundary and ignores a pending old-project list", async () => {
    mockSiteProfile.value = "pro";
    const { useProjectStore } = await import("@/stores/project");
    const { runProjectScopeResets } = await import("@/stores/projectScopeRegistry");
    const projects = useProjectStore();
    projects.currentProjectId = 42;
    const store = useSherpaStore();
    store.currentConversationId = "project-a";
    store.messages.push({ id: "a-result", role: "assistant", content: "Project A private result" });
    let resolveList!: (value: unknown) => void;
    mockApi.get.mockImplementationOnce(() => new Promise((resolve) => { resolveList = resolve; }));
    const pending = store.refreshConversations(42);
    runProjectScopeResets();
    projects.currentProjectId = 43;
    expect(store.currentConversationId).toBeNull();
    expect(store.messages.some((m) => m.content.includes("Project A private result"))).toBe(false);
    resolveList({ data: [{ id: "project-a", title: "Old project" }] });
    await pending;
    expect(store.conversations).toEqual([]);
    store.dispose();
  });

  it("uses the shared request path with a server-resolved worksheet reference on Pro", async () => {
    mockSiteProfile.value = "pro";
    const { useProjectStore } = await import("@/stores/project");
    useProjectStore().currentProjectId = 42;
    const store = useSherpaStore();
    await store.sendMessage("Explain scaling", true);
    const sent = JSON.parse(mockWs.send.mock.calls.at(-1)![0]);
    expect(sent.action).toBe("sherpa_chat_with_tools");
    expect(sent.payload.workflow_context.workflow_id).toBe(5);
    expect(sent.payload.advisor_node_id).toBeNull();
    expect(sent.payload.project_id).toBe(useProjectStore().currentProjectId);
    dispatchSherpaEvent({ type: "sherpa_chat_start", request_id: sent.payload.request_id });
    dispatchSherpaEvent({ type: "sherpa_chat_chunk", request_id: sent.payload.request_id, chunk: "Qualified response" });
    dispatchSherpaEvent({ type: "sherpa_chat_done", request_id: sent.payload.request_id, conversation_id: "qualified-chat" });
    expect(store.messages.some((message) => message.content === "Qualified response")).toBe(true);
    store.dispose();
  });

  it("captures the current dataset masks at chat-send time", async () => {
    const sherpa = useSherpaStore();
    const snapshot = {
      schema: "spectra-my-dataset-advisor/1",
      datasets: [{ experiment_id: 4, row_mask: [true, false] }],
    };
    mockDataStore.captureAdvisorDatasetContext.mockReturnValue(snapshot);
    await sherpa.sendMessage("Explain my current selection");
    const message = JSON.parse(mockWs.send.mock.calls[0][0] as string);
    expect(message.payload.workflow_context.dataset_context.my_dataset).toEqual(snapshot);
    expect(mockDataStore.captureAdvisorDatasetContext).toHaveBeenCalledTimes(1);
  });

  it("shows a delayed status notification when Sherpa chat is still preparing", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();

    await sherpa.sendMessage("tell me about PCA");
    await vi.advanceTimersByTimeAsync(4000);

    expect(sherpa.state).toBe("chatting");
    expect(notifications.notifications[0]?.title).toBe("Sherpa Advisor");
    expect(notifications.notifications[0]?.message).toBe(
      "Sherpa request sent. Waiting for server acknowledgement.",
    );
  });

  it("seeds a welcome checklist the first time Sherpa initializes", () => {
    const sherpa = useSherpaStore();

    sherpa.init();

    expect(sherpa.messages).toHaveLength(1);
    const welcome = sherpa.messages[0];
    expect(welcome?.role).toBe("assistant");
    // Main-tab orientation: Dashboard → Project → Data → Workflows → Runs → Deploy → Report.
    expect(welcome?.content).toContain("Welcome to Sherpa Advisor");
    expect(welcome?.content).toMatch(/1\.\s+\*\*Dashboard\*\*/);
    expect(welcome?.content).toMatch(/2\.\s+\*\*Project\*\*/);
    expect(welcome?.content).toMatch(/3\.\s+\*\*Data\*\*/);
    expect(welcome?.content).toMatch(/4\.\s+\*\*Workflows\*\*/);
    expect(welcome?.content).toMatch(/5\.\s+\*\*Runs\*\*/);
    expect(welcome?.content).toMatch(/6\.\s+\*\*Deploy\*\*/);
    expect(welcome?.content).toMatch(/7\.\s+\*\*Report\*\*/);
    expect(welcome?.content).toContain("Use **Settings**");

    sherpa.dispose();
  });

  it("restores the welcome checklist when starting a new Sherpa conversation", () => {
    const sherpa = useSherpaStore();

    sherpa.init();
    sherpa.startNewConversation();

    expect(sherpa.messages).toHaveLength(1);
    expect(sherpa.messages[0]?.role).toBe("assistant");
    expect(sherpa.messages[0]?.content).toContain("Welcome to Sherpa Advisor");
    expect(sherpa.messages[0]?.content).toMatch(/1\.\s+\*\*Dashboard\*\*/);
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
        (notification) => notification.message === "Sherpa Advisor is preparing a response.",
      ),
    ).toBe(false);

    sherpa.dispose();
  });

  it("clears transient sync state when the Sherpa panel unmounts", async () => {
    const sherpa = useSherpaStore();
    sherpa.init();

    await sherpa.syncWorkflow();
    expect(sherpa.isSyncing).toBe(true);

    sherpa.dispose();

    expect(sherpa.isSyncing).toBe(false);
    expect(sherpa.isChatting).toBe(false);
    expect(sherpa.syncState).toBe("idle");
    expect(sherpa.chatState).toBe("idle");
  });

  it("keeps the absolute one-minute deadline despite Sherpa activity", async () => {
    const sherpa = useSherpaStore();
    sherpa.init();

    await sherpa.sendMessage(
      "Does it make sense to use MCR-ALS upon non-time-series spectra data?",
    );
    emitSherpa({ type: SHERPA_WS_EVENT.chatStart, request_id: lastRequestId() });

    await vi.advanceTimersByTimeAsync(SHERPA_RESPONSE_TIMEOUT_MS - 1_000);
    emitSherpa({
      type: SHERPA_WS_EVENT.chatChunk,
      request_id: lastRequestId(),
      chunk: "Yes, it can.",
    });

    await vi.advanceTimersByTimeAsync(500);
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
      }),
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
    expect(payload.action).toBe("sherpa_chat_with_tools");
    expect(payload.payload.workflow_id).toBeNull();
    expect(payload.payload.workflow_context.workflow_id).toBeNull();
  });

  it("sends the active Sherpa conversation_id and does not replay frontend history", async () => {
    const { useProjectStore } = await import("@/stores/project");
    const projectStore = useProjectStore();
    const sherpa = useSherpaStore();
    projectStore.currentProjectId = 101;
    sherpa.currentConversationId = "conv-123";

    await sherpa.sendMessage("continue this thread");

    const payload = JSON.parse(mockWs.send.mock.calls[0][0] as string);
    expect(payload.payload.conversation_id).toBe("conv-123");
    expect(payload.payload.project_id).toBe(101);
    expect(payload.payload.history).toBeUndefined();
  });

  it("uses only the explicitly installed context transport for bounded disclosure", async () => {
    mockAppMode.value = "test_product";
    mockAppConfig.value = { advisorContextPolicy: "receipt" };
    const context = { disclosure_receipt: { public_id: "receipt-1" }, workflow_descriptor: { node_count: 1 } };
    mockTransport.prepareContext.mockResolvedValueOnce(context);
    const sherpa = useSherpaStore();
    await sherpa.sendMessage("Should I use PCA?");
    expect(mockTransport.prepareContext).toHaveBeenCalledWith(5);
    const payload = JSON.parse(mockWs.send.mock.calls[0][0] as string);
    expect(payload.payload.workflow_context).toEqual(context);
    expect(JSON.stringify(payload.payload.workflow_context)).not.toContain("results_summary");
  });

  it("never falls back to broad context when product disclosure is refused", async () => {
    mockAppMode.value = "test_product";
    mockAppConfig.value = { advisorContextPolicy: "receipt" };
    mockTransport.prepareContext.mockRejectedValueOnce(new Error("Disclosure not confirmed"));
    const sherpa = useSherpaStore();
    await sherpa.sendMessage("Should I use PCA?");
    expect(mockWs.send).not.toHaveBeenCalled();
    expect(sherpa.messages.at(-1)?.content).toContain("not confirmed");
  });

  it.each([false, true])("opens a proposed draft without browser execution (autoExecute=%s)", async (preference) => {
    mockWorkflowBuilderConfigStore.autoExecute = preference;
    const sherpa = useSherpaStore();
    await sherpa.sendMessage("Create a PCA workflow", true);
    emitSherpa({
      type: SHERPA_WS_EVENT.workflowProposed,
      request_id: lastRequestId(),
      new_workflow_id: 30,
      suggested_name: "PCA draft",
      conversation_id: "conv-ai",
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(mockWorkbookStore.selectWorkflowSheet).toHaveBeenCalledWith(30);
    expect(mockWorkflowStore.executeStoredWorkflow).not.toHaveBeenCalled();
  });

  it("waits for proposed-sheet navigation before restoring an immediately completed exact run", async () => {
    let finishNavigation!: () => void;
    mockWorkbookStore.selectWorkflowSheet.mockImplementationOnce(async () => {
      await new Promise<void>((resolve) => { finishNavigation = resolve; });
      mockWorkflowStore.workflowId = 30;
    });
    const sherpa = useSherpaStore();
    await sherpa.sendMessage("Create a workflow and run it");
    const requestId = lastRequestId();
    emitSherpa({ type: SHERPA_WS_EVENT.workflowProposed, request_id: requestId,
      new_workflow_id: 30, suggested_name: "Draft", conversation_id: "conv-ai" });
    emitSherpa({ type: SHERPA_WS_EVENT.chatDone, request_id: requestId,
      execution_result: { workflow_id: 30, run_id: 99, status: "completed" } });
    await Promise.resolve();
    await Promise.resolve();
    expect(mockWorkflowStore.loadWorkflow).not.toHaveBeenCalled();
    finishNavigation();
    for (let step = 0; step < 8; step++) await Promise.resolve();
    expect(mockWorkflowStore.loadWorkflow).toHaveBeenCalledWith(30, 99);
    expect(sherpa.messages.some((item) => item.content.includes("empty response"))).toBe(false);
  });

  it("previews a product proposal and applies it only after explicit confirmation", async () => {
    mockAppMode.value = "test_product";
    mockAppConfig.value = { advisorContextPolicy: "receipt" };
    mockTransport.prepareContext.mockResolvedValueOnce({ disclosure_receipt: { public_id: "receipt" } });
    const sherpa = useSherpaStore();
    await sherpa.sendMessage("Create a PCA alternative", true);
    const requestId = lastRequestId();
    const proposal = {
      proposal_id: "00000000-0000-4000-8000-000000000043",
      proposal_digest: "e".repeat(64),
      suggested_name: "PCA alternative",
      human_explanation: "A separate workflow for review.",
      dag_spec: { nodes: [{ id: "pca_1" }], edges: [] },
    };
    emitSherpa({
      type: SHERPA_WS_EVENT.workflowProposalPreview,
      request_id: requestId,
      proposal,
    });

    expect(sherpa.pendingProductProposal).toEqual({ proposal, sourceWorkflowId: 5 });
    expect(mockWorkbookStore.selectWorkflowSheet).not.toHaveBeenCalled();
    expect(mockWorkflowStore.executeStoredWorkflow).not.toHaveBeenCalled();

    mockTransport.confirmProposal.mockResolvedValueOnce(88);
    await sherpa.confirmProductProposal();

    expect(mockTransport.confirmProposal).toHaveBeenCalledWith(5, proposal);
    expect(mockWorkbookStore.refreshSheets).toHaveBeenCalledOnce();
    expect(mockWorkbookStore.selectWorkflowSheet).toHaveBeenCalledWith(88);
    expect(mockWorkflowStore.executeStoredWorkflow).not.toHaveBeenCalled();
    expect(sherpa.pendingProductProposal).toBeNull();
  });

  it("includes execution results in Sherpa workflow context for metric questions", async () => {
    const sherpa = useSherpaStore();
    mockWorkflowStore.nodes = [
      {
        id: "data_1",
        type: "data.file_load",
        x: 0,
        y: 0,
        params: { experiment_id: 42 },
        executionState: { output_shape: [569, 30], status: "completed" },
      },
      {
        id: "pls_1",
        type: "model.fitted_pls",
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

  it("refuses legacy plot claims until an executed contract is available", async () => {
    const sherpa = useSherpaStore();
    mockWorkflowStore.nodes = [
      {
        id: "pca_1",
        type: "model.pca",
        x: 0,
        y: 0,
        params: { n_components: "2" },
        executionState: { status: "completed" },
      },
    ];
    mockWorkflowStore.edges = [];
    mockWorkflowStore.lastExecutionResults = {
      pca_1: {
        default: {
          type: "SherpaDataset",
          data: [
            [-2.68, -0.32],
            [2.39, 0.35],
          ],
          n_samples: 150,
          n_features: 2,
          metadata: {
            type: "PCA",
            isPCA: true,
            pc_labels: ["PC1 (92.5%)", "PC2 (5.3%)"],
            explained_variance_ratio: [0.925, 0.053],
            n_components: 2,
            label_categories: ["setosa", "versicolor", "virginica"],
          },
        },
        loadings: {
          type: "SherpaDataset",
          data: [
            [0.36, -0.08, 0.86, 0.36],
            [0.66, 0.73, -0.18, -0.08],
          ],
          title: "PCA Loadings",
          x_axis: {
            title: "Property",
            units: "",
            data: [0, 1, 2, 3],
            labels: [
              "sepal length (cm)",
              "sepal width (cm)",
              "petal length (cm)",
              "petal width (cm)",
            ],
          },
          metadata: { data_quantity: "PCA loading" },
        },
      },
    };

    await sherpa.sendMessage("explain the plot in the Loadings node", true);

    const payload = JSON.parse(mockWs.send.mock.calls[0][0] as string);
    const nodes = payload.payload.workflow_context.nodes;
    expect(nodes).toHaveLength(1);
    const plotStates = nodes[0].plot_states;
    expect(Array.isArray(plotStates)).toBe(true);

    // Historical results without an execution contract cannot authorize plot claims.
    expect(plotStates).toHaveLength(1);
    expect(plotStates[0].refusal_reason).toMatch(/no presentation contract/);
    expect(plotStates[0].x_axis).toBeNull();
    const presentation = {presentation_id:"saved",label:"Saved responses",kind:"classification_responses",source_ports:["default"],modes:["plot"],description:""};
    mockWorkflowStore.lastExecutionPresentations = {pca_1: {
      schema_version:"spectrasherpa-executed-presentation/1",contract_digest:"a".repeat(64),
      contract:{schema_version:"spectrasherpa-node-presentation/1",default_presentation:"saved",presentations:[presentation]},
      presentations:[{...presentation,content_categories:[]}],
    }};
    sherpa.stopAnalysis();
    await sherpa.sendMessage("explain the saved response plot", true);
    const typed = JSON.parse(mockWs.send.mock.calls.at(-1)![0] as string).payload.workflow_context.nodes[0].plot_states;
    expect(typed[0].presentation_kind).toBe("classification_responses");
    expect(typed[0].contract_digest).toBe("a".repeat(64));
    expect(typed[0].traces).toBeNull();
    mockWorkflowStore.lastExecutionPresentations = {};


  });

  it("falls back to inspected file metadata for Sherpa dataset context", async () => {
    const sherpa = useSherpaStore();
    mockWorkflowStore.nodes = [
      {
        id: "data_1",
        type: "data.file_load",
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
      analysis_context: {
        schema: "spectra-analysis-context/1",
        captured_at: expect.any(String),
        project_id: null,
        sheet: null,
        selection: null,
        authority:
          "The active workflow sheet and current My Dataset selection are the input authority. Treat this context as sheet-scoped and do not reuse settings from another sheet.",
      },
      dataset_id: null,
      label: null,
      source: null,
      dataset_name: null,
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
      feature_names: null,
      target_names: null,
      metadata_summary: {
        data_type: null,
        spectral_technique: "FTIR",
        file_name: null,
        has_wavenumber_axis: true,
      },
    });
  });

  it("includes authoritative dataset identity from executed data-source results", async () => {
    const sherpa = useSherpaStore();
    mockWorkflowStore.nodes = [
      {
        id: "data_1",
        type: "data.file_load",
        x: 0,
        y: 0,
        label: "Load Data",
        params: {
          source: "sklearn",
        },
        executionState: { output_shape: [178, 13], status: "completed" },
      },
    ];
    mockWorkflowStore.lastExecutionResults = {
      data_1: {
        type: "SherpaDataset",
        dataset_id: "wine-dataset-1",
        title: "wine",
        backend: "sklearn",
        n_samples: 178,
        n_features: 13,
        x_axis: {
          labels: ["alcohol", "malic_acid", "ash"],
        },
        target_context: {
          class_names: ["class_0", "class_1", "class_2"],
        },
        extra: {
          "sklearn.dataset_name": "wine",
          "sklearn.target_names": ["class_0", "class_1", "class_2"],
        },
        metadata: {
          feature_names: ["alcohol", "malic_acid", "ash"],
        },
      },
    };

    await sherpa.sendMessage("What are the top features that can be used as predictor?");

    const payload = JSON.parse(mockWs.send.mock.calls[0][0] as string);
    expect(payload.payload.workflow_context.dataset_context).toEqual({
      analysis_context: {
        schema: "spectra-analysis-context/1",
        captured_at: expect.any(String),
        project_id: null,
        sheet: null,
        selection: null,
        authority:
          "The active workflow sheet and current My Dataset selection are the input authority. Treat this context as sheet-scoped and do not reuse settings from another sheet.",
      },
      dataset_id: "wine-dataset-1",
      label: "wine",
      source: "sklearn",
      dataset_name: "wine",
      description: null,
      // n_samples/n_features now come through from the unwrapped dataset
      // identity on the first data.* node that has executed.
      n_samples: 178,
      n_features: 13,
      is_time_series: null,
      is_spectra: null,
      technique: null,
      x_title: null,
      x_units: null,
      x_min: null,
      x_max: null,
      data_quantity: null,
      value_units: null,
      feature_names: ["alcohol", "malic_acid", "ash"],
      target_names: ["class_0", "class_1", "class_2"],
      metadata_summary: null,
    });
    expect(payload.payload.workflow_context.results_summary.data_1).toMatchObject({
      dataset_id: "wine-dataset-1",
      backend: "sklearn",
      dataset_name: "wine",
      feature_names: ["alcohol", "malic_acid", "ash"],
      target_names: ["class_0", "class_1", "class_2"],
    });
  });

  it("unwraps multi-output data-source results (default port)", async () => {
    // Real backend shape: serialize_result wraps SherpaDataset under a
    // ``default`` port key, with sibling ``target`` alongside.  The
    // identity fields (title, backend, extra, metadata, target_context)
    // all live on the ``default`` sub-object, not at the top level.
    // This regression test ensures the frontend unwraps correctly so
    // Sherpa gets the real dataset identity instead of falling back to
    // stale catalog state (which was the bug observed after PR #16's
    // first deploy — Sherpa said "Iris" when the user loaded wine).
    const sherpa = useSherpaStore();
    mockWorkflowStore.nodes = [
      {
        id: "data_1",
        type: "data.file_load",
        x: 0,
        y: 0,
        label: "Load Data",
        params: { source: "sklearn" },
        executionState: { output_shape: [178, 13], status: "completed" },
      },
    ];
    mockWorkflowStore.lastExecutionResults = {
      data_1: {
        // Multi-output wrapper — this is what ``serialize_result`` emits
        // for ``data.file_load`` nodes whose outputs dict has ``{default,
        // target}`` keys.
        default: {
          type: "SherpaDataset",
          dataset_id: "wine-dataset-2",
          title: "wine",
          backend: "sklearn",
          n_samples: 178,
          n_features: 13,
          shape: [178, 13],
          x_axis: {
            labels: ["alcohol", "malic_acid", "ash"],
          },
          target_context: {
            target_type: "categorical",
            class_names: ["class_0", "class_1", "class_2"],
          },
          extra: {
            "sklearn.dataset_name": "wine",
            "sklearn.target_names": ["class_0", "class_1", "class_2"],
          },
          metadata: {
            feature_names: ["alcohol", "malic_acid", "ash"],
            "sklearn.dataset_name": "wine",
          },
        },
        target: [0, 0, 0, 1, 1, 1, 2, 2, 2],
      },
    };

    await sherpa.sendMessage("What are the top features that can be used as predictor?");

    const payload = JSON.parse(mockWs.send.mock.calls[0][0] as string);
    const datasetContext = payload.payload.workflow_context.dataset_context;
    expect(datasetContext).toMatchObject({
      dataset_id: "wine-dataset-2",
      label: "wine",
      source: "sklearn",
      dataset_name: "wine",
      feature_names: ["alcohol", "malic_acid", "ash"],
      target_names: ["class_0", "class_1", "class_2"],
    });
    // And the results_summary entry should also carry the unwrapped fields.
    expect(payload.payload.workflow_context.results_summary.data_1).toMatchObject({
      dataset_id: "wine-dataset-2",
      backend: "sklearn",
      dataset_name: "wine",
      feature_names: ["alcohol", "malic_acid", "ash"],
      target_names: ["class_0", "class_1", "class_2"],
      n_samples: 178,
      n_features: 13,
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

    await vi.advanceTimersByTimeAsync(SHERPA_RESPONSE_TIMEOUT_MS + 1_000);

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
      notifications.notifications.some(
        (notification) =>
          notification.message.includes("Sherpa tool started") &&
          notification.message.includes("describe_node") &&
          notification.message.includes("server 4.2s, +4.2s"),
      ),
    ).toBe(true);
    expect(
      notifications.notifications.some(
        (notification) =>
          notification.message.includes("Sherpa response received") &&
          notification.message.includes("The model accuracy is 97%.") &&
          notification.message.includes("server 6.2s, +0.6s"),
      ),
    ).toBe(true);

    sherpa.dispose();
  });

  it("attaches suggested follow-ups to the active assistant response", async () => {
    const sherpa = useSherpaStore();
    sherpa.init();

    await sherpa.sendMessage("What should I do next?");
    const requestId = lastRequestId();

    emitSherpa({ type: SHERPA_WS_EVENT.chatStart, request_id: requestId });
    emitSherpa({
      type: SHERPA_WS_EVENT.chatChunk,
      request_id: requestId,
      chunk: "Run the workflow and inspect diagnostics.",
    });
    emitSherpa({
      type: SHERPA_WS_EVENT.chatFollowUps,
      request_id: requestId,
      suggestions: ["Explain the latest run?", "Compare preprocessing choices?"],
    });
    emitSherpa({ type: SHERPA_WS_EVENT.chatDone, request_id: requestId });

    const assistant = sherpa.messages.at(-1);
    expect(assistant?.content).toContain("inspect diagnostics");
    expect(assistant?.followUps).toEqual([
      "Explain the latest run?",
      "Compare preprocessing choices?",
    ]);

    sherpa.dispose();
  });

  it("does not allow server configuration to extend the one-minute deadline", async () => {
    mockAppConfig.value = { limits: { sherpaResponseTimeoutMs: 600_000 } };
    const sherpa = useSherpaStore();
    sherpa.init();
    await sherpa.sendMessage("Explain my PCA result");
    const requestId = lastRequestId();
    emitSherpa({ type: SHERPA_WS_EVENT.chatStart, request_id: requestId });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(sherpa.state).toBe("idle");
    emitSherpa({ type: SHERPA_WS_EVENT.chatChunk, request_id: requestId, chunk: "Completed scientific answer" });
    emitSherpa({ type: SHERPA_WS_EVENT.chatDone, request_id: requestId });
    expect(sherpa.state).toBe("idle");
    expect(sherpa.messages.some((message) => message.content.includes("Completed scientific answer"))).toBe(false);
    sherpa.dispose();
  });

  it("cannot send an old sync after Stop and a replacement sync", async () => {
    const sherpa = useSherpaStore();
    sherpa.init();
    let release!: () => void;
    mockLlmStore.connect.mockImplementationOnce(() => new Promise<void>((resolve) => { release = resolve; }));
    const old = sherpa.syncWorkflow();
    sherpa.stopAnalysis();
    await sherpa.syncWorkflow();
    const sent = mockWs.send.mock.calls.length;
    release();
    await old;
    expect(mockWs.send.mock.calls.length).toBe(sent);
    expect(sherpa.isSyncing).toBe(true);
    sherpa.stopAnalysis();
    sherpa.dispose();
  });

  it.each([false, true])("does not open or fail a stopped proposal when sheet refresh finishes late (reject=%s)", async (reject) => {
    const sherpa = useSherpaStore();
    sherpa.init();
    await sherpa.sendMessage("Create a PCA workflow");
    let release!: () => void;
    mockWorkbookStore.refreshSheets.mockImplementationOnce(() => new Promise<void>((resolve, fail) => { release = () => reject ? fail(new Error("old refresh failed")) : resolve(); }));
    emitSherpa({ type: SHERPA_WS_EVENT.workflowProposed, request_id: lastRequestId(), new_workflow_id: 999, conversation_id: "stale-conversation" });
    expect(mockWorkbookStore.refreshSheets).toHaveBeenCalledOnce();
    sherpa.stopAnalysis();
    await sherpa.sendMessage("Explain PLS");
    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(mockWorkbookStore.selectWorkflowSheet).not.toHaveBeenCalled();
    expect(sherpa.currentConversationId).not.toBe("stale-conversation");
    expect(sherpa.isChatting).toBe(true);
    sherpa.stopAnalysis();
    sherpa.dispose();
  });

  it("does not clear a new request when a previous run refresh finishes late", async () => {
    const sherpa = useSherpaStore();
    sherpa.init();
    await sherpa.sendMessage("Run my workflow");
    let release!: () => void;
    mockWorkflowStore.loadWorkflow.mockImplementationOnce(() => new Promise<void>((resolve) => { release = resolve; }));
    emitSherpa({ type: SHERPA_WS_EVENT.chatDone, request_id: lastRequestId(), execution_result: { workflow_id: 5, run_id: 88, status: "completed" } });
    expect(mockWorkflowStore.loadWorkflow).toHaveBeenCalled();
    await sherpa.sendMessage("Explain PLS");
    const replacementId = lastRequestId();
    release();
    await vi.advanceTimersByTimeAsync(0);
    emitSherpa({ type: SHERPA_WS_EVENT.chatStart, request_id: replacementId });
    emitSherpa({ type: SHERPA_WS_EVENT.chatChunk, request_id: replacementId, chunk: "New answer" });
    expect(sherpa.messages.at(-1)?.content).toBe("New answer");
    expect(sherpa.isChatting).toBe(true);
    sherpa.stopAnalysis();
    sherpa.dispose();
  });

  it("keeps sync active on heartbeats and stops at its original deadline", async () => {
    const sherpa = useSherpaStore();
    sherpa.init();
    await sherpa.syncWorkflow();
    const id = lastRequestId();
    for (const elapsed of [15, 30, 45]) {
      await vi.advanceTimersByTimeAsync(15_000);
      emitSherpa({ type: SHERPA_WS_EVENT.status, request_id: id, payload: { heartbeat: true, elapsed_seconds: elapsed, detail: "Reviewing workflow." } });
      expect(sherpa.isSyncing).toBe(true);
      expect(sherpa.analysisStatus).toContain(`${elapsed}s`);
    }
    await vi.advanceTimersByTimeAsync(15_000);
    expect(sherpa.isSyncing).toBe(false);
    sherpa.dispose();
  });

  it("stops the exact request, ignores late replies and allows a new question", async () => {
    const sherpa = useSherpaStore();
    sherpa.init();
    await sherpa.sendMessage("Explain PCA");
    const stoppedId = lastRequestId();
    sherpa.stopAnalysis();
    expect(JSON.parse(mockWs.send.mock.calls.at(-1)![0] as string)).toEqual({ action: "cancel_request", request_id: stoppedId });
    expect(sherpa.isChatting).toBe(false);
    expect(sherpa.analysisStatus).toBe("");
    emitSherpa({ type: SHERPA_WS_EVENT.chatStart, request_id: stoppedId });
    emitSherpa({ type: SHERPA_WS_EVENT.chatChunk, request_id: stoppedId, chunk: "late reply" });
    expect(sherpa.messages.some((m) => m.content.includes("late reply"))).toBe(false);
    await sherpa.sendMessage("Explain PLS");
    expect(lastRequestId()).not.toBe(stoppedId);
    expect(sherpa.isChatting).toBe(true);
    emitSherpa({ type: SHERPA_WS_EVENT.chatDone, request_id: lastRequestId() });
    expect(sherpa.isChatting).toBe(false);
    sherpa.dispose();
  });

  it("updates the in-place status at 15 seconds without extending the deadline", async () => {
    const sherpa = useSherpaStore();
    sherpa.init();
    await sherpa.sendMessage("Explain PCA");
    const id = lastRequestId();
    for (const elapsed of [15, 30, 45]) {
      await vi.advanceTimersByTimeAsync(15_000);
      emitSherpa({ type: SHERPA_WS_EVENT.status, request_id: id, payload: { heartbeat: true, elapsed_seconds: elapsed, detail: "Waiting for the model response." } });
      expect(sherpa.analysisStatus).toContain(`${elapsed}s`);
      expect(sherpa.isChatting).toBe(true);
    }
    await vi.advanceTimersByTimeAsync(15_000);
    expect(sherpa.isChatting).toBe(false);
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

    await vi.advanceTimersByTimeAsync(SHERPA_RESPONSE_TIMEOUT_MS);

    expect(sherpa.state).toBe("idle");
    expect(notifications.notifications[0]?.message).toContain(
      "Sherpa Advisor timed out while waiting for tool: describe_node",
    );

    sherpa.dispose();
  });

  it("reports a timeout before server acknowledgement when no chat start arrives", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();

    await sherpa.sendMessage("Explain my PCA result");
    await vi.advanceTimersByTimeAsync(SHERPA_RESPONSE_TIMEOUT_MS);

    expect(sherpa.state).toBe("idle");
    expect(notifications.notifications[0]?.message).toContain(
      "Sherpa Advisor timed out before the server acknowledged the request.",
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

    await vi.advanceTimersByTimeAsync(SHERPA_RESPONSE_TIMEOUT_MS);

    expect(sherpa.state).toBe("idle");
    expect(
      notifications.notifications.some(
        (notification) =>
          notification.message.includes("Sherpa server acknowledged the request.") &&
          notification.message.includes("server 1.2s, +1.2s"),
      ),
    ).toBe(true);
    expect(notifications.notifications[0]?.message).toContain(
      "Sherpa Advisor timed out. Last activity: Sherpa server acknowledged the request.",
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
      "Demo Sherpa interaction limit reached (200 interactions per session)",
    );
    expect(sherpa.messages.at(-1)?.content).toBe(
      "Demo Sherpa interaction limit reached (200 interactions per session)\nRemaining: 0\nUsage resets after 24 hours of inactivity.",
    );
    expect(notifications.notifications[0]?.message).toBe(
      "Demo Sherpa interaction limit reached (200 interactions per session) Remaining: 0 Usage resets after 24 hours of inactivity.",
    );
    expect(notifications.notifications[0]?.detail).toBe(
      "Remaining: 0\nUsage resets after 24 hours of inactivity.",
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

    expect(sherpa.messages.at(-1)?.content).toBe("Sherpa Advisor recorded your decision.");

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
        notification.message.includes("Sherpa recovered a missing response start"),
      ),
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
      "Sherpa tool failed (timeout): describe_node.",
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
        detail:
          "Sherpa exhausted 2 tool rounds and is making a final response without more tool calls.",
      },
    });

    expect(sherpa.messages.at(-1)?.content).toContain("Sherpa exhausted 2 tool rounds");

    sherpa.dispose();
  });

  it("shows the secondary model name but never the supplier URL/key (audit F3/F4)", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();
    sherpa.init();

    await sherpa.sendMessage("Explain this workflow", true);
    const payload = JSON.parse(mockWs.send.mock.calls[0][0] as string);

    // Real server payload shape after audit #15/#19: detail carries the
    // model-named message; secondary_model is the configured label only.
    emitSherpa({
      type: SHERPA_WS_EVENT.status,
      request_id: payload.payload.request_id,
      payload: {
        connected: true,
        stage: "secondary_llm",
        detail:
          "Primary AI is busy — Sherpa is using a backup model (deepseek-chat). " +
          "Responses may be briefer; agentic tools are unavailable for this reply.",
        secondary_model: "deepseek-chat",
        tool_support: false,
      },
    });

    const rendered = sherpa.messages.at(-1)?.content ?? "";
    // Positive: the model label IS surfaced so users can tell a
    // degraded turn apart (product decision).
    expect(rendered).toContain("deepseek-chat");
    expect(
      notifications.notifications.some((notification) =>
        notification.message.includes("deepseek-chat"),
      ),
    ).toBe(true);

    // Negative: never expose supplier base URL / API key / env-var name
    // in any user-facing surface.
    expect(rendered).not.toMatch(/api\.deepseek\.com|https?:\/\/|sk-|SHERPA_GUIDANCE/i);

    sherpa.dispose();
  });

  it("surfaces Sherpa sync timeouts in notifications", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();

    await sherpa.syncWorkflow();
    await vi.advanceTimersByTimeAsync(SHERPA_SYNC_TIMEOUT_MS);

    expect(sherpa.state).toBe("idle");
    expect(notifications.notifications[0]?.message).toBe(
      "Sherpa sync timed out. The service may be unavailable.",
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
      "Sherpa event handling failed: Sherpa chat chunk payload was missing text.",
    );
    expect(notifications.notifications[0]?.message).toContain(
      "Sherpa event handling failed: Sherpa chat chunk payload was missing text.",
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

  it("sends retained effective parameters instead of current registry defaults", async () => {
    // Simulate a node with a user override that leaves another param unset.
    mockWorkflowStore.getNodeMetadata.mockImplementation((nodeType: string) => {
      if (nodeType === "data.train_test_split") {
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
        type: "data.train_test_split",
        params: { test_size: 0.25 }, // user override; method and random_seed not set
        executionState: { status: "completed" },
      },
    ];

    const sherpa = useSherpaStore();
    mockWorkflowStore.lastExecutionParams = {partition_1:{test_size:0.25,method:"stratified",random_seed:17}};
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
    expect(params.random_seed).toBe(17);
    mockWorkflowStore.lastExecutionParams = {};
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

  it("projects merged PeakTable fields into chemistry context without a separate output", async () => {
    mockWorkflowStore.nodes = [{ id: "peak", type: "analysis.peak_finding", params: {} }];
    mockWorkflowStore.lastExecutionResults = {
      peak: { peaks: {
        data: [{ median_pos: 1206, detection_fraction: 1, label: "consensus peak (155/155 samples)" }],
        metadata: { method: "peak_finding", x_units: "nm", selection_context: { n_samples: 155, technique: "NIR" } },
      } },
    };
    await useSherpaStore().sendMessage("explain these peaks");
    const summary = (getLastSyncPayload()?.results_summary as Record<string, Record<string, unknown>>)?.peak;
    expect(summary.salient_features).toMatchObject({
      method: "peak_finding", x_units: "nm",
      features: [{ position: 1206, importance: 1, label: "consensus peak (155/155 samples)" }],
      selection_context: { n_samples: 155, technique: "NIR" },
    });
  });

  it("adopts conversation_id from Sherpa chat start events", async () => {
    const sherpa = useSherpaStore();
    sherpa.init();

    await sherpa.sendMessage("tell me about PCA");
    emitSherpa({
      type: SHERPA_WS_EVENT.chatStart,
      request_id: lastRequestId(),
      conversation_id: "conv-42",
    });

    expect(sherpa.currentConversationId).toBe("conv-42");

    sherpa.dispose();
  });

  it("loads server conversation details by id and scopes Topics to the active worksheet", async () => {
    const { useProjectStore } = await import("@/stores/project");
    useProjectStore().currentProjectId = 42;
    const sherpa = useSherpaStore();
    sherpa.init();
    mockApi.get.mockImplementation(async (url: string) => {
      if (url.endsWith("/conv-parent")) {
        return {
          data: {
            id: "conv-parent",
            title: "Mother SIMCA",
            messages: [
              { role: "user", content: "Build an alternative." },
              {
                role: "assistant",
                content: "Generated alternative → opened as Sheet 'AI PLS-DA'.",
              },
            ],
          },
        };
      }
      if (url.endsWith("/conv-ai")) {
        return {
          data: {
            id: "conv-ai",
            title: "AI PLS-DA",
            messages: [
              { role: "user", content: "Build an alternative." },
              { role: "assistant", content: "Here is the PLS-DA workflow." },
              { role: "user", content: "Explain the model math." },
              { role: "assistant", content: "PLS-DA uses a dummy-coded class matrix." },
            ],
          },
        };
      }
      throw new Error(`Unexpected URL: ${url}`);
    });

    await sherpa.loadConversation("conv-ai");
    expect(sherpa.currentConversationId).toBe("conv-ai");
    expect(sherpa.messages.at(-1)?.content).toContain("dummy-coded");
    expect(sherpa.conversations.map((item) => item.id)).toEqual(["conv-ai"]);

    await sherpa.loadConversation("conv-parent");
    expect(sherpa.currentConversationId).toBe("conv-parent");
    expect(sherpa.messages.map((item) => item.content).join("\n")).toContain(
      "Generated alternative",
    );
    expect(sherpa.messages.map((item) => item.content).join("\n")).not.toContain("dummy-coded");
    expect(sherpa.conversations.map((item) => item.id)).toEqual(["conv-parent"]);

    await sherpa.loadConversation("conv-ai");
    expect(sherpa.currentConversationId).toBe("conv-ai");
    expect(sherpa.messages.at(-1)?.content).toContain("dummy-coded");
    expect(sherpa.conversations.map((item) => item.id)).toEqual(["conv-ai"]);

    sherpa.dispose();
  });

  it("refreshes Sherpa Topics from the active worksheet channel only", async () => {
    const { useProjectStore } = await import("@/stores/project");
    useProjectStore().currentProjectId = 42;
    mockAdvisorStore.activeChannelId = 40;
    const sherpa = useSherpaStore();
    sherpa.init();
    mockApi.get.mockResolvedValue({
      data: {
        id: "conv-ai",
        title: "AI child topic",
        updated_at: "2026-05-07T00:00:00Z",
        messages: [],
      },
    });

    await sherpa.refreshConversations(42);

    expect(mockApi.get).toHaveBeenCalledWith("/llm/conversation/conv-ai", {
      params: { project_id: 42 },
    });
    expect(sherpa.conversations).toEqual([
      {
        id: "conv-ai",
        title: "AI child topic",
        updatedAt: "2026-05-07T00:00:00Z",
      },
    ]);
  });

  it("loads a project resume recap at most once per 24 hours", async () => {
    vi.setSystemTime(new Date("2026-05-10T08:00:00Z"));
    const sherpa = useSherpaStore();
    mockApi.get.mockResolvedValueOnce({
      data: {
        recap: "You selected PLS-DA and saved a class-balance caveat.",
        last_active_at: "2026-05-10T07:00:00Z",
        cached: false,
      },
    });

    await sherpa.maybeLoadResumeRecap(42);

    expect(mockApi.get).toHaveBeenCalledWith("/sherpa/recap", {
      params: { project_id: 42 },
    });
    expect(sherpa.resumeRecap?.recap).toContain("PLS-DA");

    mockApi.get.mockClear();
    await sherpa.maybeLoadResumeRecap(42);
    expect(mockApi.get).not.toHaveBeenCalled();

    vi.setSystemTime(new Date("2026-05-11T09:00:00Z"));
    mockApi.get.mockResolvedValueOnce({
      data: {
        recap: "You later compared the model against PCA.",
        last_active_at: "2026-05-11T08:30:00Z",
        cached: true,
      },
    });

    await sherpa.maybeLoadResumeRecap(42);

    expect(mockApi.get).toHaveBeenCalledTimes(1);
    expect(sherpa.resumeRecap?.cached).toBe(true);
    expect(sherpa.resumeRecap?.recap).toContain("PCA");
  });

  it("does not show a dismissed resume recap until the memory timestamp changes", async () => {
    vi.setSystemTime(new Date("2026-05-10T08:00:00Z"));
    const sherpa = useSherpaStore();
    mockApi.get.mockResolvedValueOnce({
      data: {
        recap: "You selected PLS-DA.",
        last_active_at: "2026-05-10T07:00:00Z",
        cached: false,
      },
    });

    await sherpa.maybeLoadResumeRecap(42);
    sherpa.dismissResumeRecap();
    expect(sherpa.resumeRecap).toBeNull();

    vi.setSystemTime(new Date("2026-05-11T09:00:00Z"));
    mockApi.get.mockResolvedValueOnce({
      data: {
        recap: "You selected PLS-DA.",
        last_active_at: "2026-05-10T07:00:00Z",
        cached: true,
      },
    });

    await sherpa.maybeLoadResumeRecap(42);
    expect(sherpa.resumeRecap).toBeNull();

    vi.setSystemTime(new Date("2026-05-12T10:00:00Z"));
    mockApi.get.mockResolvedValueOnce({
      data: {
        recap: "You added a new validation result.",
        last_active_at: "2026-05-12T09:00:00Z",
        cached: false,
      },
    });

    await sherpa.maybeLoadResumeRecap(42);
    expect(sherpa.resumeRecap?.recap).toContain("validation");
  });

  it("throttles failed resume recap fetches before retrying", async () => {
    vi.setSystemTime(new Date("2026-05-10T08:00:00Z"));
    const sherpa = useSherpaStore();
    mockApi.get.mockRejectedValueOnce(new Error("recap unavailable"));

    await sherpa.maybeLoadResumeRecap(42);

    expect(mockApi.get).toHaveBeenCalledTimes(1);
    expect(sherpa.resumeRecap).toBeNull();

    mockApi.get.mockClear();
    vi.setSystemTime(new Date("2026-05-10T08:30:00Z"));
    await sherpa.maybeLoadResumeRecap(42);
    expect(mockApi.get).not.toHaveBeenCalled();

    vi.setSystemTime(new Date("2026-05-10T09:01:00Z"));
    mockApi.get.mockResolvedValueOnce({
      data: {
        recap: "You saved a validated workflow.",
        last_active_at: "2026-05-10T09:00:00Z",
        cached: false,
      },
    });

    await sherpa.maybeLoadResumeRecap(42);

    expect(mockApi.get).toHaveBeenCalledTimes(1);
    expect(sherpa.resumeRecap?.recap).toContain("validated workflow");
  });

  it("treats persisted results as completed when executionState is still pending", async () => {
    mockWorkflowStore.getNodeMetadata.mockImplementation((nodeType: string) => {
      if (nodeType === "classification.plsda") {
        return {
          label: "PLS-DA",
          description: "Classification model",
          output_type: "PLSModel",
          parameters: [
            {
              name: "n_components",
              label: "Components",
              description: "Latent variables",
              default: 2,
            },
          ],
        };
      }
      if (nodeType === "data.file_load") {
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
        type: "data.file_load",
        params: {},
        executionState: {
          status: "completed",
          output_shape: [150, 4],
          output_type: "SherpaDataset",
        },
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
