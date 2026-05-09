import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useGuidanceStore, type GuidanceEvent } from "@/stores/guidance";
import { guidanceRuleLabel } from "@/lib/guidanceRules";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPatch: vi.fn(),
  routerPush: vi.fn(),
  wsSend: vi.fn(),
  ws: {
    readyState: WebSocket.OPEN,
    send: vi.fn(),
  },
}));

vi.mock("@/api/client", () => ({
  default: {
    get: mocks.apiGet,
    patch: mocks.apiPatch,
  },
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({
    push: mocks.routerPush,
  }),
}));

vi.mock("@/stores/llm", () => ({
  useLlmStore: () => ({
    wsRef: mocks.ws,
  }),
}));

function makeEvent(overrides: Partial<GuidanceEvent> = {}): GuidanceEvent {
  return {
    type: "guidance.event",
    notification_id: 123,
    kind: "toast",
    title: "Ready to run?",
    body: "Your workflow has nodes and has not been run yet.",
    action_id: "run_workflow",
    action_version: 1,
    rule_id: "workflow_saved_never_run",
    confidence: 0.9,
    expires_at: new Date(Date.now() + 60_000).toISOString(),
    source: "rule",
    ...overrides,
  };
}

describe("guidance store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    mocks.ws.send = mocks.wsSend;
    mocks.ws.readyState = WebSocket.OPEN;
    mocks.apiGet.mockResolvedValue({
      data: {
        guidance_enabled: true,
        toast_enabled: true,
        glow_enabled: true,
      },
    });
    mocks.apiPatch.mockResolvedValue({
      data: {
        id: 123,
        rule_id: "workflow_saved_never_run",
      },
    });
  });

  it("loads guidance settings from the namespaced API", async () => {
    const store = useGuidanceStore();

    await store.loadSettings();

    expect(mocks.apiGet).toHaveBeenCalledWith("/guidance/settings");
    expect(store.isEnabled).toBe(true);
  });

  it("renders an enabled toast and acknowledges it as shown", async () => {
    const store = useGuidanceStore();
    await store.loadSettings();

    await store.handleEvent(makeEvent());

    expect(store.activeToast?.title).toBe("Ready to run?");
    expect(mocks.apiPatch).toHaveBeenCalledWith("/guidance/notifications/123", {
      ack_kind: "shown",
    });
    expect(mocks.wsSend).toHaveBeenCalledWith(
      expect.stringContaining('"action":"guidance.ack"')
    );
    expect(mocks.wsSend).toHaveBeenCalledWith(expect.stringContaining('"ack_kind":"shown"'));
  });

  it("ignores events when toast guidance is disabled", async () => {
    const store = useGuidanceStore();
    store.settings = {
      guidance_enabled: true,
      toast_enabled: false,
      glow_enabled: true,
    };

    await store.handleEvent(makeEvent());

    expect(store.activeToast).toBeNull();
    expect(mocks.apiPatch).not.toHaveBeenCalled();
    expect(mocks.wsSend).not.toHaveBeenCalled();
  });

  it("renders glow-only guidance when toasts are disabled", async () => {
    const store = useGuidanceStore();
    store.settings = {
      guidance_enabled: true,
      toast_enabled: false,
      glow_enabled: true,
    };

    await store.handleEvent(makeEvent({ kind: "glow" }));

    expect(store.activeToast).toBeNull();
    expect(store.activeGlow?.notification_id).toBe(123);
    expect(mocks.apiPatch).toHaveBeenCalledWith("/guidance/notifications/123", {
      ack_kind: "shown",
    });
  });

  it("skips glow when the action ontology version does not match", async () => {
    const store = useGuidanceStore();
    store.settings = {
      guidance_enabled: true,
      toast_enabled: false,
      glow_enabled: true,
    };

    await store.handleEvent(makeEvent({ kind: "glow", action_version: 99 }));

    expect(store.activeGlow).toBeNull();
    expect(mocks.apiPatch).not.toHaveBeenCalled();
  });

  it("acknowledges CTA clicks and routes to the action target", async () => {
    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(makeEvent());
    mocks.apiPatch.mockClear();
    mocks.wsSend.mockClear();

    await store.clickAction();

    expect(store.activeToast).toBeNull();
    expect(mocks.apiPatch).toHaveBeenCalledWith("/guidance/notifications/123", {
      ack_kind: "clicked",
    });
    expect(mocks.wsSend).toHaveBeenCalledWith(expect.stringContaining('"ack_kind":"clicked"'));
    expect(mocks.routerPush).toHaveBeenCalledWith("/workflow");
  });

  it("acknowledges real action clicks against an active glow", async () => {
    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(makeEvent({ kind: "glow" }));
    mocks.apiPatch.mockClear();

    await store.acknowledgeActionClick("run_workflow");

    expect(store.activeGlow).toBeNull();
    expect(mocks.apiPatch).toHaveBeenCalledWith("/guidance/notifications/123", {
      ack_kind: "clicked",
    });
  });

  it("loads persisted guidance notification history", async () => {
    const store = useGuidanceStore();
    mocks.apiGet.mockResolvedValueOnce({
      data: [
        {
          id: 9,
          project_id: 1,
          advisor_node_id: null,
          rule_id: "empty_project_import",
          kind: "both",
          title: "Start by importing data",
          body: null,
          action_id: "import_data",
          action_version: 1,
          confidence: 0.95,
          source: "rule",
          created_at: "2026-05-09T00:00:00Z",
          expires_at: "2026-05-09T00:10:00Z",
          shown_at: null,
          dismissed_at: null,
          clicked_at: null,
        },
      ],
    });

    await store.loadNotifications({ includeDismissed: true, limit: 100 });

    expect(mocks.apiGet).toHaveBeenCalledWith("/guidance/notifications", {
      params: { include_dismissed: true, limit: 100 },
    });
    expect(store.notifications[0]?.title).toBe("Start by importing data");
  });

  it("maps internal rule ids to user-facing labels", () => {
    expect(guidanceRuleLabel("empty_project_import")).toBe("Project setup");
    expect(guidanceRuleLabel("unknown_rule")).toBe("Guidance");
  });

  it("persists per-rule opt-out from the toast", async () => {
    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(makeEvent());
    mocks.apiPatch.mockClear();

    await store.dontShowAgain();

    expect(store.activeToast).toBeNull();
    expect(mocks.apiPatch).toHaveBeenCalledWith("/guidance/notifications/123", {
      ack_kind: "dont_show_again",
    });
  });
});
