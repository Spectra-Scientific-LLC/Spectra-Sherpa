import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import RelativeTime from "@/components/RelativeTime.vue";
import { formatMetricValue, formatRelativeTime, formatTimestamp } from "@/utils/format";

const now = Date.parse("2026-10-08T12:00:00Z");
const ago = (ms: number) => new Date(now - ms).toISOString();
const MIN = 60_000;

describe("formatRelativeTime", () => {
  it("uses one wording across the app", () => {
    expect(formatRelativeTime(ago(20_000), now)).toBe("just now");
    expect(formatRelativeTime(ago(5 * MIN), now)).toBe("5 min ago");
    expect(formatRelativeTime(ago(3 * 60 * MIN), now)).toBe("3 hr ago");
    expect(formatRelativeTime(ago(30 * 60 * MIN), now)).toBe("yesterday");
    expect(formatRelativeTime(ago(4 * 24 * 60 * MIN), now)).toBe("4 days ago");
    // A clock slightly ahead of the server never reads as the future.
    expect(formatRelativeTime(ago(-30_000), now)).toBe("just now");
  });

  it("falls back to the calendar date after a week, with the year only when it differs", () => {
    expect(formatRelativeTime("2026-09-01T12:00:00Z", now)).not.toMatch(/2026/);
    expect(formatRelativeTime("2025-09-01T12:00:00Z", now)).toMatch(/2025/);
  });

  it("shows absent values as a dash and keeps unreadable text as given", () => {
    expect(formatRelativeTime(null, now)).toBe("—");
    expect(formatRelativeTime("pending", now)).toBe("pending");
  });
});

describe("formatTimestamp", () => {
  it("always names the time zone and keeps seconds on request", () => {
    const text = formatTimestamp("2026-10-08T12:34:56Z", { seconds: true });
    expect(text).toMatch(/56/);
    expect(text).toMatch(/UTC|GMT|[A-Z]{2,5}|[+-]\d/);
    expect(formatTimestamp("2026-10-08T12:34:56Z")).not.toMatch(/:56/);
  });
});

describe("formatMetricValue", () => {
  it("never rounds a small non-zero metric to zero", () => {
    expect(formatMetricValue(0.0004123)).toBe("0.000412");
    expect(formatMetricValue(0.04123)).toBe("0.0412");
    expect(formatMetricValue(1.2e-7)).toBe("1.20e-7");
    expect(formatMetricValue(0)).toBe("0");
  });

  it("keeps the established rounding for ordinary magnitudes", () => {
    expect(formatMetricValue(0.98765)).toBe("0.988");
    expect(formatMetricValue(0.5)).toBe("0.5");
    expect(formatMetricValue(12.345)).toBe("12.3");
    expect(formatMetricValue(1234.5)).toBe("1235");
    expect(formatMetricValue(-0.25)).toBe("-0.25");
    expect(formatMetricValue(Number.NaN)).toBe("—");
  });

  it("shows counts as whole numbers", () => {
    expect(formatMetricValue(64)).toBe("64");
    expect(formatMetricValue(1)).toBe("1");
    expect(formatMetricValue(1234)).toBe("1234");
  });
});

describe("RelativeTime", () => {
  it("keeps the exact time on the element", () => {
    const wrapper = mount(RelativeTime, { props: { value: "2026-10-08T12:34:56Z" } });
    const time = wrapper.get("time");
    expect(time.attributes("datetime")).toBe("2026-10-08T12:34:56.000Z");
    expect(time.attributes("title")).toBe(formatTimestamp("2026-10-08T12:34:56Z"));
  });
});
