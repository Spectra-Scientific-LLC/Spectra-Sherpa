import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it, vi } from "vitest";
import { buildDataStoryContext } from "@/lib/dataStoryFacts";
import { useDataStore } from "@/stores/data";
import { SHERPA_WS_EVENT } from "@/lib/sherpaWs";

const transport = vi.hoisted(() => ({
  send: vi.fn(), listener: null as null | ((payload: Record<string, unknown>) => void),
}));
vi.mock("@/api/client", () => ({ default: { post: vi.fn() } }));
vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({ appMode: { value: "enterprise" }, isFeatureEnabled: () => true }),
}));
vi.mock("@/stores/sherpa", () => ({ useSherpaStore: () => ({ isSyncing: false, isChatting: false }) }));
vi.mock("@/stores/llm", () => ({ useLlmStore: () => ({
  connect: vi.fn(), wsRef: { readyState: 1, send: transport.send },
}) }));
vi.mock("@/stores/advisor", () => ({ useAdvisorStore: () => ({ activeNodeId: 42 }) }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => ({ currentProjectId: 7 }) }));
vi.mock("@/lib/sherpaEvents", () => ({
  createSherpaRequestId: () => "story-test",
  subscribeSherpaEvents: (listener: (payload: Record<string, unknown>) => void) => {
    transport.listener = listener;
    return vi.fn();
  },
}));

describe("hosted Data Story transport", () => {
  it("sends shared parsed facts and the specific question with existing project scope", async () => {
    setActivePinia(createPinia());
    transport.send.mockImplementation(() => transport.listener?.({
      type: SHERPA_WS_EVENT.dataStoryResult, response: "Recorded acquisition summary.",
    }));
    const parsed = {
      title: "Lavender", is_spectra: true, domain: { instrument: "Thermo Nicolet OMNIC" },
      metadata: { "omnic.acquisition": { scan_count: 16 } },
      x_axis: { data: [4000, 2000, 400], units: "cm^-1" },
    };
    const store = useDataStore();
    store.dataStoryContext = "How were these data acquired?";
    await store.generateDataStory(parsed as unknown as Parameters<typeof store.generateDataStory>[0]);
    const request = JSON.parse(transport.send.mock.calls[0][0]);
    expect(request.payload).toEqual({
      request_id: "story-test", project_id: 7, advisor_node_id: 42,
      dataset_info: buildDataStoryContext(parsed), additional_context: "How were these data acquired?",
    });
    expect(store.dataStoryText).toBe("Recorded acquisition summary.");
    expect(store.dataStoryLoading).toBe(false);
  });
});
