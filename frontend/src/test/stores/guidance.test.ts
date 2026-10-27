import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useGuidanceStore, type GuidanceEvent } from "@/stores/guidance";
import {
  ADVISOR_PROMPT_REQUEST_EVENT,
  type AdvisorPromptRequestDetail,
} from "@/lib/advisorPromptActions";
import { guidanceRuleLabel } from "@/lib/guidanceRules";
import { GUIDANCE_ACTIONS } from "@/lib/actionOntology";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPatch: vi.fn(),
  routerPush: vi.fn(),
  project: { currentProjectId: 7 as number | null },
  workflow: { workflowId: 9 as number | null, restoredRunId: 31 as number | null },
  notify: vi.fn(),
  currentRoute: { value: { path: "/dashboard", query: {} as Record<string, string> } },
  wsSend: vi.fn(),
  ws: {
    readyState: WebSocket.OPEN,
    send: vi.fn(),
  },
  advisorActiveNode: {
    value: null as { id: number; project_id: number; tab_key: string; subscope_key: string } | null,
  },
}));

vi.mock("@/api/client", () => ({
  default: {
    get: mocks.apiGet,
    patch: mocks.apiPatch,
  },
}));

vi.mock("@/stores/project", () => ({ useProjectStore: () => mocks.project }));
vi.mock("@/stores/workflow", () => ({ useWorkflowStore: () => mocks.workflow }));
vi.mock("@/composables/useNotifier", () => ({ useNotifier: () => ({ notifySystemEvent: mocks.notify }) }));
vi.mock("vue-router", async (original) => ({
  ...await original<typeof import("vue-router")>(),
  useRouter: () => ({
    push: mocks.routerPush,
    currentRoute: mocks.currentRoute,
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
    document.body.replaceChildren();
    setActivePinia(createPinia());
    vi.clearAllMocks();
    mocks.currentRoute.value.path = "/dashboard";
    mocks.currentRoute.value.query = {};
    mocks.project.currentProjectId = 7;
    mocks.advisorActiveNode.value = null;
    mocks.routerPush.mockImplementation(async (route: { path: string }) => { mocks.currentRoute.value.path = route.path; });
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

  it("opens workflow from Data through the existing dataset handoff, not a blank route", async () => {
    mocks.currentRoute.value.path = "/data";
    const workflow = document.createElement("button");
    workflow.dataset.action = "open_workflow";
    const handoff = vi.fn();
    workflow.addEventListener("click", handoff);
    document.body.append(workflow);
    await useGuidanceStore().runAction("open_workflow");
    expect(handoff).toHaveBeenCalledTimes(1);
    expect(mocks.routerPush).not.toHaveBeenCalled();
  });

  it.each(["disabled", "missing"])("does not bypass a %s Data handoff", async (state) => {
    mocks.currentRoute.value.path = "/data";
    const handoff = vi.fn();
    if (state === "disabled") {
      const workflow = document.createElement("button");
      workflow.dataset.action = "open_workflow";
      workflow.disabled = true;
      workflow.addEventListener("click", handoff);
      document.body.append(workflow);
    }
    await useGuidanceStore().runAction("open_workflow");
    expect(handoff).not.toHaveBeenCalled();
    expect(mocks.routerPush).not.toHaveBeenCalled();
  });

  it("preserves ordinary workflow navigation outside Data", async () => {
    await useGuidanceStore().runAction("open_workflow");
    expect(mocks.routerPush).toHaveBeenCalledWith({ path: "/workflow", query: { project_id: "7", workflow_id: "9" }, hash: undefined });
  });

  it("opens Analysis Starter without replacing its exact dataset-selection receipt", async () => {
    mocks.currentRoute.value.path = "/workflow";
    mocks.currentRoute.value.query = { project_id: "7", fromDataSelection: "1", selection: "exact-subset-receipt" };
    const before = { ...mocks.currentRoute.value.query };
    const target = document.createElement("button");
    target.dataset.action = "open_analysis_starters";
    const clicked = vi.fn();
    target.onclick = clicked;
    document.body.append(target);
    expect(await useGuidanceStore().runAction("open_analysis_starters")).toBe(true);
    expect(clicked).toHaveBeenCalledOnce();
    expect(mocks.routerPush).not.toHaveBeenCalled();
    expect(mocks.currentRoute.value.query).toEqual(before);
  });

  it.each(["wrong-page", "disabled", "missing"])("refuses a %s Analysis Starter action without discarding its context", async state => {
    mocks.currentRoute.value.path = state === "wrong-page" ? "/data" : "/workflow";
    const target = document.createElement("button");
    target.dataset.action = "open_analysis_starters";
    target.disabled = state === "disabled";
    const clicked = vi.fn();
    target.onclick = clicked;
    if (state !== "missing") document.body.append(target);
    expect(await useGuidanceStore().runAction("open_analysis_starters")).toBe(false);
    expect(clicked).not.toHaveBeenCalled();
    expect(mocks.routerPush).not.toHaveBeenCalled();
  });

  it.each(Object.values(GUIDANCE_ACTIONS).filter(action => action.actionId !== "open_analysis_starters"))("keeps the project for $actionId without submitting scientific work", async (action) => {
    if (action.expectedScope) mocks.advisorActiveNode.value = { id: 1, project_id: 7, tab_key: action.expectedScope.tabKey, subscope_key: action.expectedScope.subscopeKey ?? "" };
    const target = document.createElement("button");
    target.dataset.action = action.clickTarget ?? "import_data";
    const clicked = vi.fn();
    target.onclick = clicked;
    document.body.append(target);
    expect(await useGuidanceStore().runAction(action.actionId)).toBe(true);
    const destination = mocks.routerPush.mock.calls[0][0];
    expect(destination.path).toBe(action.route);
    expect(destination.query[action.route === "/workflow" ? "project_id" : "project"]).toBe("7");
    if (action.query) expect(destination.query).toMatchObject(action.query);
    expect(clicked).toHaveBeenCalledTimes(action.clickTarget ? 1 : 0);
  });

  it("refuses a stale-project suggestion instead of acting in the newly selected project", async () => {
    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(makeEvent());
    mocks.project.currentProjectId = 8;
    await store.clickAction();
    expect(mocks.routerPush).not.toHaveBeenCalled();
    expect(store.error).toContain("another project");
  });

  it("handles failed route loading without an unhandled rejection", async () => {
    mocks.routerPush.mockRejectedValueOnce(new Error("chunk unavailable"));
    const store = useGuidanceStore();
    await expect(store.runAction("open_library")).resolves.toBe(false);
    expect(store.error).toContain("could not be loaded");
  });

  it("does not send an Advisor prompt when the destination topic never becomes ready", async () => {
    vi.useFakeTimers();
    const listener = vi.fn();
    window.addEventListener(ADVISOR_PROMPT_REQUEST_EVENT, listener);
    try {
      const result = useGuidanceStore().runAction("explain_latest_results");
      await vi.advanceTimersByTimeAsync(2100);
      expect(await result).toBe(false);
      expect(listener).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener(ADVISOR_PROMPT_REQUEST_EVENT, listener);
      vi.useRealTimers();
    }
  });

  it("loads guidance settings from the namespaced API", async () => {
    const store = useGuidanceStore();

    const ok = await store.loadSettings();

    expect(mocks.apiGet).toHaveBeenCalledWith("/guidance/settings");
    expect(store.isEnabled).toBe(true);
    expect(ok).toBe(true);
  });

  it("returns false from loadSettings on fetch failure (audit F2 retry contract)", async () => {
    const store = useGuidanceStore();
    mocks.apiGet.mockRejectedValueOnce(new Error("Authentication required"));

    const ok = await store.loadSettings();

    // Failure must be observable so useGuidance.start() can retry —
    // previously this was swallowed and guidance silently froze
    // disabled until a full reload.
    expect(ok).toBe(false);
    expect(store.error).toContain("Authentication required");
    expect(store.isEnabled).toBe(false);
  });

  it("disables active guidance when the server reports it is unavailable", async () => {
    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(makeEvent({ kind: "both" }));

    store.markUnavailable({
      type: "guidance.unavailable",
      reason: "entitlement_required",
    });

    expect(store.isEnabled).toBe(false);
    expect(store.activeToast).toBeNull();
    expect(store.activeGlow).toBeNull();
    expect(store.error).toContain("plan does not include Guidance");
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
    expect(mocks.routerPush).toHaveBeenCalledWith({ path: "/workflow", query: { project_id: "7", workflow_id: "9" }, hash: undefined });
  });

  it("routes prompt-backed actions and asks Sherpa Advisor", async () => {
    const store = useGuidanceStore();
    mocks.advisorActiveNode.value = {
      id: 77,
      project_id: 7,
      tab_key: "models",
      subscope_key: "run_history",
    };
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

    expect(mocks.routerPush).toHaveBeenCalledWith({ path: "/runs", query: { project: "7", tab: "run_history" }, hash: undefined });
    expect(promptListener).toHaveBeenCalledTimes(1);
    const event = promptListener.mock.calls[0]?.[0] as CustomEvent<AdvisorPromptRequestDetail>;
    expect(event.detail).toEqual({
      prompt: "Explain the latest saved run and model artifacts in this project, including what I should compare next.",
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

    expect(mocks.routerPush).toHaveBeenCalledWith({ path: "/deploy", query: { project: "7" }, hash: undefined });
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

    expect(mocks.routerPush).toHaveBeenCalledWith({ path: "/project", query: { project: "7" }, hash: undefined });
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
      project_id: 7,
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

    expect(mocks.routerPush).toHaveBeenCalledWith({ path: "/report", query: { project: "7", workflow: "9", run: "31" }, hash: undefined });
    expect(promptListener).toHaveBeenCalledTimes(1);
    const event = promptListener.mock.calls[0]?.[0] as CustomEvent<AdvisorPromptRequestDetail>;
    expect(event.detail.prompt).toContain("report");
    window.removeEventListener(ADVISOR_PROMPT_REQUEST_EVENT, promptListener);
    mocks.advisorActiveNode.value = null;
  });
});
