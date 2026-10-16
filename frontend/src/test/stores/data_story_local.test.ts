import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import api from "@/api/client";
import { streamLocalDataStory } from "@/lib/localDataStory";
import { useDataStore } from "@/stores/data";

vi.mock("@/api/client", () => ({ default: { post: vi.fn() } }));
vi.mock("@/lib/localDataStory", () => ({ streamLocalDataStory: vi.fn() }));
vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appMode: { value: "local" },
    isFeatureEnabled: (feature: string) => feature === "chatAssistant",
  }),
}));

describe("local Data Story", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("uses the already-inspected source, caches its story, and regenerates only on request", async () => {
    const parsed = { title: "Corn M5", data: [[1, 2]], metadata: { prop_names: ["Moisture"] } };
    vi.mocked(streamLocalDataStory).mockImplementation(async (_info, _question, onChunk) => {
      onChunk("Corn M5 ");
      onChunk("contains spectra.");
      return "Corn M5 contains spectra.";
    });
    const store = useDataStore();
    store.dataStoryContext = "What does Moisture mean?";
    const source = parsed as unknown as Parameters<typeof store.generateDataStory>[0];
    await store.generateDataStory(source, { cacheKey: "source-11-12" });

    expect(api.post).not.toHaveBeenCalled();
    expect(streamLocalDataStory).toHaveBeenCalledWith(
      parsed, "What does Moisture mean?", expect.any(Function), expect.any(AbortSignal),
    );
    expect(store.dataStoryText).toBe("Corn M5 contains spectra.");
    expect(store.dataStoryLoading).toBe(false);
    store.invalidateDataStory();
    await store.generateDataStory(source, { cacheKey: "source-11-12" });
    expect(api.post).not.toHaveBeenCalled();
    expect(streamLocalDataStory).toHaveBeenCalledTimes(1);
    expect(store.dataStoryText).toBe("Corn M5 contains spectra.");
    await store.generateDataStory(source, { cacheKey: "source-11-12", force: true });
    expect(api.post).not.toHaveBeenCalled();
    expect(streamLocalDataStory).toHaveBeenCalledTimes(2);
  });
});
