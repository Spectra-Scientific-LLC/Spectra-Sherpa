export interface EdgePoint {
  x: number;
  y: number;
}
export interface RoutableEdge {
  key: string;
  from: string;
  to: string;
  start: EdgePoint;
  end: EdgePoint;
  label: string;
}

/** Straight port-to-port edges with independently displaced, readable labels. */
export function routeEdges(
  edges: RoutableEdge[],
  obstacles: { x: number; y: number; width: number; height: number }[] = [],
) {
  const result = new Map<string, { path: string; label: EdgePoint }>();
  const placed: { x: number; y: number; width: number }[] = [];
  const groups = new Map<string, RoutableEdge[]>();
  for (const edge of edges) {
    const key = JSON.stringify([edge.from, edge.to]);
    groups.set(key, [...(groups.get(key) ?? []), edge]);
  }
  // Parallel bundles have the tightest constraints; reserve their lanes first.
  const span = (group: RoutableEdge[]) =>
    Math.min(...group.map((e) => Math.abs(e.end.y - e.start.y)));
  for (const [, group] of [...groups].sort(
    ([a, ga], [b, gb]) => gb.length - ga.length || span(ga) - span(gb) || a.localeCompare(b),
  )) {
    group.sort((a, b) => a.key.localeCompare(b.key));
    group.forEach((edge, index) => {
      const lane = index - (group.length - 1) / 2;
      const laneWidth = Math.max(...group.map((item) => item.label.length * 7 + 40));
      const initialX = (edge.start.x + edge.end.x) / 2 + lane * laneWidth;
      const initialY = (edge.start.y + edge.end.y) / 2;
      // Monospaced 11px labels; reserve extra room for invalid-edge badges.
      const width = edge.label.length * 7 + 16;
      let x = Math.max(width / 2 + 8, initialX);
      let y = Math.max(24, initialY);
      const blocked = (cx: number, cy: number) =>
        cx < width / 2 + 8 ||
        cy < 24 ||
        placed.some((p) => Math.abs(p.y - cy) < 34 && Math.abs(p.x - cx) < (p.width + width) / 2) ||
        obstacles.some(
          (p) =>
            cx + width / 2 > p.x - 8 &&
            cx - width / 2 < p.x + p.width + 8 &&
            cy + 4 > p.y - 8 &&
            cy - 22 < p.y + p.height + 8,
        );
      // Search nearby free lanes before pushing a label far down a dense graph.
      for (let radius = 1; blocked(x, y) && radius <= 100; radius++) {
        const candidates: EdgePoint[] = [];
        for (let dx = -radius; dx <= radius; dx++) {
          for (const dy of [-radius, radius])
            candidates.push({ x: initialX + dx * 36, y: initialY + dy * 36 });
        }
        for (let dy = -radius + 1; dy < radius; dy++) {
          for (const dx of [-radius, radius])
            candidates.push({ x: initialX + dx * 36, y: initialY + dy * 36 });
        }
        candidates.sort(
          (a, b) =>
            Math.hypot(a.x - initialX, a.y - initialY) - Math.hypot(b.x - initialX, b.y - initialY),
        );
        // Keep labels between their endpoints: a tight vertical gap should
        // send the second label sideways, not above its source node.
        const lowY = Math.min(edge.start.y, edge.end.y) - 4;
        const highY = Math.max(edge.start.y, edge.end.y) + 4;
        const free = candidates.find((p) => p.y >= lowY && p.y <= highY && !blocked(p.x, p.y));
        if (free) {
          x = free.x;
          y = free.y;
          break;
        }
      }
      if (blocked(x, y)) {
        y = Math.max(
          24,
          ...obstacles.map((p) => p.y + p.height + 40),
          ...placed.map((p) => p.y + 36),
        );
      }
      placed.push({ x, y, width });
      const { start: s, end: e } = edge;
      // Label clearance must never bend or reroute the connection itself.
      const path = `M ${s.x} ${s.y} L ${e.x} ${e.y}`;
      result.set(edge.key, { path, label: { x, y: y - 6 } });
    });
  }
  return result;
}
