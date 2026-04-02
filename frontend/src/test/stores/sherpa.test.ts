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

  it("does not send Sherpa chat when no workflow is loaded", async () => {
    const sherpa = useSherpaStore();
    const notifications = useNotificationStore();
    mockWorkflowStore.workflowId = null;

    await sherpa.sendMessage("tell me about PCA");

    expect(mockLlmStore.connect).not.toHaveBeenCalled();
    expect(mockWs.send).not.toHaveBeenCalled();
    expect(sherpa.messages.at(-1)?.content).toBe(
      "Load or create a workflow before asking Sherpa Advisor a question."
    );
    expect(notifications.notifications[0]?.message).toBe(
      "Load or create a workflow before asking Sherpa Advisor a question."
    );
  });
});
