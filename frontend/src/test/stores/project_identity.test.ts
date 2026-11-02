import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import { registerProjectScopeReset, _clearProjectScopeRegistryForTests } from "@/stores/projectScopeRegistry";

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/api/client", () => ({ default: api }));

beforeEach(() => {
  setActivePinia(createPinia());
  _clearProjectScopeRegistryForTests();
  vi.clearAllMocks();
});

describe("project identity boundary", () => {
  const wire = (id: number) => ({ id, name: "Project", created_at: "2026-11-02", updated_at: "2026-11-02" });

  it("invalidates a navigation-owned selecting read even when transport ignores abort", async () => {
    useAuthStore().user = { id: 7, username: "first" };
    const project = useProjectStore();
    const owner = new AbortController();
    let finish!: (value: unknown) => void;
    api.get.mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const previousPreference = localStorage.getItem("spectra_sherpa_last_project_7");
    const pending = project.fetchProject(42, { signal: owner.signal });
    owner.abort();
    expect(project.isLoading).toBe(false);
    expect(api.get.mock.calls[0][1].signal.aborted).toBe(true);
    finish({ data: wire(42) });
    expect(await pending).toBeNull();
    expect(project.currentProjectId).toBeNull();
    expect(localStorage.getItem("spectra_sherpa_last_project_7")).toBe(previousPreference);
  });

  it("does not coalesce a new explicit same-project read under an abandoned navigation owner", async () => {
    useAuthStore().user = { id: 7, username: "first" };
    const project = useProjectStore();
    const owner = new AbortController();
    const finish: Array<(value: unknown) => void> = [];
    api.get.mockImplementation(() => new Promise(resolve => { finish.push(resolve); }));
    const abandoned = project.fetchProject(42, { signal: owner.signal, onInvalidated: () => owner.abort() });
    const explicit = project.fetchProject(42);
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(owner.signal.aborted).toBe(true);
    finish[1]({ data: wire(42) });
    expect((await explicit)?.id).toBe(42);
    finish[0]({ data: wire(42) });
    expect(await abandoned).toBeNull();
    expect(project.currentProjectId).toBe(42);
  });

  it("keeps normal same-owner project reads coalesced", async () => {
    const project = useProjectStore();
    let finish!: (value: unknown) => void;
    api.get.mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const first = project.fetchProject(42);
    const second = project.fetchProject(42);
    expect(api.get).toHaveBeenCalledTimes(1);
    finish({ data: wire(42) });
    expect(await first).toEqual(await second);
  });

  it("does not let the old navigation cancellation invalidate a newer project request", async () => {
    useAuthStore().user = { id: 7, username: "first" };
    const project = useProjectStore();
    const owner = new AbortController();
    const finish: Array<(value: unknown) => void> = [];
    api.get.mockImplementation(() => new Promise(resolve => { finish.push(resolve); }));
    const old = project.fetchProject(42, { signal: owner.signal, onInvalidated: () => owner.abort() });
    const latest = project.fetchProject(43);
    owner.abort();
    expect(api.get.mock.calls[1][1].signal.aborted).toBe(false);
    finish[0]({ data: wire(42) });
    await old;
    expect(project.isLoading).toBe(true);
    finish[1]({ data: wire(43) });
    await latest;
    expect(project.currentProjectId).toBe(43);
    expect(project.isLoading).toBe(false);
  });

  it("does not start an already-cancelled selection", async () => {
    const owner = new AbortController(); owner.abort();
    expect(await useProjectStore().fetchProject(42, { signal: owner.signal })).toBeNull();
    expect(api.get).not.toHaveBeenCalled();
  });

  it("does not select a fallback project after its navigation was cancelled during inventory loading", async () => {
    useAuthStore().user = { id: 7, username: "first" };
    const project = useProjectStore();
    const owner = new AbortController();
    let finish!: (value: unknown) => void;
    api.get.mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const pending = project.ensureProjectForBrowserTab({ signal: owner.signal });
    owner.abort();
    finish({ data: [wire(42)] });
    expect(await pending).toBeNull();
    expect(project.currentProjectId).toBeNull();
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.get.mock.calls[0][0]).toBe("/projects");
  });
  it("clears active context on logout, preserving each user's saved preference", () => {
    const auth = useAuthStore();
    auth.user = { id: 7, username: "first" };
    const project = useProjectStore();
    const reset = vi.fn();
    registerProjectScopeReset(reset);
    project.currentProjectId = 42;
    localStorage.setItem("spectra_sherpa_last_project_7", "42");
    auth.user = { id: 7, username: "first" };
    expect(project.currentProjectId).toBe(42);
    auth.clearCredentials();
    expect(project.currentProjectId).toBeNull();
    expect(reset).toHaveBeenCalledOnce();
    expect(localStorage.getItem("spectra_sherpa_last_project_7")).toBe("42");
  });

  it("ignores a pending project read after another user signs in", async () => {
    const auth = useAuthStore();
    auth.user = { id: 7, username: "first" };
    const project = useProjectStore();
    let finish!: (value: unknown) => void;
    api.get.mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const pending = project.fetchProject(42);
    auth.user = { id: 8, username: "second" };
    finish({ data: { id: 42, name: "Previous user's project" } });
    expect(await pending).toBeNull();
    expect(project.currentProjectId).toBeNull();
    expect(project.currentProject).toBeNull();
  });
});
