import { afterEach, describe, expect, it, vi } from "vitest";

import { initialTab, readRememberedTab, writeRememberedTab } from "@/utils/rememberedTab";

const TABS = ["run_history", "inspect", "compare", "models", "batch"] as const;
const KEY = "test_active_tab_7_3";

describe("remembered workspace tab", () => {
  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("stores the tab by id and restores it", () => {
    writeRememberedTab(KEY, "compare");
    expect(localStorage.getItem(KEY)).toBe("compare");
    expect(readRememberedTab(KEY, TABS)).toBe("compare");
  });

  it("ignores a value that is no longer a tab, including a legacy position", () => {
    localStorage.setItem(KEY, "retired_tab");
    expect(readRememberedTab(KEY, TABS)).toBeNull();
    localStorage.setItem(KEY, "2");
    expect(readRememberedTab(KEY, TABS)).toBeNull();
  });

  it("never reopens a tab that needs context", () => {
    writeRememberedTab(KEY, "inspect");
    expect(readRememberedTab(KEY, TABS, (id) => id !== "inspect")).toBeNull();
  });

  it("lets the URL win, then memory, then the default", () => {
    expect(initialTab("batch", "compare", TABS, "run_history")).toBe("batch");
    expect(initialTab("nonsense", "compare", TABS, "run_history")).toBe("compare");
    expect(initialTab(undefined, null, TABS, "run_history")).toBe("run_history");
  });

  it("works without storage", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(() => writeRememberedTab(KEY, "compare")).not.toThrow();
    expect(readRememberedTab(KEY, TABS)).toBeNull();
  });
});
