/**
 * Tests for `useTopbarMenu` — the OSS-owned menu-extension API that the
 * server-provided auth module uses to contribute user-menu entries at
 * runtime (v0.4.1 Phase 1 contract, pinned by Phase 3).
 *
 * Important behaviors covered:
 * - singleton backing store — all callers share the same reactive list
 * - `addItems` appends, preserving order across multiple calls
 * - `removeItems(contributorId)` removes only that contributor's items
 * - `clear()` wipes all contributions
 * - `items` never leaks the internal `__contributorId` tag
 * - empty / non-array input is a no-op
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTopbarMenu } from "@/composables/useTopbarMenu";

describe("useTopbarMenu", () => {
  beforeEach(() => {
    // Singleton state spans tests; start each case from a clean slate.
    useTopbarMenu().clear();
  });

  describe("singleton semantics", () => {
    it("returns a shared backing store across callers", () => {
      const a = useTopbarMenu();
      const b = useTopbarMenu();

      a.addItems([{ label: "From A" }], "caller-a");

      expect(b.items.value).toHaveLength(1);
      expect(b.items.value[0].label).toBe("From A");
    });
  });

  describe("addItems", () => {
    it("appends items in call order", () => {
      const menu = useTopbarMenu();
      menu.addItems([{ label: "One" }], "c1");
      menu.addItems([{ label: "Two" }, { label: "Three" }], "c2");

      expect(menu.items.value.map((i) => i.label)).toEqual(["One", "Two", "Three"]);
    });

    it("is a no-op when items is empty", () => {
      const menu = useTopbarMenu();
      menu.addItems([], "c1");

      expect(menu.items.value).toEqual([]);
    });

    it("is a no-op when items is not an array (defensive)", () => {
      const menu = useTopbarMenu();
      // Server modules live outside OSS's type system; guard against the
      // runtime case where a misbehaving contributor passes something
      // that is not an array.
      menu.addItems(null as unknown as []);
      menu.addItems(undefined as unknown as []);

      expect(menu.items.value).toEqual([]);
    });

    it("does not leak the internal contributorId tag via `items`", () => {
      const menu = useTopbarMenu();
      menu.addItems([{ label: "Tagged" }], "contributor-x");

      expect(menu.items.value[0]).toEqual({ label: "Tagged" });
      expect(menu.items.value[0]).not.toHaveProperty("__contributorId");
    });

    it("defaults to a stable anonymous contributor when no id is given", () => {
      const menu = useTopbarMenu();
      menu.addItems([{ label: "Implicit" }]);

      // Removing with the documented default id should drop the item.
      menu.removeItems("anonymous");
      expect(menu.items.value).toEqual([]);
    });
  });

  describe("removeItems", () => {
    it("removes only the items tagged with the given contributorId", () => {
      const menu = useTopbarMenu();
      menu.addItems([{ label: "Auth: Profile" }], "auth-module");
      menu.addItems([{ label: "Admin: Users" }], "admin-module");
      menu.addItems([{ label: "Auth: Sign out" }], "auth-module");

      menu.removeItems("auth-module");

      expect(menu.items.value.map((i) => i.label)).toEqual(["Admin: Users"]);
    });

    it("is a no-op when the contributorId has no items", () => {
      const menu = useTopbarMenu();
      menu.addItems([{ label: "Kept" }], "kept");

      menu.removeItems("never-added");

      expect(menu.items.value.map((i) => i.label)).toEqual(["Kept"]);
    });
  });

  describe("clear", () => {
    it("wipes every contribution regardless of contributorId", () => {
      const menu = useTopbarMenu();
      menu.addItems([{ label: "A" }], "m1");
      menu.addItems([{ label: "B" }], "m2");
      menu.addItems([{ label: "C" }], "m3");

      menu.clear();

      expect(menu.items.value).toEqual([]);
    });
  });

  describe("items reactivity", () => {
    it("reflects mutations synchronously through the returned ref", () => {
      const menu = useTopbarMenu();

      const before = menu.items.value;
      menu.addItems([{ label: "Later" }], "c1");
      const after = menu.items.value;

      expect(before).not.toBe(after);
      expect(after.map((i) => i.label)).toEqual(["Later"]);
    });

    it("invokes command callbacks attached to a contribution", () => {
      const menu = useTopbarMenu();
      const command = vi.fn();
      menu.addItems([{ label: "Click me", command }], "c1");

      menu.items.value[0].command?.();

      expect(command).toHaveBeenCalledTimes(1);
    });
  });
});
