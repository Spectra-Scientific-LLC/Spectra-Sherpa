/**
 * Regression coverage for the Sherpa Advisor refreshConversations() state
 * contract. The bug this guards against:
 *
 *   1. User sends a chat question.
 *   2. Server streams response; chatDone arrives carrying a new
 *      conversation_id that is now the active thread.
 *   3. updateConversationSummary() fires refreshConversations() async.
 *   4. /llm/conversations returns a list that does NOT contain the new id
 *      (normal eventual-consistency lag on the backend).
 *   5. Old code nulled currentConversationId.value and wiped messages.value,
 *      so the next user send transmitted conversation_id=null, starting a
 *      brand-new thread and losing prior context.
 *
 * Contract we enforce here:
 *   - Transient 5xx / network failure on /llm/conversations → NO state mutation.
 *   - List succeeds but lacks active id → validate via GET /llm/conversation/{id}.
 *     - 2xx → keep id + messages.
 *     - 404 → clear id + messages (truly deleted).
 *     - 5xx / network → NO state mutation.
 *   - updateConversationSummary() inserts an optimistic entry into
 *     conversations.value so the active thread is visible in the sidebar
 *     immediately, before the async refresh resolves.
 */
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

vi.mock("@/stores/project", () => ({
  useProjectStore: () => ({
    currentProjectId: 7,
  }),
}));

// Stub the llm store dependency — sherpa reads wsRef for chat transport, but
// these tests only exercise the refreshConversations / updateConversationSummary
// paths, which don't touch the socket.
vi.mock("@/stores/llm", () => ({
  useLlmStore: () => ({
    wsRef: null,
    connect: vi.fn().mockResolvedValue(undefined),
    connectionStatus: "connected" as const,
  }),
}));

vi.mock("@/stores/workflow", () => ({
  useWorkflowStore: () => ({
    workflowId: null,
    workflowName: null,
    workflowDescription: null,
    currentTemplateId: null,
    nodes: [],
    edges: [],
    lastExecutionResults: null,
    lastExecutionDiagnostics: {},
    getNodeMetadata: vi.fn(() => null),
  }),
}));

vi.mock("@/stores/data", () => ({
  useDataStore: () => ({ catalogDatasetInfo: null, fileInfo: null }),
  summarizeDatasetForSherpaContext: () => null,
}));

import { useSherpaStore } from "@/stores/sherpa";

const axiosError = (status: number) => {
  const err = new Error(`Request failed with status code ${status}`);
  (err as unknown as { response: { status: number } }).response = { status };
  return err;
};

