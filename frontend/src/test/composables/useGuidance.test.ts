import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useGuidance } from "@/composables/useGuidance";

const mocks = vi.hoisted(() => ({
  appMode: { __v_isRef: true, value: "enterprise" },
  isFeatureEnabled: vi.fn((feature: string) => feature === "sherpaGuidance"),
  loadSettings: vi.fn(),
  unsubscribe: vi.fn(),
  subscribeSherpaEvents: vi.fn(),
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    appMode: mocks.appMode,
    isFeatureEnabled: mocks.isFeatureEnabled,
  }),
}));

vi.mock("@/lib/sherpaEvents", () => ({
  subscribeSherpaEvents: (...args: unknown[]) => {
    mocks.subscribeSherpaEvents(...args);
    return mocks.unsubscribe;
  },
}));

vi.mock("@/stores/guidance", () => ({
  useGuidanceStore: () => ({ loadSettings: mocks.loadSettings }),
}));

const Harness = defineComponent({
  setup() {
    const guidance = useGuidance();
    return { guidance };
  },
  render: () => null,
});

const mountGuidance = () => {
  const wrapper = mount(Harness);
  return wrapper.vm.guidance as ReturnType<typeof useGuidance>;
};

describe("useGuidance retry cancellation (review finding)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.appMode.value = "enterprise";
    mocks.loadSettings.mockReset();
    mocks.unsubscribe.mockClear();
    mocks.subscribeSherpaEvents.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("stop() during the backoff sleep resolves start() instead of hanging, and halts retries", async () => {
    // Every fetch fails → without cancellation this would walk the full
    // [500, 1500, 4000] backoff (4 loadSettings calls).
    mocks.loadSettings.mockResolvedValue(false);

    const guidance = mountGuidance();
    const started = guidance.start();

    // Let the first loadSettings() resolve and the code reach _sleep().
    await flushPromises();
    expect(mocks.loadSettings).toHaveBeenCalledTimes(1);

    // Cancel mid-sleep.  The old code only cleared the timer, so the
    // awaited promise never settled and start() hung forever.
    guidance.stop();

    // start() must resolve promptly without advancing any timer, and
    // report that startup was cancelled rather than successfully armed.
    await expect(started).resolves.toBe(false);
    // ...and the retry loop must not have continued.
    await flushPromises();
    vi.advanceTimersByTime(10_000);
    await flushPromises();
    expect(mocks.loadSettings).toHaveBeenCalledTimes(1);
    expect(mocks.unsubscribe).toHaveBeenCalledTimes(1);
  });

  it("walks the full backoff when never cancelled and the fetch keeps failing", async () => {
    mocks.loadSettings.mockResolvedValue(false);

    const guidance = mountGuidance();
    const started = guidance.start();

    await flushPromises();
    expect(mocks.loadSettings).toHaveBeenCalledTimes(1);
    for (const delay of [500, 1500, 4000]) {
      vi.advanceTimersByTime(delay);
      await flushPromises();
    }
    await expect(started).resolves.toBe(true);
    // attempt 0..3 → 4 calls, then the schedule is exhausted.
    expect(mocks.loadSettings).toHaveBeenCalledTimes(4);
  });

  it("a fresh start() after stop() is not poisoned by the prior cancellation", async () => {
    mocks.loadSettings.mockResolvedValueOnce(false);
    const guidance = mountGuidance();
    const first = guidance.start();
    await flushPromises();
    guidance.stop();
    await first;

    mocks.loadSettings.mockResolvedValue(true);
    await expect(guidance.start()).resolves.toBe(true);
    // The success path returns after a single fetch — cancelled was reset.
    expect(mocks.loadSettings).toHaveBeenLastCalledWith();
  });
});
