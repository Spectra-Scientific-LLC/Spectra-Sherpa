import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

const { apiGet } = vi.hoisted(() => ({
  apiGet: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  expireBrowserSession: vi.fn(),
  default: {
    get: apiGet,
    defaults: {
      baseURL: "http://127.0.0.1:8000/api/v1",
    },
  },
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({
    user: { id: 1 },
  }),
}));

vi.mock("@/composables/useNotifier", () => ({
  useNotifier: () => ({
    notifyJobUpdate: vi.fn(),
  }),
}));

import { useJobStore } from "@/stores/job";

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

describe("Job Store WebSocket policy close", () => {
  let sockets: MockWebSocket[] = [];
  let OriginalWebSocket: typeof WebSocket;

  beforeEach(() => {
    vi.useFakeTimers();
    setActivePinia(createPinia());
    localStorage.clear();
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
    localStorage.clear();
  });

  it("keeps a valid JWT when a 1008 close is a server policy closure", async () => {
    localStorage.setItem("token", "jwt-still-valid");
    const jobs = useJobStore();

    const connectPromise = jobs.connect();
    await Promise.resolve();
    sockets[0].dispatch("open");
    await connectPromise;

    apiGet.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve({ data: { id: 1 } }) : Promise.resolve({ data: [] })
    );
    sockets[0].dispatch("close", { code: 1008 });
    await vi.advanceTimersByTimeAsync(0);

    // The hosted demo/pro session must survive a policy close: the JWT is
    // retained and the store reconnects with ordinary backoff.
    expect(localStorage.getItem("token")).toBe("jwt-still-valid");
    expect(jobs.lastError).toBe("Live updates paused by server policy. Reconnecting.");

    await vi.advanceTimersByTimeAsync(1000);
    expect(sockets).toHaveLength(2);
    sockets[1].dispatch("open");
    expect(JSON.parse(sockets[1].sent[0] ?? "{}")).toMatchObject({ type: "authenticate" });

    jobs.disconnect();
  });

  it("stops reconnecting only when the session probe rejects the token with 401", async () => {
    localStorage.setItem("token", "jwt-expired");
    const jobs = useJobStore();

    const connectPromise = jobs.connect();
    await Promise.resolve();
    sockets[0].dispatch("open");
    await connectPromise;

    apiGet.mockImplementation((path: string) =>
      path === "/auth/me" ? Promise.resolve({ status: 401, data: {} }) : Promise.resolve({ data: [] })
    );
    sockets[0].dispatch("close", { code: 1008 });
    await vi.advanceTimersByTimeAsync(0);

    expect(jobs.lastError).toBe("Unauthorized. Check your credentials.");

    // allowReconnect is off: no further socket is attempted.
    await vi.advanceTimersByTimeAsync(60000);
    expect(sockets).toHaveLength(1);
  });
  it("backs off across policy refusals and stops at the retry limit", async () => {
    localStorage.setItem("token", "valid");
    const jobs = useJobStore();
    const first = jobs.connect();
    sockets[0].dispatch("open");
    await first;
    expect(jobs.connected).toBe(false);
    for (let attempt = 0; attempt < 10; attempt++) {
      sockets[attempt].close(1008);
      const delay = Math.min(1000 * 2 ** attempt, 30000);
      await vi.advanceTimersByTimeAsync(delay - 1);
      expect(sockets).toHaveLength(attempt + 1);
      await vi.advanceTimersByTimeAsync(1);
      expect(sockets).toHaveLength(attempt + 2);
      sockets[attempt + 1].dispatch("open");
    }
    sockets[10].close(1008);
    await vi.advanceTimersByTimeAsync(120000);
    expect(sockets).toHaveLength(11);
    expect(jobs.lastError).toBe("Max reconnection attempts reached");
    expect(apiGet.mock.calls.every(([path]) => path === "/auth/me")).toBe(true);
    expect(localStorage.getItem("token")).toBe("valid");
    jobs.disconnect();
  });

  it("resets retry delay and subscribes only after authentication", async () => {
    localStorage.setItem("token", "valid");
    const jobs = useJobStore();
    const first = jobs.connect();
    sockets[0].dispatch("open");
    await first;
    expect(sockets[0].sent).toHaveLength(1);
    sockets[0].close(1008);
    await vi.advanceTimersByTimeAsync(1000);
    sockets[1].dispatch("open");
    sockets[1].dispatch("message", { data: JSON.stringify({ type: "authenticated" }) });
    expect(jobs.connected).toBe(true);
    expect(apiGet).toHaveBeenCalledWith("/jobs");
    expect(JSON.parse(sockets[1].sent[1])).toEqual({ action: "subscribe", channel: "jobs:1" });
    sockets[1].close(1008);
    await vi.advanceTimersByTimeAsync(1000);
    expect(sockets).toHaveLength(3);
    jobs.disconnect();
  });

  it.each([false, true])("ignores a late probe after disconnect (replace=%s)", async (replace) => {
    localStorage.setItem("token", "valid");
    const jobs = useJobStore();
    const first = jobs.connect();
    sockets[0].dispatch("open");
    await first;
    let finish!: (response: unknown) => void;
    apiGet.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    sockets[0].close(1008);
    jobs.disconnect();
    expect(apiGet.mock.calls[0][1].signal.aborted).toBe(true);
    if (replace) {
      const next = jobs.connect();
      sockets[1].dispatch("open");
      sockets[1].dispatch("message", { data: JSON.stringify({ type: "authenticated" }) });
      await next;
    }
    finish({ status: 401 });
    await vi.advanceTimersByTimeAsync(60000);
    expect(sockets).toHaveLength(replace ? 2 : 1);
    expect(jobs.connectionStatus).toBe(replace ? "connected" : "disconnected");
    expect(localStorage.getItem("token")).toBe("valid");
    jobs.disconnect();
  });

  it("recovers with a renewed token while the session probe is pending", async () => {
    localStorage.setItem("token", "old-session");
    let finish!: (response: unknown) => void;
    apiGet.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const store = useJobStore();
    const pending = store.connect();
    sockets[0].dispatch("open");
    await pending;
    sockets[0].close(1008);
    localStorage.setItem("token", "renewed-session");
    finish({ status: 401 });
    await vi.advanceTimersByTimeAsync(1000);
    expect(sockets).toHaveLength(2);
    sockets[1].dispatch("open");
    expect(JSON.parse(sockets[1].sent[0]).token).toBe("renewed-session");
    sockets[1].dispatch("message", { data: JSON.stringify({ type: "authenticated" }) });
    await pending;
    expect(store.connectionStatus).toBe("connected");
    expect(localStorage.getItem("token")).toBe("renewed-session");
    store.disconnect();
    localStorage.clear();
  });

});