describe("Sherpa Advisor refreshConversations — thread-continuity contract", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    apiGet.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("preserves active thread when /llm/conversations fails with 5xx", async () => {
    // User has an active conversation; /llm/conversations is transiently down.
    // We must NOT wipe currentConversationId, messages, or the local
    // conversations cache — next refresh will retry.
    apiGet.mockRejectedValueOnce(axiosError(503));

    const sherpa = useSherpaStore();
    sherpa.$patch({ currentConversationId: "conv-active" });
    sherpa.$patch({ messages: [
      { role: "user", content: "hello" },
      { role: "assistant", content: "hi there" },
    ] });
    sherpa.$patch({ conversations: [{ id: "conv-active", title: "Hello", updatedAt: "t" }] });

    await sherpa.refreshConversations(7);

    expect(sherpa.currentConversationId).toBe("conv-active");
    expect(sherpa.messages).toHaveLength(2);
    expect(sherpa.conversations).toEqual([
      { id: "conv-active", title: "Hello", updatedAt: "t" },
    ]);
  });

  it("preserves active thread when list is missing the new id but GET /conversation/{id} succeeds", async () => {
    // The C1 regression scenario: eventual-consistency lag between
    // POST /llm/chat and GET /llm/conversations.
    apiGet.mockResolvedValueOnce({ data: [] }); // list: empty, active id absent
    apiGet.mockResolvedValueOnce({ data: { conversation_id: "conv-new", messages: [] } }); // probe: 2xx

    const sherpa = useSherpaStore();
    sherpa.$patch({ currentConversationId: "conv-new" });
    sherpa.$patch({ messages: [
      { role: "user", content: "what does this template do?" },
      { role: "assistant", content: "## PLS-DA Classification Workflow …" },
    ] });

    await sherpa.refreshConversations(7);

    expect(sherpa.currentConversationId).toBe("conv-new");
    expect(sherpa.messages).toHaveLength(2);
    expect(apiGet).toHaveBeenNthCalledWith(1, "/llm/conversations", expect.anything());
    expect(apiGet).toHaveBeenNthCalledWith(
      2,
      "/llm/conversation/conv-new",
      expect.anything(),
    );
  });

  it("clears state when list is missing the id AND GET /conversation/{id} 404s", async () => {
    // The conversation was genuinely deleted elsewhere. Safe to clear.
    apiGet.mockResolvedValueOnce({ data: [] });
    apiGet.mockRejectedValueOnce(axiosError(404));

    const sherpa = useSherpaStore();
    sherpa.$patch({ currentConversationId: "conv-gone" });
    sherpa.$patch({ messages: [{ role: "assistant", content: "stale content" }] });

    await sherpa.refreshConversations(7);

    expect(sherpa.currentConversationId).toBeNull();
    expect(sherpa.messages).toEqual([]);
  });

  it("preserves state when list is missing the id AND GET /conversation/{id} fails with 5xx", async () => {
    // Probe is ambiguous (upstream transient). Don't destroy state.
    apiGet.mockResolvedValueOnce({ data: [] });
    apiGet.mockRejectedValueOnce(axiosError(502));

    const sherpa = useSherpaStore();
    sherpa.$patch({ currentConversationId: "conv-active" });
    sherpa.$patch({ messages: [{ role: "assistant", content: "response text" }] });

    await sherpa.refreshConversations(7);

    expect(sherpa.currentConversationId).toBe("conv-active");
    expect(sherpa.messages).toHaveLength(1);
  });

  it("updates conversations.value from a healthy list without touching the active thread", async () => {
    // Happy path: list contains the active id. No probe call needed.
    apiGet.mockResolvedValueOnce({
      data: [
        { id: "conv-active", title: "Server Title", updated_at: "2026-04-16T00:00:00Z" },
        { id: "conv-other", title: "Other", updated_at: "2026-04-15T00:00:00Z" },
      ],
    });

    const sherpa = useSherpaStore();
    sherpa.$patch({ currentConversationId: "conv-active" });
    sherpa.$patch({ messages: [{ role: "assistant", content: "reply" }] });

    await sherpa.refreshConversations(7);

    expect(sherpa.currentConversationId).toBe("conv-active");
    expect(sherpa.messages).toHaveLength(1);
    expect(sherpa.conversations).toHaveLength(2);
    expect(sherpa.conversations[0].title).toBe("Server Title");
    expect(apiGet).toHaveBeenCalledTimes(1); // list only — no probe
  });
});

describe("Sherpa Advisor updateConversationSummary — optimistic UI", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    apiGet.mockReset();
    apiGet.mockResolvedValue({ data: [] }); // async refresh is permitted but not asserted
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("inserts the active conversation into conversations.value before the async refresh resolves", () => {
    const sherpa = useSherpaStore();
    sherpa.$patch({ currentConversationId: "conv-new" });
    sherpa.$patch({ messages: [
      { role: "user", content: "tell me what this template does" },
      { role: "assistant", content: "..." },
    ] });

    // Synchronous call — no await. The optimistic insert must land before
    // the internal refreshConversations() promise resolves.
    sherpa.updateConversationSummary("conv-new");

    expect(sherpa.conversations.some((c) => c.id === "conv-new")).toBe(true);
    const entry = sherpa.conversations.find((c) => c.id === "conv-new")!;
    expect(entry.title).toBe("tell me what this template does");
  });

  it("updates timestamp of an existing entry without clobbering its title", () => {
    const sherpa = useSherpaStore();
    sherpa.$patch({ conversations: [
      { id: "conv-known", title: "Server-assigned title", updatedAt: "old" },
    ] });
    sherpa.$patch({ currentConversationId: "conv-known" });
    sherpa.$patch({ messages: [{ role: "user", content: "follow-up question" }] });

    sherpa.updateConversationSummary("conv-known");

    const entry = sherpa.conversations.find((c) => c.id === "conv-known")!;
    expect(entry.title).toBe("Server-assigned title"); // not overwritten
    expect(entry.updatedAt).not.toBe("old"); // refreshed
  });
});
