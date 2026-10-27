import { afterEach, describe, expect, it, vi } from "vitest";
import { guidanceReadyActions } from "@/lib/guidanceReadyActions";

afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks(); });

describe("Starter Guidance availability hints", () => {
  it("reports only visible enabled canonical buttons, not selections or dataset contents", () => {
    document.body.innerHTML = '<button data-guidance-ready="import_data">Load</button><button data-guidance-ready="unknown">Private text</button>';
    const button = document.querySelector("button")!;
    vi.spyOn(button, "getClientRects").mockReturnValue([{}] as unknown as DOMRectList);
    expect(guidanceReadyActions()).toEqual(["import_data"]);
    button.disabled = true;
    expect(guidanceReadyActions()).toEqual([]);
    button.disabled = false;
    button.setAttribute("aria-busy", "true");
    expect(guidanceReadyActions()).toEqual([]);
    button.removeAttribute("aria-busy");
    button.hidden = true;
    expect(guidanceReadyActions()).toEqual([]);
    button.hidden = false;
    button.style.visibility = "hidden";
    expect(guidanceReadyActions()).toEqual([]);
    button.style.visibility = "visible";
    vi.mocked(button.getClientRects).mockReturnValue([] as unknown as DOMRectList);
    expect(guidanceReadyActions()).toEqual([]);
  });
});
