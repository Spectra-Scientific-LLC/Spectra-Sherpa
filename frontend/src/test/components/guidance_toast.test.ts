/**
 * Component tests for GuidanceToast — Deploy + Report flows.
 *
 * Store-level tests (``src/test/stores/guidance.test.ts``) cover the
 * acknowledgement state machine.  These tests pin the rendered DOM:
 * what does a deploy notification look like to the user, what does
 * a report notification look like, what happens when the CTA is
 * clicked through the actual button element.  Catches regressions
 * the store tests can't see — e.g. the toast accidentally not
 * exposing an action button, label being empty, or chip-style drift
 * for LLM-sourced suggestions.
 */
import { mount, flushPromises } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import GuidanceToast from "@/components/guidance/GuidanceToast.vue";
import { useGuidanceStore, type GuidanceEvent } from "@/stores/guidance";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPatch: vi.fn(),
  routerPush: vi.fn(),
  wsSend: vi.fn(),
  ws: { readyState: WebSocket.OPEN, send: vi.fn() },
  advisorActiveNode: { value: null as { id: number; tab_key: string; subscope_key: string } | null },
}));

vi.mock("@/api/client", () => ({
  default: { get: mocks.apiGet, patch: mocks.apiPatch },
}));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: mocks.routerPush }) }));
vi.mock("@/stores/llm", () => ({ useLlmStore: () => ({ wsRef: mocks.ws }) }));
vi.mock("@/stores/advisor", () => ({
  useAdvisorStore: () => ({
    get activeNode() {
      return mocks.advisorActiveNode.value;
    },
  }),
}));

function makeDeployEvent(overrides: Partial<GuidanceEvent> = {}): GuidanceEvent {
  return {
    type: "guidance.event",
    notification_id: 501,
    kind: "both",
    title: "Automate this with a folder watch",
    body: "You've run this workflow a few times. A folder watch can process new files automatically.",
    action_id: "create_folder_watch",
    action_version: 1,
    rule_id: "deploy_runs_no_automation",
    confidence: 0.8,
    expires_at: new Date(Date.now() + 60_000).toISOString(),
    source: "rule",
    ...overrides,
  };
}

function makeReportEvent(overrides: Partial<GuidanceEvent> = {}): GuidanceEvent {
  return {
    type: "guidance.event",
    notification_id: 502,
    kind: "toast",
    title: "Want help drafting a report?",
    body: "Open Advisor to summarize your latest run and suggest a structure for the writeup.",
    action_id: "draft_report_via_advisor",
    action_version: 1,
    rule_id: "report_idle_with_runs",
    confidence: 0.7,
    expires_at: new Date(Date.now() + 60_000).toISOString(),
    source: "rule",
    ...overrides,
  };
}

