import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useGuidanceStore, type GuidanceEvent } from "@/stores/guidance";
import {
  ADVISOR_PROMPT_REQUEST_EVENT,
  type AdvisorPromptRequestDetail,
} from "@/lib/advisorPromptActions";
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
  advisorActiveNode: {
    value: null as { id: number; tab_key: string; subscope_key: string } | null,
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

vi.mock("@/stores/advisor", () => ({
  useAdvisorStore: () => ({
    get activeNode() {
      return mocks.advisorActiveNode.value;
    },
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

  it("routes prompt-backed actions and asks Sherpa Advisor", async () => {
    const store = useGuidanceStore();
    const promptListener = vi.fn();
    window.addEventListener(ADVISOR_PROMPT_REQUEST_EVENT, promptListener);
    await store.loadSettings();
    await store.handleEvent(
      makeEvent({
        action_id: "explain_latest_results",
        title: "Want an explanation of these results?",
        rule_id: "idle_on_results",
      }),
    );
    mocks.apiPatch.mockClear();

    await store.clickAction();

    expect(mocks.routerPush).toHaveBeenCalledWith("/experiments");
    expect(promptListener).toHaveBeenCalledTimes(1);
    const event = promptListener.mock.calls[0]?.[0] as CustomEvent<AdvisorPromptRequestDetail>;
    expect(event.detail).toEqual({
      prompt: "Explain the results of my latest run.",
      autoSend: true,
    });
    window.removeEventListener(ADVISOR_PROMPT_REQUEST_EVENT, promptListener);
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
    expect(guidanceRuleLabel("llm_run_workflow")).toBe("Guidance insight");
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

  // ---------------------------------------------------------------
  // PR6 — action execution hardening
  // ---------------------------------------------------------------

  it("clicks [data-action] target after navigation when clickTarget is set", async () => {
    // Mount the data-action button BEFORE the click so the wait
    // resolves immediately. This is the live in-tab path (rule fires
    // on the same route, target is already in the DOM).
    const button = document.createElement("button");
    button.setAttribute("data-action", "create_folder_watch");
    button.textContent = "New Watch";
    const clickSpy = vi.fn();
    button.addEventListener("click", clickSpy);
    document.body.appendChild(button);

    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(
      makeEvent({
        action_id: "create_folder_watch",
        rule_id: "deploy_runs_no_automation",
        kind: "both",
      }),
    );

    await store.clickAction();

    expect(mocks.routerPush).toHaveBeenCalledWith("/deploy");
    expect(clickSpy).toHaveBeenCalledTimes(1);
    document.body.removeChild(button);
  });

  it("does not throw when clickTarget never appears within timeout", async () => {
    // Live with a very short timeout via the imported util's default
    // — the test passes when no error escapes.  We can't easily
    // shorten the 2s default from outside, so we simulate by
    // dispatching the action WITHOUT mounting any data-action target
    // and asserting clickAction resolves cleanly (the test would
    // exceed vitest's 5s default timeout if the wait hung).
    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(
      makeEvent({
        action_id: "new_project",
        rule_id: "empty_project_import",
        kind: "toast",
      }),
    );

    // The button isn't in the DOM. Use vi.useFakeTimers to advance
    // through the wait without burning real wall clock.
    vi.useFakeTimers();
    const clickPromise = store.clickAction();
    await vi.advanceTimersByTimeAsync(2100);
    await clickPromise;
    vi.useRealTimers();

    expect(mocks.routerPush).toHaveBeenCalledWith("/project");
    // Routing succeeded; nothing crashed; no test assertion failed.
  }, 10_000);

  it("waits for advisor scope before firing prompt for drawer-clicked report action", async () => {
    // Simulates the notification-drawer cross-tab click path:
    // user is on /workflow, clicks a report draft notification,
    // the prompt must land in report.draft, not workflow.sheet.
    //
    // We assert the integration by setting activeNode to match the
    // expectedScope BEFORE clickAction runs.  The synchronous
    // ``matches()`` check inside ``_waitForAdvisorScope`` returns
    // true immediately and the prompt fires.  Real reactivity (watch
    // firing on a later mutation) is exercised in staging — what we
    // pin here is the contract: scope must equal expectedScope
    // before the prompt event dispatches.
    mocks.advisorActiveNode.value = {
      id: 99,
      tab_key: "report",
      subscope_key: "draft",
    };
    const promptListener = vi.fn();
    window.addEventListener(ADVISOR_PROMPT_REQUEST_EVENT, promptListener);

    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(
      makeEvent({
        action_id: "draft_report_via_advisor",
        rule_id: "report_idle_with_runs",
        kind: "toast",
      }),
    );

    await store.clickAction();

    expect(mocks.routerPush).toHaveBeenCalledWith("/report");
    expect(promptListener).toHaveBeenCalledTimes(1);
    const event = promptListener.mock.calls[0]?.[0] as CustomEvent<AdvisorPromptRequestDetail>;
    expect(event.detail.prompt).toContain("report");
    window.removeEventListener(ADVISOR_PROMPT_REQUEST_EVENT, promptListener);
    mocks.advisorActiveNode.value = null;
  });
});
