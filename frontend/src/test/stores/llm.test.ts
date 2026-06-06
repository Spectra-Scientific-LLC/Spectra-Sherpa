import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { ref } from "vue";

const { apiGet } = vi.hoisted(() => ({
  apiGet: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: {
    get: apiGet,
    defaults: {
      baseURL: "http://127.0.0.1:8000/api/v1",
    },
  },
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appMode: ref("enterprise"),
    isFeatureEnabled: () => false,
  }),
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({
    user: { id: 1 },
  }),
}));

vi.mock("@/stores/project", () => ({
  useProjectStore: () => ({
    currentProjectId: 1,
  }),
}));

import { useLlmStore } from "@/stores/llm";
import { useNotificationStore } from "@/stores/notification";

class MockWebSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  static CLOSED = 3;

  readyState = MockWebSocket.CONNECTING;
  sent: string[] = [];
  private listeners = new Map<string, Array<(event?: any) => void>>();

  constructor(public url: string) {}

  addEventListener(type: string, handler: (event?: any) => void) {
    const current = this.listeners.get(type) || [];
    current.push(handler);
    this.listeners.set(type, current);
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  close(code = 1000, reason = "") {
    this.readyState = MockWebSocket.CLOSED;
    this.dispatch("close", { code, reason });
  }

  dispatch(type: string, event: any = {}) {
    if (type === "open") {
      this.readyState = MockWebSocket.OPEN;
    }
    for (const handler of this.listeners.get(type) || []) {
      handler(event);
    }
  }
}

const axiosError = (status: number) => {
  const err = new Error(`Request failed with status code ${status}`);
  (err as unknown as { response: { status: number } }).response = { status };
  return err;
};

describe("LLM Store WebSocket handshake", () => {
  let sockets: MockWebSocket[] = [];
  let OriginalWebSocket: typeof WebSocket;

  beforeEach(() => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
    apiGet.mockReset();
    apiGet.mockResolvedValue({ data: [] });
    sockets = [];
    OriginalWebSocket = globalThis.WebSocket;
    class TestWebSocket extends MockWebSocket {
      static OPEN = MockWebSocket.OPEN;
      static CONNECTING = MockWebSocket.CONNECTING;
      static CLOSED = MockWebSocket.CLOSED;

      constructor(url: string) {
        super(url);
        sockets.push(this);
      }
    }
    globalThis.WebSocket = TestWebSocket as unknown as typeof WebSocket;
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    globalThis.WebSocket = OriginalWebSocket;
  });

  it("waits for authenticated before resolving connect and emits handshake transport events", async () => {
    const llm = useLlmStore();
    const transportEvents: Array<{ kind?: string; detail?: string | null }> = [];
    const handler = (event: Event) => {
      transportEvents.push((event as CustomEvent).detail);
    };
    window.addEventListener("app-ws-transport", handler);

    let resolved = false;
    const connectPromise = llm.connect().then(() => {
      resolved = true;
    });
    await Promise.resolve();

    expect(llm.connectionStatus).toBe("connecting");
    expect(sockets).toHaveLength(1);

    sockets[0].dispatch("open");
    await Promise.resolve();

    expect(resolved).toBe(false);
    expect(sockets[0].sent).toHaveLength(1);
    expect(JSON.parse(sockets[0].sent[0])).toMatchObject({
      type: "authenticate",
    });
    expect(transportEvents.map((event) => event.kind)).toEqual([
      "socket_open",
      "auth_sent",
    ]);

    sockets[0].dispatch("message", {
      data: JSON.stringify({ type: "authenticated", user_id: 1 }),
    });
    await connectPromise;

    expect(llm.connectionStatus).toBe("connected");
    expect(transportEvents.map((event) => event.kind)).toEqual([
      "socket_open",
      "auth_sent",
      "auth_ack",
    ]);

    window.removeEventListener("app-ws-transport", handler);
  });

  it("fails connect if authenticated ack never arrives", async () => {
    const llm = useLlmStore();
    const transportEvents: Array<{ kind?: string; detail?: string | null }> = [];
    const handler = (event: Event) => {
      transportEvents.push((event as CustomEvent).detail);
    };
    window.addEventListener("app-ws-transport", handler);

    const connectPromise = llm.connect();
    void connectPromise.catch(() => undefined);
    await Promise.resolve();
    sockets[0].dispatch("open");
    await vi.advanceTimersByTimeAsync(5250);
    sockets[1].dispatch("open");
    await vi.advanceTimersByTimeAsync(5500);
    sockets[2].dispatch("open");
    await vi.advanceTimersByTimeAsync(6000);

    await expect(connectPromise).rejects.toThrow("WebSocket authentication timed out.");
    expect(transportEvents.map((event) => event.kind)).toContain("auth_timeout");
    expect(transportEvents.map((event) => event.kind)).toContain("connect_retry");

    window.removeEventListener("app-ws-transport", handler);
  });

  it("retries the initial connection after auth timeout and succeeds on the next socket", async () => {
    const llm = useLlmStore();
    const transportEvents: Array<{ kind?: string; detail?: string | null }> = [];
    const handler = (event: Event) => {
      transportEvents.push((event as CustomEvent).detail);
    };
    window.addEventListener("app-ws-transport", handler);

    const connectPromise = llm.connect();
    await Promise.resolve();
    sockets[0].dispatch("open");
    await vi.advanceTimersByTimeAsync(5000);
    expect(sockets[0].readyState).toBe(MockWebSocket.CLOSED);

    await vi.advanceTimersByTimeAsync(250);
    expect(sockets).toHaveLength(2);

    sockets[1].dispatch("open");
    sockets[1].dispatch("message", {
      data: JSON.stringify({ type: "authenticated", user_id: 1 }),
    });
    await connectPromise;

    expect(llm.connectionStatus).toBe("connected");
    expect(transportEvents.map((event) => event.kind)).toContain("connect_retry");

    window.removeEventListener("app-ws-transport", handler);
  });

  it("surfaces streaming warning events in chat and notifications", async () => {
    const llm = useLlmStore();
    const notifications = useNotificationStore();

    const connectPromise = llm.connect();
    await Promise.resolve();
    sockets[0].dispatch("open");
    sockets[0].dispatch("message", {
      data: JSON.stringify({ type: "authenticated", user_id: 1 }),
    });
    await connectPromise;

    await llm.sendMessage("Explain this");

    sockets[0].dispatch("message", {
      data: JSON.stringify({ type: "llm_start", conversation_id: "conv-1" }),
    });
    sockets[0].dispatch("message", {
      data: JSON.stringify({
        type: "llm_warning",
        conversation_id: "conv-1",
        code: "history_load_failed",
        detail: "Conversation history could not be loaded. Sherpa is replying without prior chat context.",
      }),
    });

    expect(llm.messages.at(-1)?.role).toBe("system");
    expect(llm.messages.at(-1)?.content).toBe(
      "Conversation history could not be loaded. Continuing without prior chat context."
    );
    expect(notifications.notifications[0]?.title).toBe("Chat");
    expect(notifications.notifications[0]?.message).toBe(
      "Conversation history could not be loaded. Continuing without prior chat context."
    );
    expect(notifications.notifications[0]?.detail).toBe(
      "Conversation history could not be loaded. Sherpa is replying without prior chat context."
    );
  });

});

