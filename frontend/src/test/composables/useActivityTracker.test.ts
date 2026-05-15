import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, nextTick, onBeforeUnmount, onMounted, reactive } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useActivityTracker } from "@/composables/useActivityTracker";

const mocks = vi.hoisted(() => ({
  route: { path: "/project", fullPath: "/project" },
  appMode: { __v_isRef: true, value: "enterprise" },
  isFeatureEnabled: vi.fn((feature: string) => feature === "sherpaGuidance"),
  guidanceStore: {
    isEnabled: true,
    acknowledgeActionClick: vi.fn().mockResolvedValue(undefined),
  },
  wsSend: vi.fn(),
  llmStore: {
    wsRef: null as WebSocket | null,
    connect: vi.fn(),
  },
  projectStore: {
    currentProjectId: 17,
  } as { currentProjectId: number | null },
  advisorStore: {
    activeNodeId: 23,
  },
}));

vi.mock("vue-router", () => ({
  useRoute: () => mocks.route,
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appMode: mocks.appMode,
    isFeatureEnabled: mocks.isFeatureEnabled,
  }),
}));

vi.mock("@/stores/guidance", () => ({
  useGuidanceStore: () => mocks.guidanceStore,
}));

vi.mock("@/stores/llm", () => ({
  useLlmStore: () => mocks.llmStore,
}));

vi.mock("@/stores/project", () => ({
  useProjectStore: () => mocks.projectStore,
}));

vi.mock("@/stores/advisor", () => ({
  useAdvisorStore: () => mocks.advisorStore,
}));

const Harness = defineComponent({
  setup() {
    const tracker = useActivityTracker();
    onMounted(() => tracker.start());
    onBeforeUnmount(() => tracker.stop());
    return () => null;
  },
});

describe("useActivityTracker", () => {
  beforeEach(() => {
    mocks.route.path = "/project";
    mocks.route.fullPath = "/project";
    mocks.appMode.value = "enterprise";
    mocks.guidanceStore.isEnabled = true;
    mocks.isFeatureEnabled.mockClear();
    mocks.guidanceStore.acknowledgeActionClick.mockClear();
    mocks.wsSend.mockClear();
    mocks.projectStore = reactive({ currentProjectId: 17 });
    mocks.llmStore.wsRef = null;
    mocks.llmStore.connect.mockReset();
    mocks.llmStore.connect.mockImplementation(async () => {
      mocks.llmStore.wsRef = {
        readyState: WebSocket.OPEN,
        send: mocks.wsSend,
      } as unknown as WebSocket;
    });
  });

  it("connects the realtime socket before sending route activity", async () => {
    mount(Harness);
    await flushPromises();

    expect(mocks.llmStore.connect).toHaveBeenCalledTimes(1);
    expect(mocks.wsSend).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(mocks.wsSend.mock.calls[0][0]))).toMatchObject({
      action: "guidance.activity",
      payload: {
        kind: "route_change",
        route: "/project",
        project_id: 17,
        scope_node_id: 23,
      },
    });
  });

  it("does not send guidance activity when user guidance is disabled", async () => {
    mocks.guidanceStore.isEnabled = false;

    mount(Harness);
    await flushPromises();

    expect(mocks.llmStore.connect).not.toHaveBeenCalled();
    expect(mocks.wsSend).not.toHaveBeenCalled();
  });

  it("emits route activity when selected project changes without navigation", async () => {
    mount(Harness);
    await flushPromises();
    mocks.wsSend.mockClear();

    mocks.projectStore.currentProjectId = 36;
    await nextTick();
    await flushPromises();

    expect(mocks.wsSend).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(mocks.wsSend.mock.calls[0][0]))).toMatchObject({
      action: "guidance.activity",
      payload: {
        kind: "route_change",
        route: "/project",
        project_id: 36,
        scope_node_id: 23,
      },
    });
  });

  it("emits idle activity after five seconds", async () => {
    vi.useFakeTimers();
    const start = new Date("2026-05-14T18:00:00.000Z");
    vi.setSystemTime(start);
    try {
      mount(Harness);
      await flushPromises();
      mocks.wsSend.mockClear();

      vi.advanceTimersByTime(5_000);
      await flushPromises();

      expect(mocks.wsSend).toHaveBeenCalledTimes(1);
      expect(JSON.parse(String(mocks.wsSend.mock.calls[0][0]))).toMatchObject({
        action: "guidance.activity",
        payload: {
          kind: "idle_tick",
          route: "/project",
          project_id: 17,
          scope_node_id: 23,
          idle_seconds: 5,
        },
      });
    } finally {
      vi.useRealTimers();
    }
  });
});
