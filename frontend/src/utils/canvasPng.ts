import { downloadBlob } from "@/utils/download";

/** Canvas equivalent of the computed linear gradients used by node headers. */
export function headerPaint(
  ctx: CanvasRenderingContext2D,
  style: Pick<CSSStyleDeclaration, "backgroundImage" | "backgroundColor">,
  box: { x: number; y: number; width: number; height: number },
) {
  const angle = style.backgroundImage.match(/^linear-gradient\(([-\d.]+)deg,/);
  const colors = style.backgroundImage.match(/rgba?\([^)]*\)|#[\da-f]+/gi);
  if (!angle || !colors || colors.length < 2) return style.backgroundColor;
  const radians = (Number(angle[1]) * Math.PI) / 180;
  const dx = Math.sin(radians),
    dy = -Math.cos(radians);
  const extent = (Math.abs(box.width * dx) + Math.abs(box.height * dy)) / 2;
  const cx = box.x + box.width / 2,
    cy = box.y + box.height / 2;
  const gradient = ctx.createLinearGradient(
    cx - dx * extent,
    cy - dy * extent,
    cx + dx * extent,
    cy + dy * extent,
  );
  colors.forEach((color, index) => gradient.addColorStop(index / (colors.length - 1), color));
  return gradient;
}

export function paintCanvasBackground(
  ctx: CanvasRenderingContext2D,
  style: CSSStyleDeclaration,
  box: { x: number; y: number; width: number; height: number },
) {
  ctx.fillStyle = style.backgroundColor;
  ctx.fillRect(box.x, box.y, box.width, box.height);
  if (!style.backgroundImage.includes("radial-gradient")) return;
  const spacing = Number.parseFloat(style.getPropertyValue("--workflow-grid-size")) || 20;
  const tile = document.createElement("canvas");
  tile.width = tile.height = spacing;
  const dots = tile.getContext("2d");
  if (!dots) return;
  dots.fillStyle = style.getPropertyValue("--workflow-grid-color").trim() || "#e5e7eb";
  dots.beginPath();
  dots.arc(spacing / 2, spacing / 2, 1, 0, Math.PI * 2);
  dots.fill();
  const pattern = ctx.createPattern(tile, "repeat");
  if (pattern) {
    ctx.fillStyle = pattern;
    ctx.fillRect(box.x, box.y, box.width, box.height);
  }
}

export function pngDimensions(width: number, height: number) {
  const scale = Math.min(2, 8192 / width, 8192 / height, Math.sqrt(16_000_000 / (width * height)));
  return {
    width: Math.max(1, Math.floor(width * scale)),
    height: Math.max(1, Math.floor(height * scale)),
  };
}

export function canvasPngFilename(name: string) {
  const safe = Array.from(name, (char) =>
    char.charCodeAt(0) < 32 || /[\\/:*?"<>|]/.test(char) ? "-" : char,
  )
    .join("")
    .trim();
  return `${safe || "workflow"}.png`;
}

/** Render the complete graph, independent of the browser's scroll viewport. */
export async function saveCanvasPng(surface: HTMLElement, name: string): Promise<void> {
  const nodes = [...surface.querySelectorAll<HTMLElement>(".workflow-node")];
  if (!nodes.length) throw new Error("Add a node before exporting the canvas.");
  const origin = surface.getBoundingClientRect();
  const items = [...surface.querySelectorAll(".workflow-node, .port, .edge-label")];
  const boxes = items
    .map((item) => item.getBoundingClientRect())
    .filter((box) => box.width && box.height);
  const left = Math.min(...boxes.map((box) => box.left)) - origin.left - 32;
  const top = Math.min(...boxes.map((box) => box.top)) - origin.top - 32;
  const width = Math.ceil(Math.max(...boxes.map((box) => box.right)) - origin.left - left + 32);
  const height = Math.ceil(Math.max(...boxes.map((box) => box.bottom)) - origin.top - top + 32);
  const canvas = document.createElement("canvas");
  Object.assign(canvas, pngDimensions(width, height));
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("PNG export is unavailable in this browser.");
  ctx.scale(canvas.width / width, canvas.height / height);
  ctx.translate(-left, -top);
  paintCanvasBackground(ctx, getComputedStyle(surface.closest(".workflow-canvas") || surface), {
    x: left,
    y: top,
    width,
    height,
  });
  for (const edge of surface.querySelectorAll<SVGPathElement>(".edge-line")) {
    const style = getComputedStyle(edge);
    ctx.strokeStyle = style.stroke;
    ctx.fillStyle = style.stroke;
    ctx.lineWidth = Number.parseFloat(style.strokeWidth) || 2;
    ctx.setLineDash(
      style.strokeDasharray === "none"
        ? []
        : style.strokeDasharray.split(/[ ,]+/).map(Number.parseFloat),
    );
    ctx.stroke(new Path2D(edge.getAttribute("d") || ""));
    const length = edge.getTotalLength();
    const end = edge.getPointAtLength(length);
    const previous = edge.getPointAtLength(Math.max(0, length - 10));
    ctx.save();
    ctx.translate(end.x, end.y);
    ctx.rotate(Math.atan2(end.y - previous.y, end.x - previous.x));
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(-10, -4);
    ctx.lineTo(-10, 4);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }
  ctx.setLineDash([]);
  const rect = (element: Element) => {
    const bounds = element.getBoundingClientRect();
    return {
      x: bounds.left - origin.left,
      y: bounds.top - origin.top,
      width: bounds.width,
      height: bounds.height,
    };
  };
  for (const node of nodes) {
    const box = rect(node);
    const style = getComputedStyle(node);
    ctx.fillStyle = style.backgroundColor;
    ctx.strokeStyle = style.borderColor;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(box.x, box.y, box.width, box.height, 6);
    ctx.fill();
    ctx.stroke();
    const header = node.querySelector<HTMLElement>(".node-header");
    if (header) {
      const h = rect(header);
      ctx.fillStyle = headerPaint(ctx, getComputedStyle(header), h);
      ctx.beginPath();
      ctx.roundRect(h.x, h.y, h.width, h.height, [6, 6, 0, 0]);
      ctx.fill();
    }
    for (const element of node.querySelectorAll<HTMLElement>(
      ".node-icon, .node-label, .node-status, .data-shape-badge",
    )) {
      const box = rect(element);
      const style = getComputedStyle(element);
      const content = element.cloneNode(true) as HTMLElement;
      content.querySelectorAll(".pi").forEach((icon) => icon.remove());
      const text = (content.textContent || "").trim().replace(/\s+/g, " ");
      ctx.font = `${style.fontWeight} ${style.fontSize} sans-serif`;
      ctx.fillStyle = style.color;
      ctx.textBaseline = "middle";
      ctx.save();
      ctx.beginPath();
      ctx.rect(box.x, box.y, box.width, box.height);
      ctx.clip();
      if (element.classList.contains("data-shape-badge")) {
        const lines: string[] = [];
        let line = "";
        for (const word of text.split(" ")) {
          const candidate = line ? `${line} ${word}` : word;
          if (line && ctx.measureText(candidate).width > box.width - 8) {
            lines.push(line);
            line = word;
          } else line = candidate;
        }
        if (line) lines.push(line);
        const lineHeight = Number.parseFloat(style.fontSize) * 1.4;
        lines.forEach((line, index) =>
          ctx.fillText(line, box.x + 4, box.y + 4 + lineHeight * (index + 0.5)),
        );
      } else {
        let fitted = text;
        if (ctx.measureText(fitted).width > box.width) {
          while (fitted.length && ctx.measureText(`${fitted}…`).width > box.width)
            fitted = fitted.slice(0, -1);
          fitted += "…";
        }
        ctx.fillText(fitted, box.x, box.y + box.height / 2);
      }
      ctx.restore();
    }
    for (const port of node.querySelectorAll(".port")) {
      const box = rect(port);
      ctx.fillStyle = getComputedStyle(port).backgroundColor;
      ctx.strokeStyle = "#0f172a";
      ctx.beginPath();
      ctx.arc(box.x + box.width / 2, box.y + box.height / 2, box.width / 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }
  }
  for (const label of surface.querySelectorAll<SVGTextElement>(".edge-label")) {
    const style = getComputedStyle(label);
    ctx.fillStyle = style.fill;
    ctx.font = `${style.fontWeight} ${style.fontSize} monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    const text = [...label.childNodes]
      .filter((node) => node.nodeType === Node.TEXT_NODE)
      .map((node) => node.textContent)
      .join("")
      .trim();
    ctx.fillText(text, Number(label.getAttribute("x")), Number(label.getAttribute("y")));
  }
  const blob = await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob(
      (value) => (value ? resolve(value) : reject(new Error("Could not create PNG."))),
      "image/png",
    ),
  );
  downloadBlob(blob, canvasPngFilename(name));
}
