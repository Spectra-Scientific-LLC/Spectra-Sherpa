import { describe, expect, it } from "vitest";
import { routeEdges, type RoutableEdge } from "@/utils/edgeRouting";

const edge = (key: string, overrides: Partial<RoutableEdge> = {}): RoutableEdge => ({
  key,
  from: "split",
  to: "pls",
  start: { x: 100, y: 200 },
  end: { x: 100, y: 500 },
  label: `${key} · SpectralDataset`,
  ...overrides,
});

describe("workflow edge routing", () => {
  it("separates parallel connections and their labels", () => {
    const routes = routeEdges([
      edge("X_train"),
      edge("y_train", { start: { x: 120, y: 200 }, end: { x: 120, y: 500 } }),
    ]);
    expect(routes.get("X_train")!.path).not.toBe(routes.get("y_train")!.path);
    const a = routes.get("X_train")!.label;
    const b = routes.get("y_train")!.label;
    expect(Math.abs(a.y - b.y) >= 34 || Math.abs(a.x - b.x) >= 190).toBe(true);
  });
  it("is stable when saved edges are reordered", () => {
    const edges = [edge("X_train"), edge("y_train"), edge("test", { to: "test" })];
    expect([...routeEdges(edges)]).toEqual([...routeEdges([...edges].reverse())]);
  });
  it("preserves distinct port endpoints", () => {
    const path = routeEdges([
      edge("y_train", { start: { x: 136, y: 231 }, end: { x: 56, y: 490 } }),
    ]).get("y_train")!.path;
    expect(path).toBe("M 136 231 L 56 490");
  });
  it("avoids labels colliding across different node pairs", () => {
    const routes = [
      ...routeEdges([edge("a"), edge("b", { to: "test" }), edge("c", { from: "other" })]).values(),
    ];
    for (let i = 1; i < routes.length; i++) {
      expect(Math.abs(routes[i].label.y - routes[i - 1].label.y)).toBeGreaterThanOrEqual(34);
    }
  });
  it("supports horizontal, reversed, and coincident endpoints without invalid geometry", () => {
    for (const end of [
      { x: 500, y: 200 },
      { x: 10, y: 0 },
      { x: 100, y: 200 },
    ]) {
      const result = routeEdges([edge("a", { end })]).get("a")!;
      expect(result.path).not.toMatch(/NaN|Infinity/);
      expect(result.path).toBe(`M 100 200 L ${end.x} ${end.y}`);
    }
  });
  it("updates routes as nodes move and accepts an empty graph", () => {
    expect(routeEdges([]).size).toBe(0);
    expect(routeEdges([edge("a")]).get("a")).not.toEqual(
      routeEdges([edge("a", { end: { x: 900, y: 900 } })]).get("a"),
    );
  });
  it("clears node bodies without sending tight parallel labels above the source", () => {
    const inputs = [edge("X_train"), edge("y_train")].map((e) => ({
      ...e,
      start: { x: 210, y: 614 },
      end: { x: 230, y: 646 },
    }));
    const obstacles = [
      { x: 170, y: 460, width: 160, height: 140 },
      { x: 176, y: 652, width: 160, height: 140 },
    ];
    const routes = routeEdges(inputs, obstacles);
    for (const route of routes.values()) {
      expect(route.label.y).toBeGreaterThanOrEqual(604);
      expect(route.label.y).toBeLessThanOrEqual(644);
      expect(route.label.x).toBeLessThan(600);
    }
  });
});
