import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

// Hoisted axios-style mock for the api client.  Each test sets the mock's
// resolved backend version before importing the composable via dynamic
// import to ensure the module-level state is fresh.
const mocks = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { get: mocks.get },
}));

const reloadComposable = async () => {
  vi.resetModules();
  return import("@/composables/useAppVersion");
};

describe("useAppVersion", () => {
  beforeEach(() => {
    mocks.get.mockReset();
  });

  it("exposes the build-time frontend version constant", async () => {
    mocks.get.mockResolvedValue({ data: { backend_version: "0.0.0" } });
    const { useAppVersion } = await reloadComposable();
    const { frontendVersion } = useAppVersion();
    expect(frontendVersion).toMatch(/^\d+\.\d+\.\d+/);
  });

  it("fetches backend version on first use and caches it", async () => {
    mocks.get.mockResolvedValue({ data: { backend_version: "9.9.9" } });
    const { useAppVersion } = await reloadComposable();
    const v1 = useAppVersion();
    await nextTick();
    await nextTick();
    expect(v1.backendVersion.value).toBe("9.9.9");

    // Second consumer reuses cached value — no extra HTTP call.
    const v2 = useAppVersion();
    expect(v2.backendVersion.value).toBe("9.9.9");
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });

  it("flags drift when frontend and backend differ in major.minor", async () => {
    // Frontend constant is whatever package.json carries; pick a backend
    // version with a guaranteed-different major to assert drift.
    mocks.get.mockResolvedValue({ data: { backend_version: "99.0.0" } });
    const { useAppVersion } = await reloadComposable();
    const { versionDrift } = useAppVersion();
    await nextTick();
    await nextTick();
    expect(versionDrift.value).toBe(true);
  });

  it("does not flag drift when only the patch version differs", async () => {
    // Construct a backend version with the same major.minor as the frontend
    // but a different patch.  Patches are explicitly excluded from drift
    // checks because they shouldn't trigger a "reload your bundle" prompt.
    const frontendMm = __SHERPA_FRONTEND_VERSION__.match(/^(\d+)\.(\d+)/);
    expect(frontendMm).not.toBeNull();
    mocks.get.mockResolvedValue({
      data: { backend_version: `${frontendMm![1]}.${frontendMm![2]}.999` },
    });
    const { useAppVersion } = await reloadComposable();
    const { versionDrift } = useAppVersion();
    await nextTick();
    await nextTick();
    expect(versionDrift.value).toBe(false);
  });

  it("records the error and leaves backendVersion null on fetch failure", async () => {
    mocks.get.mockRejectedValue(new Error("network down"));
    const { useAppVersion } = await reloadComposable();
    const { backendVersion, loadError } = useAppVersion();
    await nextTick();
    await nextTick();
    expect(backendVersion.value).toBeNull();
    expect(loadError.value).toBe("network down");
  });
});
