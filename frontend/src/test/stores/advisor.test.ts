import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import api from "@/api/client";
import { useAdvisorStore } from "@/stores/advisor";

const profile = vi.hoisted(() => ({ value: "local" }));
vi.mock("@/composables/useAppConfig", () => ({ useAppConfig: () => ({
  appMode: { value: profile.value === "pro" ? "enterprise" : "local" }, siteProfile: profile,
}) }));
vi.mock("@/api/client", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));

const sherpaStoreMock = {
  loadConversation: vi.fn(),
  startNewConversation: vi.fn(),
};

vi.mock("@/stores/sherpa", () => ({
  useSherpaStore: () => sherpaStoreMock,
}));

describe("useAdvisorStore", () => {
  beforeEach(() => {
    profile.value = "local";
    setActivePinia(createPinia());
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
    vi.mocked(api.put).mockReset();
    sherpaStoreMock.loadConversation.mockReset();
    sherpaStoreMock.startNewConversation.mockReset();
  });

  it("does not start an unqualified Pro memory scope or replace project chat", async () => {
    profile.value = "pro";
    const store = useAdvisorStore();
    expect(await store.switchScope({ projectId: 5, tabKey: "data", subscopeKey: "files" })).toBeNull();
    expect(store.activeNodeId).toBeNull();
    expect(store.topics).toEqual([]);
    expect(api.post).not.toHaveBeenCalled();
    expect(sherpaStoreMock.startNewConversation).not.toHaveBeenCalled();
  });
  it("loads an existing sheet channel conversation on workflow switch", async () => {
    const store = useAdvisorStore();
    store.setFromProjectDetail(5, [
      {
        id: 20,
        project_id: 5,
        workflow_id: 10,
        channel_type: "sheet",
        title: "PCA",
        color: "#3b82f6",
        conversation_id: "conv-pca",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ]);

    await store.switchToWorkflowChannel(10, 20, 5);

    expect(store.activeChannelId).toBe(20);
    expect(sherpaStoreMock.loadConversation).toHaveBeenCalledWith("conv-pca");
    expect(sherpaStoreMock.startNewConversation).not.toHaveBeenCalled();
  });

  it("creates a sheet channel when the workbook sheet lacks one", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: {
        id: 30,
        project_id: 5,
        workflow_id: 10,
        channel_type: "sheet",
        title: "PLS",
        color: "#22c55e",
        conversation_id: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    });

    const store = useAdvisorStore();
    store.projectId = 5;
    await store.switchToWorkflowChannel(10, null, 5);

    expect(api.post).toHaveBeenCalledWith("/workflows/10/advisor-channel");
    expect(store.activeChannelId).toBe(30);
    expect(sherpaStoreMock.startNewConversation).toHaveBeenCalled();
  });

  it("updates channel conversation binding through the dedicated endpoint", async () => {
    const store = useAdvisorStore();
    store.setFromProjectDetail(5, [
      {
        id: 20,
        project_id: 5,
        workflow_id: 10,
        channel_type: "sheet",
        title: "PCA",
        color: "#3b82f6",
        conversation_id: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ]);
    vi.mocked(api.put).mockResolvedValue({
      data: {
        ...store.channels[0],
        conversation_id: "conv-new",
      },
    });

    await store.updateChannel(20, { conversation_id: "conv-new" });

    expect(api.put).toHaveBeenCalledWith("/projects/5/advisor-channels/20", {
      conversation_id: "conv-new",
    });
  });

});
