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
