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
  nodes: [] as Array<Record<string, unknown>>,
  edges: [] as Array<Record<string, unknown>>,
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
    mockWorkflowStore.nodes = [];
    mockWorkflowStore.edges = [];
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
});
