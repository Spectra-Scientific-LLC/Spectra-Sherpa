import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import api from "@/api/client";
import { useDataSourceStore } from "@/stores/dataSources";

vi.mock("@/api/client", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));

describe("useDataSourceStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
    vi.mocked(api.put).mockReset();
  });

  it("loads project data sources from the dedicated endpoint", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [
        {
          id: 1,
          project_id: 7,
          display_name: "Iris",
          source_type: "example",
          source_ref: "sklearn:iris",
          fingerprint: "sklearn:iris",
          color: "#3b82f6",
          metadata: {},
          sort_order: 0,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
    });

    const store = useDataSourceStore();
    const result = await store.loadProjectDataSources(7);

    expect(api.get).toHaveBeenCalledWith("/projects/7/data-sources");
    expect(result).toHaveLength(1);
    expect(store.byId.get(1)?.display_name).toBe("Iris");
  });

  it("updates one data source in local state", async () => {
    const store = useDataSourceStore();
    store.setFromProjectDetail(7, [
      {
        id: 1,
        project_id: 7,
        display_name: "Old",
        source_type: "example",
        source_ref: null,
        fingerprint: null,
        color: "#3b82f6",
        metadata: {},
        sort_order: 0,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ]);
    vi.mocked(api.put).mockResolvedValue({
      data: {
        ...store.dataSources[0],
        display_name: "Renamed",
      },
    });

    await store.updateDataSource(7, 1, { display_name: "Renamed" });

    expect(api.put).toHaveBeenCalledWith("/projects/7/data-sources/1", {
      display_name: "Renamed",
    });
    expect(store.dataSources[0].display_name).toBe("Renamed");
  });
});
