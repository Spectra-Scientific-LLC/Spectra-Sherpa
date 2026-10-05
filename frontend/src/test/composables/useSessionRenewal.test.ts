import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, onMounted, reactive } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSessionRenewal } from "@/composables/useSessionRenewal";

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
  authStore: { token: null as string | null, user: null as { id: number } | null },
}));

vi.mock("@/api/client", () => ({
  default: { post: mocks.post },
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => mocks.authStore,
}));

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
  });
  beforeEach(() => {
    localStorage.clear();
    mocks.post.mockReset();
    mocks.authStore = reactive({
      token: null as string | null,
      user: null as { id: number } | null,
    });
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
      expect(localStorage.getItem("token")).toBe(renewedToken);
      expect(mocks.authStore.token).toBe(renewedToken);
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
        if (loginSignal === "token") mocks.authStore.token = token;
        else mocks.authStore.user = { id: 7 };
        await flushPromises();
        expect(mocks.post).toHaveBeenCalledTimes(1);
        expect(mocks.authStore.token).toBe(renewed);
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
      mocks.authStore.token = token;
      let resolve!: (value: { data: { access_token: string } }) => void;
      mocks.post.mockReturnValue(
        new Promise((done) => {
          resolve = done;
        }),
      );
      wrapper = mount(Harness);
      await flushPromises();
      localStorage.removeItem("token");
      mocks.authStore.token = null;
      await flushPromises();
      resolve({ data: { access_token: tokenWithExpiry(Date.now() / 1000 + 60 * 60) } });
      await flushPromises();
      await vi.advanceTimersByTimeAsync(60_000);
      expect(localStorage.getItem("token")).toBeNull();
      expect(mocks.authStore.token).toBeNull();
      expect(mocks.post).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
