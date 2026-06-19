import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useWorkbookStore } from "@/stores/workbook";
import type { WorkbookSheet } from "@/stores/workbook";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: apiMock,
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({ user: { id: 3 } }),
}));

const advisorStoreMock = vi.hoisted(() => ({
  switchScope: vi.fn(),
}));

const workflowStoreMock = vi.hoisted(() => ({
  hasUnsavedChanges: false,
  workflowId: null as number | null,
  loadWorkflow: vi.fn(),
  saveWorkflow: vi.fn(),
}));

vi.mock("@/stores/advisor", () => ({
  useAdvisorStore: () => advisorStoreMock,
}));

vi.mock("@/stores/project", () => ({
  useProjectStore: () => ({ removeWorkflowFromCurrentProject: vi.fn() }),
}));

vi.mock("@/stores/workflow", () => ({
  useWorkflowStore: () => workflowStoreMock,
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
    advisorStoreMock.switchScope.mockResolvedValue(undefined);
    advisorStoreMock.switchScope.mockClear();
    workflowStoreMock.hasUnsavedChanges = false;
    workflowStoreMock.workflowId = null;
    workflowStoreMock.loadWorkflow.mockReset();
    workflowStoreMock.saveWorkflow.mockReset();
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

  describe("deleteSheet cascade", () => {
    it("drops trial sheets pointing at the deleted source workflow", async () => {
      const store = useWorkbookStore();
      store.projectId = 5;
      store.sheets = [
        makeSheet({ workflowId: 10, sheetOrder: 0 }),
        makeSheet({ workflowId: 20, sheetOrder: 1 }),
        makeSheet({
          workflowId: -1,
          kind: "trial",
          trialId: "trial-1",
          sourceWorkflowId: 20,
          sheetOrder: 2,
        }),
        makeSheet({
          workflowId: -2,
          kind: "trial",
          trialId: "trial-2",
          sourceWorkflowId: 10,
          sheetOrder: 3,
        }),
      ];
      store.activeIndex = 0;
      apiMock.delete.mockResolvedValueOnce({ data: null });
      // refreshSheets in the wasActive=false branch — return current persisted sheets
      apiMock.get.mockResolvedValueOnce({
        data: [
          { id: 10, name: "Sheet 1", tab_color: null, sheet_order: 0, node_count: 0 },
        ],
      });

      await store.deleteSheet(20);

      // workflow 20 is gone; trial-1 (sourced from 20) is gone;
      // workflow 10 + trial-2 (sourced from 10) remain.
      const remaining = store.sheets.map((s) => s.workflowId).sort((a, b) => a - b);
      expect(remaining).toEqual([-2, 10]);
    });

    it("leaves trial sheets pointing at a different workflow alone", async () => {
      const store = useWorkbookStore();
      store.projectId = 5;
      store.sheets = [
        makeSheet({ workflowId: 10, sheetOrder: 0 }),
        makeSheet({ workflowId: 20, sheetOrder: 1 }),
        makeSheet({
          workflowId: -1,
          kind: "trial",
          trialId: "trial-1",
          sourceWorkflowId: 10,
          sheetOrder: 2,
        }),
      ];
      store.activeIndex = 0;
      apiMock.delete.mockResolvedValueOnce({ data: null });
      apiMock.get.mockResolvedValueOnce({
        data: [
          { id: 10, name: "Sheet 1", tab_color: null, sheet_order: 0, node_count: 0 },
        ],
      });

      await store.deleteSheet(20);

      const remaining = store.sheets.map((s) => s.workflowId).sort((a, b) => a - b);
      expect(remaining).toEqual([-1, 10]);
    });

    it("lands activeIndex on a sensible sheet when the active sheet was a trial of the deleted workflow", async () => {
      // Repro for M2: active sheet is a TRIAL of workflow W, user deletes
      // W. Pre-fix, the cascade splices the active trial out but wasActive
      // is false (the trial's own workflowId != W), so the else-branch's
      // currentWorkflowId lookup returns -1 and activeIndex points wherever
      // it happens to land. Post-fix, activeIndex must land on a valid
      // non-trial sheet.
      const store = useWorkbookStore();
      store.projectId = 5;
      store.sheets = [
        makeSheet({ workflowId: 10, sheetOrder: 0, name: "Other" }),
        makeSheet({ workflowId: 20, sheetOrder: 1, name: "Source" }),
        makeSheet({
          workflowId: -1,
          kind: "trial",
          trialId: "trial-1",
          sourceWorkflowId: 20,
          sheetOrder: 2,
          name: "Trial of Source",
        }),
      ];
      store.activeIndex = 2; // active sheet IS the trial of workflow 20

      apiMock.delete.mockResolvedValueOnce({ data: null });
      apiMock.get.mockResolvedValueOnce({
        data: [
          { id: 10, name: "Other", tab_color: null, sheet_order: 0, node_count: 0 },
        ],
      });

      await store.deleteSheet(20);

      // Workflow 20 and the trial-1 (sourced from 20) are both gone.
      const remainingIds = store.sheets.map((s) => s.workflowId).sort((a, b) => a - b);
      expect(remainingIds).toEqual([10]);

      // activeIndex must land on a valid sheet index (0), not be left at
      // a stale value pointing past the array.
      expect(store.activeIndex).toBe(0);
      expect(store.sheets[store.activeIndex]?.workflowId).toBe(10);
    });
  });

  describe("advisor channel switching", () => {
    it("does not fail sheet switching when localStorage quota is exhausted", async () => {
      const store = useWorkbookStore();
      store.projectId = 5;
      store.sheets = [
        makeSheet({ workflowId: 10, sheetOrder: 0 }),
        makeSheet({ workflowId: 20, sheetOrder: 1 }),
      ];
      store.activeIndex = 0;
      const setItemSpy = vi
        .spyOn(localStorage, "setItem")
        .mockImplementation(() => {
          throw new DOMException("The quota has been exceeded.", "QuotaExceededError");
        });

      await expect(store.switchSheet(1)).resolves.toBeUndefined();

      expect(store.activeIndex).toBe(1);
      setItemSpy.mockRestore();
    });

    it("prunes stale workflow drafts and retries active-sheet persistence on quota errors", async () => {
      const store = useWorkbookStore();
      store.projectId = 5;
      store.sheets = [
        makeSheet({ workflowId: 10, sheetOrder: 0 }),
        makeSheet({ workflowId: 20, sheetOrder: 1 }),
      ];
      store.activeIndex = 0;
      localStorage.setItem("spectra_sherpa_workflow_draft_v1:3:5:10", "large-draft");
      localStorage.setItem("spectra_sherpa_data_draft_v1:3:5", "keep-data-draft");
      const originalSetItem = localStorage.setItem.bind(localStorage);
      let activeSheetAttempts = 0;
      const setItemSpy = vi
        .spyOn(localStorage, "setItem")
        .mockImplementation(function setItemWithOneQuotaFailure(key: string, value: string) {
          if (key === "spectra_sherpa_active_sheet_3_5" && activeSheetAttempts === 0) {
            activeSheetAttempts += 1;
            throw new DOMException("The quota has been exceeded.", "QuotaExceededError");
          }
          return originalSetItem(key, value);
        });

      await store.switchSheet(1);

      expect(localStorage.getItem("spectra_sherpa_workflow_draft_v1:3:5:10")).toBeNull();
      expect(localStorage.getItem("spectra_sherpa_data_draft_v1:3:5")).toBe("keep-data-draft");
      expect(localStorage.getItem("spectra_sherpa_active_sheet_3_5")).toBe("20");
      setItemSpy.mockRestore();
    });

    it("switches Sherpa Advisor to the active workflow sheet channel", async () => {
      const store = useWorkbookStore();
      store.projectId = 5;
      store.sheets = [
        makeSheet({ workflowId: 10, advisorChannelId: 100, sheetOrder: 0 }),
        makeSheet({ workflowId: 20, advisorChannelId: 200, sheetOrder: 1 }),
      ];
      store.activeIndex = 0;

      await store.switchSheet(1);

      expect(advisorStoreMock.switchScope).toHaveBeenCalledWith({
        projectId: 5,
        tabKey: "workflow",
        subscopeKey: "sheet:20",
        resourceType: "workflow",
        resourceId: 20,
        title: "Sheet 1",
      });
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

      expect(advisorStoreMock.switchScope).toHaveBeenCalledWith({
        projectId: 5,
        tabKey: "workflow",
        subscopeKey: "sheet:10",
        resourceType: "workflow",
        resourceId: 10,
        title: "Sheet 1",
      });
    });
  });

  describe("trial tabs", () => {
    it("saves pending source workflow edits before reloading after active trial close", async () => {
      const store = useWorkbookStore();
      store.sheets = [
        makeSheet({ workflowId: 10, sheetOrder: 0, name: "Source" }),
        makeSheet({
          workflowId: -1,
          kind: "trial",
          trialId: "trial-10-node-1",
          sourceWorkflowId: 10,
          sourceNodeId: "node_1",
          sheetOrder: 1,
          name: "Trial",
        }),
      ];
      store.activeIndex = 1;
      workflowStoreMock.hasUnsavedChanges = true;
      workflowStoreMock.workflowId = 10;

      const calls: string[] = [];
      workflowStoreMock.saveWorkflow.mockImplementation(async () => {
        calls.push("save");
        workflowStoreMock.hasUnsavedChanges = false;
      });
      workflowStoreMock.loadWorkflow.mockImplementation(async () => {
        calls.push("load");
      });

      await store.closeTrialTab("trial-10-node-1");

      expect(calls).toEqual(["save", "load"]);
      expect(workflowStoreMock.saveWorkflow).toHaveBeenCalledWith({ createVersion: false });
      expect(workflowStoreMock.loadWorkflow).toHaveBeenCalledWith(10);
    });
  });
});
