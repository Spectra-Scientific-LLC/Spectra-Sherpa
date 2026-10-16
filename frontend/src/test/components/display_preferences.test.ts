import { afterEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import DisplayPreferencesSection from "@/views/settings/DisplayPreferencesSection.vue";
import { DEFAULT_DISPLAY_PREFERENCES, useDisplayPreferences } from "@/composables/useDisplayPreferences";

afterEach(() => Object.assign(useDisplayPreferences(), DEFAULT_DISPLAY_PREFERENCES));

describe("global display defaults", () => {
  it("starts with a 300-row visual ceiling and applies changes immediately across instances", async () => {
    const first = mount(DisplayPreferencesSection);
    const second = mount(DisplayPreferencesSection);
    expect(first.get('[aria-label="Maximum display rows"]').element).toHaveProperty("value", "300");
    await first.get('[aria-label="Maximum display rows"]').setValue("500");
    expect(useDisplayPreferences().maxRows).toBe(500);
    expect(second.get('[aria-label="Maximum display rows"]').element).toHaveProperty("value", "500");
    first.unmount();
    second.unmount();
  });

  it("keeps visual preferences independent of dataset titles and target selection", () => {
    const prefs = useDisplayPreferences();
    expect(Object.keys(prefs).sort()).toEqual([
      "lineScale", "markerScale", "maxRows", "palette", "precision", "tableDensity",
    ].sort());
  });
});
