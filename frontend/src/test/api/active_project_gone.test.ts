import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import api from "@/api/client";
import { useProjectStore } from "@/stores/project";

// The interceptor uses ``window.location.href`` for the recovery redirect.
// jsdom's location is read-only by default, so we stub it.
const originalLocation = window.location;

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({ user: { id: 7 } }),
}));

describe("api client — active project 404 handler", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    // @ts-expect-error - jsdom navigation stub
    delete window.location;
    // @ts-expect-error - jsdom navigation stub
    window.location = { ...originalLocation, pathname: "/project", href: "" };
  });

  it("clears currentProjectId when a 404 hits the active project's resource path", async () => {
    const project = useProjectStore();
    project.currentProjectId = 42;
    project.currentProject = {
      id: 42,
      name: "active",
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- test fixture shape
    } as any;

    // Drive the interceptor by issuing a request against a route that the
    // adapter resolves to 404. Easiest is to mock axios's request and
    // simulate the rejection path.
    const err = {
      isAxiosError: true,
      response: { status: 404, data: { detail: "Project not found" } },
      config: { url: "/projects/42" },
    };
    await expect(api.request({ url: "/projects/42", adapter: () => Promise.reject(err) })).rejects.toBeDefined();

    // The interceptor's async lazy-import + reset runs on a microtask;
    // flush by yielding control.
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(project.currentProjectId).toBeNull();
    expect(project.currentProject).toBeNull();
  });

  it("leaves currentProjectId alone when the 404 is for a different project", async () => {
    const project = useProjectStore();
    project.currentProjectId = 42;

    const err = {
      isAxiosError: true,
      response: { status: 404 },
      config: { url: "/projects/99" },
    };
    await expect(api.request({ url: "/projects/99", adapter: () => Promise.reject(err) })).rejects.toBeDefined();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(project.currentProjectId).toBe(42);
  });

  it("ignores 404s on nested project paths (parent exists, child missing)", async () => {
    const project = useProjectStore();
    project.currentProjectId = 42;

    const err = {
      isAxiosError: true,
      response: { status: 404 },
      config: { url: "/projects/42/experiments/999" },
    };
    await expect(
      api.request({ url: "/projects/42/experiments/999", adapter: () => Promise.reject(err) }),
    ).rejects.toBeDefined();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(project.currentProjectId).toBe(42);
  });
});
