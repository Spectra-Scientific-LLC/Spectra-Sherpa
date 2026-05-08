import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { ref } from "vue";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  appMode: { __v_isRef: true, value: "local" },
  featureFlags: {
    chatAssistant: false,
  } as Record<string, boolean>,
}));

vi.mock("@/api/client", () => ({
  default: {
    get: mocks.apiGet,
    defaults: {
      baseURL: "http://127.0.0.1:8000/api/v1",
    },
  },
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appMode: mocks.appMode,
    isFeatureEnabled: (feature: string) => Boolean(mocks.featureFlags[feature]),
  }),
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({
    user: { id: 1 },
  }),
}));

vi.mock("@/stores/project", () => ({
  useProjectStore: () => ({
    currentProjectId: null,
  }),
}));

vi.mock("@/stores/notification", () => ({
  useNotificationStore: () => ({
    add: vi.fn(),
  }),
}));

import { useLlmStore } from "@/stores/llm";

const encoder = new TextEncoder();

const makeSseResponse = (...events: Array<Record<string, unknown>>): Response =>
  ({
    ok: true,
    status: 200,
    body: new ReadableStream({
      start(controller) {
        for (const event of events) {
          controller.enqueue(
            encoder.encode(`data: ${JSON.stringify(event)}\n\n`)
          );
        }
        controller.close();
      },
    }),
  } as Response);

describe("LLM Store local BYO chat", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let originalFetch: typeof globalThis.fetch | undefined;

  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    mocks.featureFlags.chatAssistant = false;
    mocks.apiGet.mockReset();
    originalFetch = globalThis.fetch;
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as typeof fetch;
  });

  afterEach(() => {
    if (originalFetch) {
      globalThis.fetch = originalFetch;
    } else {
      delete (globalThis as { fetch?: typeof fetch }).fetch;
    }
    vi.clearAllMocks();
  });

  it("streams local chat over /chat/stream and persists browser-local history", async () => {
    mocks.featureFlags.chatAssistant = true;
    fetchMock.mockResolvedValue(
      makeSseResponse(
        { type: "chunk", text: "Hello " },
        { type: "chunk", text: "world" },
        { type: "done" }
      )
    );

    const llm = useLlmStore();
    await llm.sendMessage("Explain PCA");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/chat/stream",
      expect.objectContaining({
        method: "POST",
      })
    );
    expect(llm.currentConversationId).toBeTruthy();
    expect(llm.messages).toEqual([
      { role: "user", content: "Explain PCA" },
      { role: "assistant", content: "Hello world" },
    ]);
    expect(llm.conversations).toHaveLength(1);

    const conversationId = llm.currentConversationId!;
    llm.startNewConversation();
    await llm.loadConversation(conversationId);

    expect(llm.messages).toEqual([
      { role: "user", content: "Explain PCA" },
      { role: "assistant", content: "Hello world" },
    ]);

    await llm.deleteConversation(conversationId);
    expect(llm.conversations).toEqual([]);
    expect(llm.messages).toEqual([]);
  });

  it("derives local config status from the chatAssistant capability", async () => {
    const llm = useLlmStore();

    await llm.checkConfigChange();
    expect(llm.configStatus).toBe("unavailable");
    expect(llm.currentConfig).toBeNull();

    mocks.featureFlags.chatAssistant = true;
    await llm.checkConfigChange();

    expect(llm.configStatus).toBe("configured");
    expect(llm.currentConfig).toEqual({
      provider: "byo-endpoint",
      base_url: "",
      model: "configured-via-env",
      verbose: true,
      max_paragraphs: 2,
    });
  });
});
