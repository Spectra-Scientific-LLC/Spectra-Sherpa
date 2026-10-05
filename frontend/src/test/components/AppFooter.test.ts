import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/api", () => ({ api: { get: mocks.get } }));

describe("deployment identity in the footer", () => {
  beforeEach(() => {
    vi.resetModules();
    mocks.get.mockReset();
  });

  it("renders the requested version format and full revision tooltip", async () => {
    const commit = "a".repeat(34) + "267376";
    mocks.get.mockResolvedValue({ data: { backend_version: "0.6.0", build_commit: commit } });
    const { default: AppFooter } = await import("@/components/AppFooter.vue");
    const wrapper = mount(AppFooter);
    await flushPromises();
    expect(wrapper.find(".app-footer-brand").text()).toBe("SpectraSherpa");
    expect(wrapper.find(".app-footer-version").text()).toBe(
      `FE ${__SHERPA_FRONTEND_VERSION__} - BE 0.6.0 (267376)`,
    );
    expect(wrapper.find(".app-footer-version").attributes("title")).toContain(commit);
    wrapper.unmount();
  });

  it("keeps versions visible without a fabricated revision for an older backend", async () => {
    mocks.get.mockResolvedValue({ data: { backend_version: "0.6.0" } });
    const { default: AppFooter } = await import("@/components/AppFooter.vue");
    const wrapper = mount(AppFooter);
    await flushPromises();
    expect(wrapper.find(".app-footer-version").text()).toBe(
      `FE ${__SHERPA_FRONTEND_VERSION__} - BE 0.6.0`,
    );
    expect(wrapper.find(".app-footer-version").attributes("title")).toContain(
      "revision unavailable",
    );
    wrapper.unmount();
  });
});
