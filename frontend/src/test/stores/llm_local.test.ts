import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

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
import { clearStoredApiKey, writeStoredApiKey } from "@/utils/authStorage";

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
    clearStoredApiKey();
    vi.clearAllMocks();
  });

  it.each([true, false])("uses one streaming credential with bearer present=%s", async (hasBearer) => {
    mocks.featureFlags.chatAssistant = true;
    if (hasBearer) localStorage.setItem("token", "alice-token");
    writeStoredApiKey("bob-key");
    fetchMock.mockResolvedValue(makeSseResponse({ type: "done" }));
    await useLlmStore().sendMessage("Explain PCA");
    const headers = new Headers(fetchMock.mock.calls[0][1].headers);
    expect(headers.get("Authorization")).toBe(hasBearer ? "Bearer alice-token" : null);
    expect(headers.get("X-API-Key")).toBe(hasBearer ? null : "bob-key");
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
      expect.objectContaining({
        id: expect.any(String),
        role: "user",
        content: "Explain PCA",
      }),
      expect.objectContaining({
        id: expect.any(String),
        role: "assistant",
        content: "Hello world",
      }),
    ]);
    expect(llm.conversations).toHaveLength(1);

    const conversationId = llm.currentConversationId!;
    llm.startNewConversation();
    await llm.loadConversation(conversationId);

    expect(llm.messages).toEqual([
      expect.objectContaining({
        id: expect.any(String),
        role: "user",
        content: "Explain PCA",
      }),
      expect.objectContaining({
        id: expect.any(String),
        role: "assistant",
        content: "Hello world",
      }),
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


describe("LLM Store hosted configuration", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    mocks.appMode.value = "enterprise";
    mocks.apiGet.mockReset();
  });
  afterEach(() => { mocks.appMode.value = "local"; });

  it("reads the registered configuration contract without a debug endpoint", async () => {
    mocks.apiGet.mockResolvedValue({ data: {
      features: { chatAssistant: true }, configStatus: "ok",
      llms: { anthropic: { enabled: true, model: "test-model" } },
    } });
    const store = useLlmStore();
    await store.checkConfigChange();
    expect(mocks.apiGet).toHaveBeenCalledWith("/config");
    expect(store.configStatus).toBe("configured");
    expect(store.currentConfig).toMatchObject({ provider: "anthropic", model: "test-model", base_url: "" });
  });

  it.each([
    { features: { chatAssistant: false }, configStatus: "ok" },
    { features: { chatAssistant: true }, configStatus: "degraded" },
  ])("refuses to claim readiness when unavailable: %j", async (data) => {
    mocks.apiGet.mockResolvedValue({ data });
    const store = useLlmStore();
    await store.checkConfigChange();
    expect(store.configStatus).toBe("unavailable");
    expect(store.currentConfig).toBeNull();
  });
});
