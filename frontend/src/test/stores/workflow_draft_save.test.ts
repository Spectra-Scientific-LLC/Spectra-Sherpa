import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import api from "@/api/client";
import { useWorkflowStore } from "@/stores/workflow";
import { workflowDraftKey } from "@/utils/workflowDraft";

vi.mock("@/api/client", () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => ({ user: { id: 6 } }) }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => ({ currentProjectId: 1 }) }));

describe("server save recovery lifecycle", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    localStorage.clear();
    vi.mocked(api.post).mockResolvedValue({ data: { semantic_edges: [], issues: [] } });
  });

  function prepareDraft() {
    const store = useWorkflowStore();
    store.workflowId = 101;
    store.nodes = [
      {
        id: "clip_new",
        type: "preprocess.clip_range",
        x: 100,
        y: 100,
        params: { minimum: 600, maximum: 1400 },
      },
    ];
    store.hasUnsavedChanges = true;
    const key = workflowDraftKey(6, 1, 101);
    localStorage.setItem(
      key,
      JSON.stringify({
        workflowName: store.workflowName,
        workflowDescription: store.workflowDescription,
        nodes: store.nodes,
        edges: [],
      }),
    );
    return { store, key };
  }

  it.each([true, false])(
    "clears a newly inserted node draft after save (createVersion=%s)",
    async (createVersion) => {
      const { store, key } = prepareDraft();
      vi.mocked(api.put).mockResolvedValue({ data: { id: 101, integrity_hash: "saved" } });
      await store.saveWorkflow({ createVersion });
      expect(localStorage.getItem(key)).toBeNull();
      expect(store.hasUnsavedChanges).toBe(false);
      expect(store.nodes[0].params).toEqual({ minimum: 600, maximum: 1400 });
    },
  );

  it("preserves the recovery draft when saving fails", async () => {
    const { store, key } = prepareDraft();
    const before = localStorage.getItem(key);
    vi.mocked(api.put).mockRejectedValue(new Error("offline"));
    await expect(store.saveWorkflow()).rejects.toThrow("offline");
    expect(localStorage.getItem(key)).toBe(before);
    expect(store.hasUnsavedChanges).toBe(true);
  });

  it("does not mark edits made during a save as already saved", async () => {
    const { store, key } = prepareDraft();
    vi.mocked(api.put).mockImplementationOnce(async () => {
      store.nodes[0].params.maximum = 1500;
      localStorage.setItem(
        key,
        JSON.stringify({
          workflowName: store.workflowName,
          workflowDescription: store.workflowDescription,
          nodes: store.nodes,
          edges: [],
        }),
      );
      return { data: { id: 101 } };
    });
    await store.saveWorkflow();
    expect(store.hasUnsavedChanges).toBe(true);
    expect(JSON.parse(localStorage.getItem(key)!).nodes[0].params.maximum).toBe(1500);
  });
});
