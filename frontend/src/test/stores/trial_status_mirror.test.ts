import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("@/api/client", () => ({ default: apiMock }));

vi.mock("@/stores/job", () => ({
  useJobStore: () => ({}),
}));

vi.mock("@/stores/project", () => ({
  useProjectStore: () => ({
    currentProjectId: 1,
    removeWorkflowFromCurrentProject: vi.fn(),
  }),
}));

vi.mock("@/stores/advisor", () => ({
  useAdvisorStore: () => ({ switchScope: vi.fn() }),
}));

import { useWorkbookStore } from "@/stores/workbook";
import { useWorkflowStore } from "@/stores/workflow";

const makeSheet = (overrides: Record<string, unknown> = {}) =>
  ({
    workflowId: 1,
    name: "Sheet",
    tabColor: null,
    sheetOrder: 0,
    executionStatus: "idle" as const,
    ...overrides,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- WorkbookSheet test fixture.
  }) as any;

describe("trial-sheet executionStatus mirroring", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  it("executeStoredWorkflow mirrors running/success status onto trial sheets", async () => {
    const workbook = useWorkbookStore();
    const workflow = useWorkflowStore();

    workbook.sheets = [
      makeSheet({ workflowId: 7, name: "Source" }),
      makeSheet({
        workflowId: -1,
        kind: "trial",
        trialId: "trial-1",
        sourceWorkflowId: 7,
        name: "Trial of Source",
      }),
      makeSheet({
        workflowId: -2,
        kind: "trial",
        trialId: "trial-2",
        sourceWorkflowId: 99,
        name: "Trial of unrelated",
      }),
    ];

    let resolveExec: ((v: unknown) => void) | undefined;
    apiMock.post.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveExec = resolve;
        }),
    );

    const promise = workflow.executeStoredWorkflow(7);
    // The synchronous "running" assignment fires before the await resolves.
    await Promise.resolve();
    expect(workbook.sheets[0].executionStatus).toBe("running");
    expect(workbook.sheets[1].executionStatus).toBe("running"); // mirrored
    expect(workbook.sheets[2].executionStatus).toBe("idle"); // unrelated trial untouched

    resolveExec?.({ data: { status: "success" } });
    await promise;

    expect(workbook.sheets[0].executionStatus).toBe("success");
    expect(workbook.sheets[1].executionStatus).toBe("success");
    expect(workbook.sheets[2].executionStatus).toBe("idle");

    // After 3 s the terminal status clears.
    vi.advanceTimersByTime(3001);
    expect(workbook.sheets[0].executionStatus).toBe("idle");
    expect(workbook.sheets[1].executionStatus).toBe("idle");
  });

  it("executeStoredWorkflow mirrors error status onto trial sheets", async () => {
    const workbook = useWorkbookStore();
    const workflow = useWorkflowStore();

    workbook.sheets = [
      makeSheet({ workflowId: 7 }),
      makeSheet({
        workflowId: -1,
        kind: "trial",
        trialId: "trial-1",
        sourceWorkflowId: 7,
      }),
    ];

    apiMock.post.mockRejectedValueOnce(new Error("boom"));

    await expect(workflow.executeStoredWorkflow(7)).rejects.toThrow("boom");
    expect(workbook.sheets[0].executionStatus).toBe("error");
    expect(workbook.sheets[1].executionStatus).toBe("error");
  });
});
