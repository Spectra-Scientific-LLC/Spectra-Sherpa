import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadBlob } from "@/utils/download";
import {
  canvasPngFilename,
  pngDimensions,
  saveCanvasPng,
  headerPaint,
  paintCanvasBackground,
} from "@/utils/canvasPng";

vi.mock("@/utils/download", () => ({ downloadBlob: vi.fn() }));
afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("canvas PNG export", () => {
  it.each([
    ["rgb(59, 130, 246)", "rgb(37, 99, 235)"],
    ["rgb(34, 197, 94)", "rgb(22, 163, 74)"],
    ["rgb(139, 92, 246)", "rgb(124, 58, 237)"],
  ])("preserves header gradient stops %s to %s", (start, end) => {
    const gradient = { addColorStop: vi.fn() };
    const ctx = { createLinearGradient: vi.fn(() => gradient) };
    expect(
      headerPaint(
        ctx as unknown as CanvasRenderingContext2D,
        {
          backgroundImage: `linear-gradient(135deg, ${start}, ${end})`,
          backgroundColor: "rgba(0, 0, 0, 0)",
        },
        { x: 10, y: 20, width: 160, height: 40 },
      ),
    ).toBe(gradient);
    expect(gradient.addColorStop.mock.calls).toEqual([
      [0, start],
      [1, end],
    ]);
    expect(ctx.createLinearGradient).toHaveBeenCalledOnce();
  });
  it("uses the canvas background and grid colors instead of white", () => {
    const fills: unknown[] = [];
    const pattern = {};
    const ctx = {
      fillStyle: "",
      fillRect: vi.fn(() => fills.push(ctx.fillStyle)),
      createPattern: vi.fn(() => pattern),
    };
    const dots = { fillStyle: "", beginPath: vi.fn(), arc: vi.fn(), fill: vi.fn() };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      dots as unknown as CanvasRenderingContext2D,
    );
    const style = {
      backgroundColor: "rgb(254, 251, 255)",
      backgroundImage: "radial-gradient(circle, rgb(229, 231, 235) 1px, transparent 1.5px)",
      getPropertyValue: (name: string) => (name === "--workflow-grid-size" ? "20px" : "#e5e7eb"),
    };
    paintCanvasBackground(
      ctx as unknown as CanvasRenderingContext2D,
      style as CSSStyleDeclaration,
      { x: 0, y: 0, width: 500, height: 400 },
    );
    expect(fills).toEqual(["rgb(254, 251, 255)", pattern]);
    expect(dots.fillStyle).toBe("#e5e7eb");
    expect(dots.arc).toHaveBeenCalledWith(10, 10, 1, 0, Math.PI * 2);
  });
  it("renders off-screen nodes and downloads a PNG named for the sheet", async () => {
    const surface = document.createElement("div");
    surface.innerHTML =
      '<div class="workflow-node"><span class="node-label">Offscreen node</span></div>';
    const node = surface.querySelector(".workflow-node")!;
    const label = surface.querySelector(".node-label")!;
    vi.spyOn(surface, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 600, 400));
    vi.spyOn(node, "getBoundingClientRect").mockReturnValue(new DOMRect(2000, 1500, 160, 100));
    vi.spyOn(label, "getBoundingClientRect").mockReturnValue(new DOMRect(2010, 1510, 140, 20));
    const context = {
      fillRect: vi.fn(),
      scale: vi.fn(),
      translate: vi.fn(),
      setLineDash: vi.fn(),
      beginPath: vi.fn(),
      roundRect: vi.fn(),
      fill: vi.fn(),
      stroke: vi.fn(),
      save: vi.fn(),
      rect: vi.fn(),
      clip: vi.fn(),
      fillText: vi.fn(),
      restore: vi.fn(),
      measureText: (text: string) => ({ width: text.length * 5 }),
    };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      context as unknown as CanvasRenderingContext2D,
    );
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback) =>
      callback(new Blob(["png"], { type: "image/png" })),
    );
    await saveCanvasPng(surface, "My workflow");
    expect(context.translate).toHaveBeenCalledWith(-1968, -1468);
    expect(context.fillText).toHaveBeenCalledWith("Offscreen node", 2010, 1520);
    expect(downloadBlob).toHaveBeenCalledWith(
      expect.objectContaining({ type: "image/png" }),
      "My workflow.png",
    );
  });
  it("exports at double resolution for normal canvases", () => {
    expect(pngDimensions(1200, 900)).toEqual({ width: 2400, height: 1800 });
  });
  it("bounds image memory and dimensions for large and narrow graphs", () => {
    for (const [w, h] of [
      [10000, 10000],
      [100000, 100],
      [100, 100000],
    ]) {
      const size = pngDimensions(w, h);
      expect(size.width).toBeLessThanOrEqual(8192);
      expect(size.height).toBeLessThanOrEqual(8192);
      expect(size.width * size.height).toBeLessThanOrEqual(16000000);
    }
  });
  it("uses a safe sheet-based filename", () => {
    expect(canvasPngFilename("PLS / Test: α")).toBe("PLS - Test- α.png");
    expect(canvasPngFilename("  ")).toBe("workflow.png");
    expect(canvasPngFilename("x\ny")).toBe("x-y.png");
  });
  it("reports an empty sheet without downloading a blank image", async () => {
    await expect(saveCanvasPng(document.createElement("div"), "empty")).rejects.toThrow(
      "Add a node",
    );
  });
});
