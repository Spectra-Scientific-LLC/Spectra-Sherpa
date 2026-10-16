import { flushPromises, mount } from "@vue/test-utils";
import { reactive, nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LogsView from "@/views/LogsView.vue";

type MockConfig = { appMode: { value: string }; siteProfile: { value: string | null } };
type MockAuth = {
  user: { id: number; capabilities: { admin: boolean }; is_active: boolean } | null;
  token: string | null;
};
const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  config: { appMode: { value: "enterprise" }, siteProfile: { value: "demo" } } as MockConfig,
  auth: { user: null, token: null } as MockAuth,
}));
vi.mock("@/composables/useAppConfig", () => ({ useAppConfig: () => mocks.config }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => mocks.auth }));
vi.mock("@/api/client", () => ({ default: { get: mocks.get } }));
const wrappers: ReturnType<typeof mount>[] = [];
function render() {
  const wrapper = mount(LogsView, { global: { stubs: {
    ResponsiveHeaderActions: { template: "<div><slot/></div>" },
    ChatExchangeHistory: true,
    Button: { props: ["label", "disabled"], template: '<button :disabled="disabled">{{label}}</button>' },
  } } });
  wrappers.push(wrapper);
  return wrapper;
}
const snapshot = { data: { logs: [{ timestamp: "now", level: "INFO", message: "private diagnostic" }] } };

describe("application log access", () => {
  beforeEach(() => {
    mocks.get.mockReset().mockResolvedValue(snapshot);
    mocks.config = reactive({ appMode: { value: "enterprise" }, siteProfile: { value: "demo" } });
    mocks.auth = reactive({ user: { id: 1, capabilities: { admin: true }, is_active: true }, token: "token" });
  });
  afterEach(() => { wrappers.splice(0).forEach((wrapper) => wrapper.unmount()); });

  it("loads Demo admin logs only on explicit refresh", async () => {
    const wrapper = render();
    expect(mocks.get).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("including other users' activity");
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(mocks.get).toHaveBeenCalledWith("/admin/logs", { signal: expect.any(AbortSignal) });
    expect(wrapper.text()).toContain("private diagnostic");
  });

  it.each(["ordinary", "anonymous", "inactive", "pro"])("blocks %s viewers without a request", async (kind) => {
    if (kind === "ordinary") mocks.auth.user!.capabilities.admin = false;
    if (kind === "anonymous") mocks.auth.user = null;
    if (kind === "inactive") mocks.auth.user!.is_active = false;
    if (kind === "pro") mocks.config.siteProfile.value = "pro";
    const wrapper = render();
    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
    await wrapper.get("button").trigger("click");
    expect(mocks.get).not.toHaveBeenCalled();
    expect(wrapper.find(".logs-list").exists()).toBe(false);
  });

  it.each(["local", "hybrid"])("preserves the %s localhost endpoint", async (mode) => {
    mocks.config.appMode.value = mode;
    mocks.config.siteProfile.value = null;
    const wrapper = render();
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(mocks.get).toHaveBeenCalledWith("/logs", { signal: expect.any(AbortSignal) });
  });

  it.each([[401, "Sign in again"], [403, "Only Demo administrators"], [500, "Try Refresh again"]])(
    "explains status %s without suggesting an API key", async (status, message) => {
      mocks.get.mockRejectedValue({ response: { status } });
      const wrapper = render();
      await wrapper.get("button").trigger("click");
      await flushPromises();
      expect(wrapper.get('[role="alert"]').text()).toContain(message);
      expect(wrapper.text()).not.toContain("API key");
    },
  );

  it.each(["logout", "switch", "demote", "token"])("clears the snapshot on %s", async (change) => {
    const wrapper = render();
    await wrapper.get("button").trigger("click");
    await flushPromises();
    if (change === "logout") mocks.auth.user = null;
    if (change === "switch") mocks.auth.user!.id = 2;
    if (change === "demote") mocks.auth.user!.capabilities.admin = false;
    if (change === "token") mocks.auth.token = null;
    await nextTick();
    expect(wrapper.text()).not.toContain("private diagnostic");
  });

  it("aborts stale requests and ignores their late result", async () => {
    let resolve!: (value: typeof snapshot) => void;
    mocks.get.mockImplementation(() => new Promise((done) => { resolve = done; }));
    const wrapper = render();
    await wrapper.get("button").trigger("click");
    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
    const signal = mocks.get.mock.calls[0][1].signal;
    mocks.auth.user!.id = 2;
    expect(signal.aborted).toBe(true);
    resolve(snapshot);
    await flushPromises();
    expect(wrapper.text()).not.toContain("private diagnostic");
  });

  it("aborts pending requests on unmount", async () => {
    mocks.get.mockImplementation(() => new Promise(() => {}));
    const wrapper = render();
    await wrapper.get("button").trigger("click");
    const signal = mocks.get.mock.calls[0][1].signal;
    wrapper.unmount();
    expect(signal.aborted).toBe(true);
  });

  it("explains an empty snapshot", async () => {
    mocks.get.mockResolvedValue({ data: { logs: [] } });
    const wrapper = render();
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("No recent application logs");
  });
});
