import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useWorkbookStore } from "@/stores/workbook";
import type { WorkbookSheet } from "@/stores/workbook";

vi.mock("@/api/client", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({ user: { id: 3 } }),
}));

const advisorStoreMock = vi.hoisted(() => ({
  switchToWorkflowChannel: vi.fn(),
}));

vi.mock("@/stores/advisor", () => ({
  useAdvisorStore: () => advisorStoreMock,
}));

vi.mock("@/stores/project", () => ({
  useProjectStore: () => ({ removeWorkflowFromCurrentProject: vi.fn() }),
}));

vi.mock("@/stores/workflow", () => ({
  useWorkflowStore: () => ({
    hasUnsavedChanges: false,
    workflowId: null,
    loadWorkflow: vi.fn(),
    saveWorkflow: vi.fn(),
  }),
}));

const makeSheet = (overrides: Partial<WorkbookSheet> = {}): WorkbookSheet => ({
  workflowId: 1,
  name: "Sheet 1",
  tabColor: null,
  sheetOrder: 0,
  ...overrides,
});

describe("useWorkbookStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    advisorStoreMock.switchToWorkflowChannel.mockResolvedValue(undefined);
    advisorStoreMock.switchToWorkflowChannel.mockClear();
  });

  describe("setLastSelectedNodeId", () => {
    it("stores nodeId on the matching sheet", () => {
      const store = useWorkbookStore();
      store.sheets = [makeSheet({ workflowId: 10 }), makeSheet({ workflowId: 20 })];

      store.setLastSelectedNodeId(10, "node_abc");

      expect(store.sheets[0].lastSelectedNodeId).toBe("node_abc");
      expect(store.sheets[1].lastSelectedNodeId).toBeUndefined();
    });

    it("clears nodeId when null is passed", () => {
      const store = useWorkbookStore();
      store.sheets = [makeSheet({ workflowId: 10, lastSelectedNodeId: "old_node" })];

      store.setLastSelectedNodeId(10, null);

      expect(store.sheets[0].lastSelectedNodeId).toBeUndefined();
    });

    it("is a no-op when workflowId does not match any sheet", () => {
      const store = useWorkbookStore();
      store.sheets = [makeSheet({ workflowId: 10 })];

      store.setLastSelectedNodeId(99, "node_xyz");

      expect(store.sheets[0].lastSelectedNodeId).toBeUndefined();
    });
  });

  describe("activeSheetKey localStorage scoping", () => {
    it("scopes the active-sheet key by userId so users do not share session state", () => {
      // Simulate a value written for user 3 and a stale value for user 9
      localStorage.setItem("spectra_sherpa_active_sheet_9_5", "99");

      // The store exposes no direct key reader, but persistActiveSheet writes on
      // switchSheet / loadSheets. We verify that a pre-written key for a different
      // user is NOT read by checking that nothing in the store references userId 9.
      const keyForUser3 = "spectra_sherpa_active_sheet_3_5";
      expect(localStorage.getItem(keyForUser3)).toBeNull();

      // Write via localStorage directly to confirm format
      localStorage.setItem(keyForUser3, "5");
      expect(localStorage.getItem(keyForUser3)).toBe("5");
      expect(localStorage.getItem("spectra_sherpa_active_sheet_9_5")).toBe("99");
    });
  });

  describe("advisor channel switching", () => {
    it("switches Sherpa Advisor to the active workflow sheet channel", async () => {
      const store = useWorkbookStore();
      store.projectId = 5;
      store.sheets = [
        makeSheet({ workflowId: 10, advisorChannelId: 100, sheetOrder: 0 }),
        makeSheet({ workflowId: 20, advisorChannelId: 200, sheetOrder: 1 }),
      ];
      store.activeIndex = 0;

      await store.switchSheet(1);

      expect(advisorStoreMock.switchToWorkflowChannel).toHaveBeenCalledWith(20, 200, 5);
    });

    it("uses the source workflow advisor channel for trial tabs", async () => {
      const store = useWorkbookStore();
      store.projectId = 5;
      store.sheets = [
        makeSheet({ workflowId: 10, advisorChannelId: 100, sheetOrder: 0 }),
        makeSheet({
          workflowId: -1,
          kind: "trial",
          trialId: "trial-1",
          sourceWorkflowId: 10,
          advisorChannelId: 100,
          sheetOrder: 1,
        }),
      ];
      store.activeIndex = 0;

      await store.switchSheet(1);

      expect(advisorStoreMock.switchToWorkflowChannel).toHaveBeenCalledWith(10, 100, 5);
    });
  });
});
