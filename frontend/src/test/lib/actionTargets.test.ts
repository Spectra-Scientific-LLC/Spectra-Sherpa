import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { findActionTarget, waitForActionTarget } from "@/lib/actionTargets";

describe("actionTargets", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    // DOM emulators have no layout engine; model a rendered button explicitly.
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  describe("findActionTarget", () => {
    it("returns null for nullish ids", () => {
      expect(findActionTarget(null)).toBeNull();
      expect(findActionTarget(undefined)).toBeNull();
      expect(findActionTarget("")).toBeNull();
    });

    it("matches by exact data-action value", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action", "create_folder_watch");
      button.textContent = "New Watch";
      document.body.appendChild(button);

      const found = findActionTarget("create_folder_watch");
      expect(found).toBe(button);
    });

    it("returns null when no element matches", () => {
      const button = document.createElement("button");
      button.setAttribute("data-action", "import_data");
      document.body.appendChild(button);
      expect(findActionTarget("create_folder_watch")).toBeNull();
    });

    it("escapes embedded quotes so a malicious action id can't break the selector", () => {
      // Defense-in-depth: action ids come from the ontology and are
      // validated server-side, but the helper should still be safe
      // against unexpected input.
      expect(() => findActionTarget('a"][data-action="b')).not.toThrow();
    });

    it("returns the first match when duplicates exist", () => {
      const a = document.createElement("button");
      a.setAttribute("data-action", "import_data");
      a.id = "first";
      const b = document.createElement("button");
      b.setAttribute("data-action", "import_data");
      b.id = "second";
      document.body.append(a, b);

      const found = findActionTarget("import_data");
      expect(found?.id).toBe("first");
    });

    it.each(["disabled", "hidden", "busy", "inert", "no-layout"])("skips a %s toolbar duplicate", (state) => {
      document.body.innerHTML = '<button data-action="open_analysis_starters" id="toolbar"></button><button data-action="open_analysis_starters" id="selection"></button>';
      const toolbar = document.getElementById("toolbar") as HTMLButtonElement;
      if (state === "disabled") toolbar.disabled = true;
      if (state === "hidden") toolbar.hidden = true;
      if (state === "busy") toolbar.setAttribute("aria-busy", "true");
      if (state === "inert") toolbar.setAttribute("inert", "");
      if (state === "no-layout") Object.defineProperty(toolbar, "getClientRects", { value: () => [] });
      expect(findActionTarget("open_analysis_starters")?.id).toBe("selection");
    });
  });

  describe("waitForActionTarget", () => {
    it("returns the target immediately when already present", async () => {
      const button = document.createElement("button");
      button.setAttribute("data-action", "new_project");
      document.body.appendChild(button);

      const found = await waitForActionTarget("new_project", 1000);
      expect(found).toBe(button);
    });

    it("returns the target once it appears within the timeout", async () => {
      const promise = waitForActionTarget("create_folder_watch", 1000, 20);
      // Mount the target a tick later — simulates a route-change
      // followed by destination-view onMounted.
      setTimeout(() => {
        const button = document.createElement("button");
        button.setAttribute("data-action", "create_folder_watch");
        document.body.appendChild(button);
      }, 60);

      const found = await promise;
      expect(found).not.toBeNull();
      expect(found?.getAttribute("data-action")).toBe("create_folder_watch");
    });

    it("resolves with null when the timeout elapses without a match", async () => {
      const found = await waitForActionTarget("never_mounts", 100, 20);
      expect(found).toBeNull();
    });
  });
});
