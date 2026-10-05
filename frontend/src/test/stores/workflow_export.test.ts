import { beforeEach, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import api from "@/api/client";
import { useWorkflowStore } from "@/stores/workflow";

vi.mock("@/api/client", () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => ({ user: { id: 6 } }) }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => ({ currentProjectId: 1 }) }));
vi.mock("@/stores/projectProvenance", () => ({
  useProjectProvenanceStore: () => ({ refresh: vi.fn().mockResolvedValue(undefined) }),
}));
vi.mock("@/utils/download", () => ({
  downloadBlob: vi.fn(), blobFromResponseData: vi.fn(), filenameFromContentDisposition: vi.fn(),
}));

beforeEach(() => {
  setActivePinia(createPinia());
  vi.resetAllMocks();
  vi.mocked(api.put).mockResolvedValue({ data: { id: 101, integrity_hash: "saved" } });
  vi.mocked(api.post).mockResolvedValue({ data: { semantic_edges: [], issues: [] } });
  vi.mocked(api.get).mockResolvedValue({ data: { python_code: "current", notebook: {} }, headers: {} });
});

const formats = ["exportToPython", "exportToNotebook", "downloadExport"] as const;

it.each(formats)("%s saves dirty workflows before export", async (format) => {
  const store = useWorkflowStore();
  store.workflowId = 101;
  store.hasUnsavedChanges = true;
  await store[format]();
  expect(api.put).toHaveBeenCalledOnce();
  expect(vi.mocked(api.put).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(api.get).mock.invocationCallOrder[0]);
  expect(store.hasUnsavedChanges).toBe(false);
});

it.each(formats)("%s blocks export after a failed save", async (format) => {
  const store = useWorkflowStore();
  store.workflowId = 101;
  store.hasUnsavedChanges = true;
  vi.mocked(api.put).mockRejectedValue(new Error("save rejected"));
  await expect(store[format]()).rejects.toThrow("save rejected");
  expect(api.get).not.toHaveBeenCalled();
});

it.each(formats)("%s does not resave a clean workflow", async (format) => {
  const store = useWorkflowStore();
  store.workflowId = 101;
  store.hasUnsavedChanges = false;
  await store[format]();
  expect(api.put).not.toHaveBeenCalled();
  expect(api.get).toHaveBeenCalledOnce();
});

it("waits for an in-flight save and saves edits made during it", async () => {
  const store = useWorkflowStore();
  store.workflowId = 101;
  store.hasUnsavedChanges = true;
  let complete!: (value: unknown) => void;
  vi.mocked(api.put).mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
  const saving = store.saveWorkflow();
  store.workflowName = "Newer edit";
  const exporting = store.exportToPython();
  expect(api.get).not.toHaveBeenCalled();
  complete({ data: { id: 101 } });
  await saving;
  await exporting;
  expect(api.put).toHaveBeenCalledTimes(2);
  expect(api.get).toHaveBeenCalledOnce();
});

it("blocks export when edits change during its own save", async () => {
  const store = useWorkflowStore();
  store.workflowId = 101;
  store.hasUnsavedChanges = true;
  let complete!: (value: unknown) => void;
  vi.mocked(api.put).mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
  const exporting = store.exportToPython();
  store.workflowName = "Still editing";
  complete({ data: { id: 101 } });
  await expect(exporting).rejects.toThrow("Workflow changed while saving");
  expect(api.get).not.toHaveBeenCalled();
});