describe("LLM Store refreshConversations project-scope cleanup", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    apiGet.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("clears stale rows when a project switch fails list fetch and probe 404s", async () => {
    // Seed lastConversationProjectId via a successful refresh for the
    // old project; otherwise switchingProjects is false and the new
    // contract preserves state on 404 (treating it as eventual consistency).
    apiGet.mockResolvedValueOnce({ data: [] });
    apiGet.mockRejectedValueOnce(axiosError(503));
    apiGet.mockRejectedValueOnce(axiosError(404));

    const llm = useLlmStore();
    await llm.refreshConversations(1);

    llm.currentConversationId = "conv-old";
    llm.messages = [{ role: "assistant", content: "old thread" }];
    llm.conversations = [{ id: "conv-old", title: "Old thread", updatedAt: "t0" }];

    await llm.refreshConversations(999);

    expect(llm.currentConversationId).toBeNull();
    expect(llm.messages).toEqual([]);
    expect(llm.conversations).toEqual([]);
  });

  it("clears stale rows on project switch failure even when there is no active conversation", async () => {
    apiGet.mockResolvedValueOnce({
      data: [{ id: "conv-old", title: "Old thread", updated_at: "t0" }],
    });

    const llm = useLlmStore();
    await llm.refreshConversations(1);

    llm.currentConversationId = null;
    llm.messages = [{ role: "assistant", content: "Old project transcript" }];
    llm.conversations = [{ id: "conv-old", title: "Old thread", updatedAt: "t0" }];

    apiGet.mockReset();
    apiGet.mockRejectedValueOnce(axiosError(503));

    await llm.refreshConversations(999);

    expect(llm.currentConversationId).toBeNull();
    expect(llm.messages).toEqual([]);
    expect(llm.conversations).toEqual([]);
  });
});
