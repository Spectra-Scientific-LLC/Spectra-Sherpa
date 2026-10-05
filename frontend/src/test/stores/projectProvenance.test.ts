import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import api from "@/api/client";
import { availabilityState, availabilityDetail, useProjectProvenanceStore, type ProjectProvenanceRecord } from "@/stores/projectProvenance";

vi.mock("@/api/client", () => ({ default: { get: vi.fn() } }));

describe("Basic availability lights", () => {
  const record: ProjectProvenanceRecord = {
    kind: "model", label: "Calibrated model", state: "faulty", name: "PLS",
    digest: null, record_id: "model", detail: "No active dataset selection", destination: "/runs",
    availability: { state: "healthy", detail: "Active model files available." },
  };
  it("does not color a stored model red for incomplete provenance", () => {
    expect(availabilityState(record)).toBe("healthy");
    expect(availabilityDetail(record)).toBe("Active model files available.");
  });
  it("reports missing model files independently of complete provenance", () => {
    expect(availabilityState({ ...record, state: "healthy", availability: { state: "faulty", detail: "Missing files" } })).toBe("faulty");
  });
  it("does not mistake an old server's provenance state for availability", () => {
    expect(availabilityState({ ...record, availability: undefined })).toBe("missing");
  });
});

describe("Project provenance refresh", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("shares simultaneous full checks for one project", async () => {
    let complete!: (value: { data: unknown }) => void;
    vi.mocked(api.get).mockReturnValueOnce(new Promise((resolve) => { complete = resolve; }));
    const store = useProjectProvenanceStore();
    const first = store.refresh(7);
    const second = store.refresh(7);
    expect(api.get).toHaveBeenCalledTimes(1);
    complete({ data: { project_id: 7, project_name: "Corn", verified_at: "2026-10-04T00:00:00Z", records: [], choice_event_ids: {} } });
    await Promise.all([first, second]);
    expect(store.summary?.project_id).toBe(7);
  });

  it("rechecks live after an in-flight cached summary", async () => {
    let complete!: (value: { data: unknown }) => void;
    vi.mocked(api.get).mockReturnValueOnce(new Promise((resolve) => { complete = resolve; }));
    vi.mocked(api.get).mockResolvedValueOnce({ data: { project_id: 7, project_name: "Corn", verified_at: "2026-10-04T00:00:01Z", records: [], choice_event_ids: {} } });
    const store = useProjectProvenanceStore();
    const cached = store.refresh(7, false);
    const live = store.refresh(7, true);
    complete({ data: { project_id: 7, project_name: "Corn", verified_at: "2026-10-04T00:00:00Z", records: [], choice_event_ids: {} } });
    await Promise.all([cached, live]);
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(store.summary?.verified_at).toBe("2026-10-04T00:00:01Z");
  });

  it("does not restore an old project after switching during a queued full check", async () => {
    let complete!: (value: { data: unknown }) => void;
    vi.mocked(api.get).mockReturnValueOnce(new Promise((resolve) => { complete = resolve; }));
    vi.mocked(api.get).mockResolvedValueOnce({ data: { project_id: 8, project_name: "Lavender", verified_at: "2026-10-04T00:00:01Z", records: [], choice_event_ids: {} } });
    const store = useProjectProvenanceStore();
    const cached = store.refresh(7, false);
    const queued = store.refresh(7, true);
    const switched = store.refresh(8, true);
    complete({ data: { project_id: 7, project_name: "Corn", verified_at: "2026-10-04T00:00:00Z", records: [], choice_event_ids: {} } });
    await Promise.all([cached, queued, switched]);
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(store.projectId).toBe(8);
    expect(store.summary?.project_name).toBe("Lavender");
  });
});
