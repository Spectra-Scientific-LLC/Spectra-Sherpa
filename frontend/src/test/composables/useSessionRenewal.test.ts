import { readBrowserToken } from "@/extension-contract/session-v1";
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, onMounted } from "vue";
import { createPinia, setActivePinia, disposePinia, type Pinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSessionRenewal } from "@/composables/useSessionRenewal";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import { useWorkbookStore } from "@/stores/workbook";
import { useWorkflowStore } from "@/stores/workflow";

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: { post: mocks.post },
}));

let auth: ReturnType<typeof useAuthStore>;
let pinia: Pinia;

const tokenWithExpiry = (seconds: number): string => {
  const payload = window
    .btoa(JSON.stringify({ sub: "7", exp: seconds }))
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  return `header.${payload}.signature`;
};

const Harness = defineComponent({
  setup() {
    auth.token = readBrowserToken();
    const renewal = useSessionRenewal();
    onMounted(() => renewal.start());
    return () => null;
  },
});

describe("useSessionRenewal", () => {
  let wrapper: ReturnType<typeof mount> | null = null;
  afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    disposePinia(pinia);
  });
  beforeEach(() => {
    localStorage.clear();
    mocks.post.mockReset();
    pinia = createPinia();
    setActivePinia(pinia);
    auth = useAuthStore();
    auth.user = { id: 7, username: "first" };
  });

  it("renews a valid session while the visible tab is active", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-21T12:00:00Z"));
    try {
      const expiringToken = tokenWithExpiry(Date.now() / 1000 + 10 * 60);
      const renewedToken = tokenWithExpiry(Date.now() / 1000 + 60 * 60);
      localStorage.setItem("token", expiringToken);
      mocks.post.mockResolvedValue({ data: { access_token: renewedToken } });

      wrapper = mount(Harness);
      await flushPromises();

      expect(mocks.post).toHaveBeenCalledWith("/auth/refresh");
      expect(readBrowserToken()).toBe(renewedToken);
      expect(auth.token).toBe(renewedToken);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not renew a token that is not near expiry", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-21T12:00:00Z"));
    try {
      localStorage.setItem("token", tokenWithExpiry(Date.now() / 1000 + 30 * 60));

      wrapper = mount(Harness);
      await flushPromises();

      expect(mocks.post).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the loaded canvas, sheets, draft and retained results through the actual refresh path", async () => {
    const token = tokenWithExpiry(Date.now() / 1000 + 10 * 60);
    localStorage.setItem("token", token);
    auth.token = token;
    const project = useProjectStore();
    project.currentProjectId = 129;
    project.currentProject = { id: 129, name: "Corn M5" } as never;
    const workbook = useWorkbookStore();
    workbook.projectId = 129;
    workbook.sheets = [{ workflowId: 385, name: "Preprocessing Pipeline" }] as never;
    const workflow = useWorkflowStore();
    workflow.workflowId = 385;
    workflow.nodes = [{ id: "snv", type: "preprocess.normalize", params: { method: "snv" } }] as never;
    workflow.hasUnsavedChanges = true;
    workflow.lastExecutionResults = { snv: { data: [[1, 2]] } };
    const revision = auth.sessionRevision;
    mocks.post.mockResolvedValue({ data: { access_token: tokenWithExpiry(Date.now() / 1000 + 3600) } });
    wrapper = mount(Harness);
    await flushPromises();
    expect(mocks.post).toHaveBeenCalledWith("/auth/refresh");
    expect(auth.sessionRevision).toBe(revision);
    expect(project.currentProjectId).toBe(129);
    expect(workbook.activeSheet?.workflowId).toBe(385);
    expect(workflow.workflowId).toBe(385);
    expect(workflow.nodes).toHaveLength(1);
    expect(workflow.hasUnsavedChanges).toBe(true);
    expect(workflow.lastExecutionResults).toEqual({ snv: { data: [[1, 2]] } });
    await auth.clearCredentials();
    expect(project.currentProjectId).toBeNull();
    expect(workbook.sheets).toEqual([]);
    expect(workflow.nodes).toEqual([]);
  });

  it("does not renew after the tab has been idle for five minutes", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-21T12:00:00Z"));
    try {
      localStorage.setItem("token", tokenWithExpiry(Date.now() / 1000 + 30 * 60));
      wrapper = mount(Harness);
      await flushPromises();

      vi.advanceTimersByTime(6 * 60_000);
      localStorage.setItem("token", tokenWithExpiry(Date.now() / 1000 + 10 * 60));
      vi.advanceTimersByTime(15_000);
      await flushPromises();

      expect(mocks.post).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it.each(["token", "host-user"])(
    "starts renewal after %s login without remounting the layout",
    async (loginSignal) => {
      vi.useFakeTimers();
      vi.setSystemTime(new Date("2026-09-21T12:00:00Z"));
      try {
        wrapper = mount(Harness);
        await vi.advanceTimersByTimeAsync(10 * 60_000);
        expect(mocks.post).not.toHaveBeenCalled();
        const token = tokenWithExpiry(Date.now() / 1000 + 10 * 60);
        const renewed = tokenWithExpiry(Date.now() / 1000 + 60 * 60);
        mocks.post.mockResolvedValue({ data: { access_token: renewed } });
        localStorage.setItem("token", token);
        auth.token = token;
        if (loginSignal === "host-user") auth.user = { id: 7, username: "first" };
        await flushPromises();
        expect(mocks.post).toHaveBeenCalledTimes(1);
        expect(auth.token).toBe(renewed);
      } finally {
        vi.useRealTimers();
      }
    },
  );

  it("does not resurrect a logged-out session from an in-flight refresh", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-21T12:00:00Z"));
    try {
      const token = tokenWithExpiry(Date.now() / 1000 + 10 * 60);
      localStorage.setItem("token", token);
      auth.token = token;
      let resolve!: (value: { data: { access_token: string } }) => void;
      mocks.post.mockReturnValue(
        new Promise((done) => {
          resolve = done;
        }),
      );
      wrapper = mount(Harness);
      await flushPromises();
      localStorage.removeItem("token");
      await auth.clearCredentials();
      await flushPromises();
      resolve({ data: { access_token: tokenWithExpiry(Date.now() / 1000 + 60 * 60) } });
      await flushPromises();
      await vi.advanceTimersByTimeAsync(60_000);
      expect(readBrowserToken()).toBeNull();
      expect(auth.token).toBeNull();
      expect(mocks.post).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
