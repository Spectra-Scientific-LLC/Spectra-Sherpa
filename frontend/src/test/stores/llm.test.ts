import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { ref } from "vue";

const { apiGet } = vi.hoisted(() => ({
  apiGet: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: {
    get: apiGet,
  },
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appMode: ref("enterprise"),
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

describe("LLM Store WebSocket handshake", () => {
  let sockets: MockWebSocket[] = [];
  let OriginalWebSocket: typeof WebSocket;

  beforeEach(() => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
    apiGet.mockReset();
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
    sockets[0].dispatch("open");
    await vi.advanceTimersByTimeAsync(5000);

    await expect(connectPromise).rejects.toThrow("WebSocket authentication timed out.");
    expect(transportEvents.map((event) => event.kind)).toContain("auth_timeout");

    window.removeEventListener("app-ws-transport", handler);
  });
});