describe("GuidanceToast (Deploy + Report flows)", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    mocks.ws.send = mocks.wsSend;
    mocks.ws.readyState = WebSocket.OPEN;
    mocks.advisorActiveNode.value = null;
    mocks.apiGet.mockResolvedValue({
      data: { guidance_enabled: true, toast_enabled: true, glow_enabled: true },
    });
    mocks.apiPatch.mockResolvedValue({ data: { id: 501 } });
    document.body.innerHTML = "";
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("renders nothing when there is no active toast", () => {
    const wrapper = mount(GuidanceToast);
    expect(wrapper.find(".guidance-toast").exists()).toBe(false);
  });

  it("renders deploy toast title + body + 'Create folder watch' CTA", async () => {
    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(makeDeployEvent());
    const wrapper = mount(GuidanceToast);
    await flushPromises();

    const toast = wrapper.find(".guidance-toast");
    expect(toast.exists()).toBe(true);
    expect(toast.find("h2").text()).toBe("Automate this with a folder watch");
    expect(toast.find("p").text()).toContain("folder watch");

    const primary = toast.find(".guidance-toast__primary");
    expect(primary.exists()).toBe(true);
    expect(primary.text()).toBe("Create folder watch");
  });

  it("renders report toast with 'Draft with Advisor' CTA", async () => {
    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(makeReportEvent());
    const wrapper = mount(GuidanceToast);
    await flushPromises();

    const toast = wrapper.find(".guidance-toast");
    expect(toast.exists()).toBe(true);
    expect(toast.find("h2").text()).toBe("Want help drafting a report?");
    const primary = toast.find(".guidance-toast__primary");
    expect(primary.text()).toBe("Draft with Advisor");
  });

  it("Deploy CTA click clicks the [data-action] target after navigation", async () => {
    // Set up the same-route New Watch button so the PR6 clickTarget
    // wait resolves immediately when the toast CTA is clicked.
    const newWatchButton = document.createElement("button");
    newWatchButton.setAttribute("data-action", "create_folder_watch");
    newWatchButton.textContent = "New Watch";
    const buttonClickSpy = vi.fn();
    newWatchButton.addEventListener("click", buttonClickSpy);
    document.body.appendChild(newWatchButton);

    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(makeDeployEvent());
    const wrapper = mount(GuidanceToast);
    await flushPromises();
    mocks.apiPatch.mockClear();

    await wrapper.find(".guidance-toast__primary").trigger("click");
    await flushPromises();

    expect(mocks.routerPush).toHaveBeenCalledWith("/deploy");
    expect(buttonClickSpy).toHaveBeenCalledTimes(1);
    expect(mocks.apiPatch).toHaveBeenCalledWith(
      "/guidance/notifications/501",
      { ack_kind: "clicked" },
    );
    expect(wrapper.find(".guidance-toast").exists()).toBe(false);
  });

  it("Report CTA click waits for advisor scope and dispatches the prompt", async () => {
    // Set advisor scope to match the report action's expectedScope
    // BEFORE the click so _waitForAdvisorScope resolves immediately
    // (the live in-tab path).
    mocks.advisorActiveNode.value = {
      id: 99,
      tab_key: "report",
      subscope_key: "draft",
    };
    const promptListener = vi.fn();
    window.addEventListener("advisor-prompt-request", promptListener);

    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(makeReportEvent());
    const wrapper = mount(GuidanceToast);
    await flushPromises();
    mocks.apiPatch.mockClear();

    await wrapper.find(".guidance-toast__primary").trigger("click");
    await flushPromises();

    expect(mocks.routerPush).toHaveBeenCalledWith("/report");
    expect(promptListener).toHaveBeenCalledTimes(1);
    const promptEvent = promptListener.mock.calls[0]?.[0] as CustomEvent<{
      prompt: string;
      autoSend: boolean;
    }>;
    expect(promptEvent.detail.prompt).toContain("report");
    expect(promptEvent.detail.autoSend).toBe(true);
    expect(mocks.apiPatch).toHaveBeenCalledWith(
      "/guidance/notifications/502",
      { ack_kind: "clicked" },
    );
    window.removeEventListener("advisor-prompt-request", promptListener);
  });

  it("Dismiss button acknowledges and hides the toast", async () => {
    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(makeDeployEvent());
    const wrapper = mount(GuidanceToast);
    await flushPromises();
    mocks.apiPatch.mockClear();

    await wrapper.find(".guidance-toast__close").trigger("click");
    await flushPromises();

    expect(mocks.apiPatch).toHaveBeenCalledWith(
      "/guidance/notifications/501",
      { ack_kind: "dismissed" },
    );
    expect(wrapper.find(".guidance-toast").exists()).toBe(false);
  });

  it('"Don\'t show again" sends the dont_show_again ack', async () => {
    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(makeReportEvent());
    const wrapper = mount(GuidanceToast);
    await flushPromises();
    mocks.apiPatch.mockClear();

    await wrapper.find(".guidance-toast__quiet").trigger("click");
    await flushPromises();

    expect(mocks.apiPatch).toHaveBeenCalledWith(
      "/guidance/notifications/502",
      { ack_kind: "dont_show_again" },
    );
  });

  it("Shows AI badge for LLM-sourced toasts", async () => {
    const store = useGuidanceStore();
    await store.loadSettings();
    await store.handleEvent(
      makeDeployEvent({
        notification_id: 503,
        source: "llm",
        rule_id: "llm_create_folder_watch",
      }),
    );
    const wrapper = mount(GuidanceToast);
    await flushPromises();

    const chips = wrapper.findAll(".guidance-toast__chip");
    expect(chips.length).toBe(2); // base "Guidance" + "AI" badge
    expect(chips[1]?.text()).toBe("AI");
  });
});
