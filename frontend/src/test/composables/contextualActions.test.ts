import { afterEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount, flushPromises } from "@vue/test-utils";
import ContextualActions from "@/components/ContextualActions.vue";
import { invalidateActionContext, registerContextualActions, removeContextualActions, setActionContext, useContextualActions } from "@/composables/useContextualActions";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";

const context = { surface: "run" as const, projectId: 1, runId: 42 };
afterEach(() => { removeContextualActions("test"); setActionContext(null); });

describe("contextual actions", () => {
  it("isolates availability errors and snapshots the exact run", async () => {
    const execute = vi.fn();
    registerContextualActions("test", [
      { id: "broken", label: "Broken", available: () => { throw new Error("bad capability"); }, execute },
      { id: "inspect", label: "Inspect", available: () => true, execute },
    ], () => true);
    setActionContext(context);
    const api = useContextualActions();
    expect(api.actions.value.map(item => item.label)).toEqual(["Inspect"]);
    await api.execute("test:inspect");
    expect(execute.mock.calls[0][0]).toEqual(context);
    expect(Object.isFrozen(execute.mock.calls[0][0])).toBe(true);
  });

  it("publishes an opaque application handle to Deploy extensions", async () => {
    const execute = vi.fn();
    const deployContext = {
      surface: "deploy" as const,
      projectId: 7,
      applicationHandle: "release:abc123",
    };
    registerContextualActions("test", [{
      id: "send-to-workbench",
      label: "Send to Workbench",
      available: (value) => value.surface === "deploy" && value.applicationHandle === "release:abc123",
      execute,
    }], () => true);
    setActionContext(deployContext);
    const api = useContextualActions();
    expect(api.actions.value.map((item) => item.label)).toEqual(["Send to Workbench"]);
    await api.execute("test:send-to-workbench");
    expect(execute).toHaveBeenCalledWith(deployContext, expect.any(AbortSignal));
  });

  it("aborts in-flight actions and drops late errors after context changes", async () => {
    let reject!: (error: Error) => void;
    let signal!: AbortSignal;
    registerContextualActions("test", [{ id: "inspect", label: "Inspect", available: () => true,
      execute: (_ctx, supplied) => { signal = supplied; return new Promise((_resolve, fail) => { reject = fail; }); },
    }], () => true);
    const release = setActionContext(context);
    const api = useContextualActions();
    const pending = api.execute("test:inspect");
    setActionContext({ ...context, runId: 43 });
    release();
    expect(signal.aborted).toBe(true);
    reject(new Error("stale failure"));
    await pending;
    expect(api.error.value).toBeNull();
    expect(api.actions.value).toHaveLength(1);
  });

  it("does not abort an in-flight action when the same context values are republished", async () => {
    setActivePinia(createPinia());
    const auth = useAuthStore();
    auth.user = { id: 1, username: "scientist" };
    useProjectStore().currentProjectId = 1;
    let finish!: () => void;
    let signal!: AbortSignal;
    registerContextualActions("test", [{
      id: "optimize",
      label: "Optimize",
      available: () => true,
      execute: (_ctx, supplied) => {
        signal = supplied;
        return new Promise<void>((resolve) => { finish = resolve; });
      },
    }], () => true);
    const wrapper = mount(ContextualActions, {
      props: { context },
      global: { stubs: { Button: true } },
    });
    await flushPromises();
    const pending = useContextualActions().execute("test:optimize");

    await wrapper.setProps({ context: { ...context } });
    await flushPromises();

    expect(signal.aborted).toBe(false);
    finish();
    await pending;
    wrapper.unmount();
  });

  it("republishes a mounted valid view after extension invalidation, never across users or projects", async () => {
    setActivePinia(createPinia());
    const auth = useAuthStore();
    auth.user = { id: 1, username: "scientist" };
    const project = useProjectStore();
    project.currentProjectId = 1;
    registerContextualActions("test", [{ id: "inspect", label: "Inspect", available: () => true, execute: vi.fn() }], () => true);
    const wrapper = mount(ContextualActions, { props: { context }, global: { stubs: { Button: true } } });
    await flushPromises();
    expect(useContextualActions().actions.value).toHaveLength(1);
    invalidateActionContext();
    expect(useContextualActions().actions.value).toHaveLength(0);
    await flushPromises();
    expect(useContextualActions().actions.value).toHaveLength(1);
    project.currentProjectId = 2;
    await flushPromises();
    expect(useContextualActions().actions.value).toHaveLength(0);
    project.currentProjectId = 1;
    auth.user = { id: 2, username: "other" };
    await flushPromises();
    expect(useContextualActions().actions.value).toHaveLength(0);
    wrapper.unmount();
  });
});
