import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createPinia, disposePinia, setActivePinia, type Pinia } from "pinia";
import api from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { SESSION_STORAGE_KEY } from "@/extension-contract/session-v1";
import { captureGuiTrace, flushGuiTrace, resetGuiTrace, traceGui } from "@/lib/guiTrace";

const originalAdapter = api.defaults.adapter;
let pinia: Pinia;
// Real Axios interceptors and transforms; the adapter is the network boundary.
const dispatched = vi.fn();
function installSession(login: string) {
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({
    token: `test-only-${login}`, loginId: login, generation: 0, transition: "login",
  }));
}
beforeEach(async () => {
  localStorage.clear(); resetGuiTrace(); dispatched.mockReset();
  installSession("first");
  pinia = createPinia(); setActivePinia(pinia);
  useAuthStore().user = { id: 7, username: "first" };
  api.defaults.adapter = async config => {
    if (config.url === "/logs/workspace-events") {
      dispatched({ serialized: typeof config.data === "string", body: JSON.parse(config.data),
        jsonContentType: config.headers.get("Content-Type") === "application/json",
        replacementActor: config.headers.Authorization === "Bearer test-only-second" });
    }
    return { config, status: 200, statusText: "OK", data: {}, headers: { "x-sherpa-gui-trace": "1" } };
  };
  // Enable the actual production sender through the actual response interceptor.
  await api.get("/config");
  await flushGuiTrace(); dispatched.mockClear();
});
afterEach(() => {
  api.defaults.adapter = originalAdapter; disposePinia(pinia); setActivePinia(undefined); resetGuiTrace(); localStorage.clear();
});

it.each(["captured", "generic"])("refuses %s old-owner trace after enqueue but before Axios initiating-session capture", async kind => {
  const emit = kind === "captured" ? captureGuiTrace(() => true) : traceGui;
  emit("workflow_loading", "start", { workflow_id: 424, project_id: 126, workflow_loading: true });
  const pending = flushGuiTrace(); // Calls api.post synchronously; request interceptor is still a microtask away.
  installSession("second");
  // The legitimate new-login bootstrap synchronously adopts the replacement
  // session before the first request interceptor microtask reads initiating.
  const bootstrap = useAuthStore().ensureStoredSession(true);
  useAuthStore().user = { id: 8, username: "second" };
  await bootstrap;
  await pending;
  // Old implementation dispatched exactly once, with replacementActor=true.
  expect(dispatched.mock.calls.filter(([record]) => record.replacementActor).length).toBe(0);
  expect(dispatched).not.toHaveBeenCalled();
});

it("preserves Axios JSON serialization for a current-session trace without transport metadata in its body", async () => {
  captureGuiTrace(() => true)("workflow_loading", "ok", { workflow_id: 424, workflow_loading: false });
  await flushGuiTrace();
  expect(dispatched).toHaveBeenCalledOnce();
  const record = dispatched.mock.calls[0][0];
  expect(record.serialized).toBe(true);
  expect(record.jsonContentType).toBe(true);
  expect(Object.keys(record.body).sort()).toEqual(["events", "page_id"]);
  expect(record.body.events).toEqual([expect.objectContaining({ operation: "workflow_loading", workflow_id: 424, workflow_loading: false })]);
  expect(JSON.stringify(record.body)).not.toContain("test-only");
});

it("refuses a batch if its page epoch resets in the dispatch window without a credential change", async () => {
  traceGui("workflow_loading", "start", { workflow_id: 424 });
  const pending = flushGuiTrace();
  resetGuiTrace();
  await pending;
  expect(dispatched).not.toHaveBeenCalled();
});

it("rechecks an event's owner guard at dispatch even when the browser credential is unchanged", async () => {
  let ownerCurrent = true;
  captureGuiTrace(() => ownerCurrent)("workflow_loading", "start", { workflow_id: 424 });
  const pending = flushGuiTrace();
  ownerCurrent = false;
  await pending;
  expect(dispatched).not.toHaveBeenCalled();
});
