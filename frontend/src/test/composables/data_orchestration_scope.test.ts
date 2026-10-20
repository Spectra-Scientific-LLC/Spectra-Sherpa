import { effectScope, reactive } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import api from "@/api/client";
import { useDatasetDefinitions } from "@/views/data/composables/useDatasetDefinitions";
import { useDatasetReadinessSelection } from "@/views/data/composables/useDatasetReadinessSelection";
import { useDatasetReadinessPreview } from "@/views/data/composables/useDatasetReadinessPreview";
import { useDatasetInspection } from "@/views/data/composables/useDatasetInspection";
import { useDatasetNavigation } from "@/views/data/composables/useDatasetNavigation";
import { useSynthesisExecution } from "@/views/data/composables/useSynthesisExecution";
import { useSynthesisSearch } from "@/views/data/composables/useSynthesisSearch";
import type { ExperimentFileAssets } from "@/types";

vi.mock("@/api/client", () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const scopes: ReturnType<typeof effectScope>[] = [];
function setup<T>(factory: () => T): T {
  const scope = effectScope();
  scopes.push(scope);
  return scope.run(factory)!;
}
afterEach(() => {
  scopes.splice(0).forEach(scope => scope.stop());
  vi.resetAllMocks();
});
const choice = {
  target: "moisture", targetType: "continuous" as const, targetUnits: "wt %",
  sourceDigest: "source", group: "specimen", readiness: null,
};

describe("Data request boundaries", () => {
  it.each(["user", "project", "dataset", "sheet"])("drops saved definitions after %s A → B → A", async (field) => {
    const scope = reactive<Record<string, number>>({ user: 1, project: 2, dataset: 3, sheet: 4 });
    const state = setup(() => useDatasetDefinitions(() => Object.values(scope)));
    const old = deferred<{ data: never[] }>();
    vi.mocked(api.get).mockReturnValueOnce(old.promise);
    const request = state.refresh(3);
    const previous = scope[field];
    scope[field] = previous + 1;
    scope[field] = previous;
    old.resolve({ data: [{ id: 99 }] as never[] });
    await request;
    expect(state.views.value).toEqual([]);
    expect(state.error.value).toBeNull();
  });

  it("does not delete after a scope switch while confirmation is open", async () => {
    const scope = reactive({ project: 1 });
    const state = setup(() => useDatasetDefinitions(() => [scope.project]));
    const accepted = deferred<boolean>();
    const request = state.remove(10, 3, () => accepted.promise);
    scope.project = 2;
    scope.project = 1;
    accepted.resolve(true);
    await request;
    expect(api.delete).not.toHaveBeenCalled();
    expect(state.busy.value).toBe(false);
  });

  it("does not let an old readiness error or finally finish a new read", async () => {
    const scope = reactive({ dataset: 1 });
    const state = setup(() => useDatasetReadinessSelection(() => [scope.dataset]));
    const old = deferred<{ data: unknown }>();
    const current = deferred<{ data: unknown }>();
    vi.mocked(api.get).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    const first = state.refresh(1);
    scope.dataset = 2;
    const second = state.refresh(2);
    old.reject(new Error("old failure"));
    await first;
    expect(state.status.value).toBe("loading");
    expect(state.hydrated.value).toBe(false);
    current.resolve({ data: { metadata: { analysis_selection: {
      selected_target: "moisture", target_type: "continuous", group_column: "specimen",
    } } } });
    await second;
    expect(state.choice.value.target).toBe("moisture");
    expect(state.hydrated.value).toBe(true);
  });

  it("captures readiness write destination and suppresses a retired save failure", async () => {
    const scope = reactive({ dataset: 1, sheet: 1 });
    const state = setup(() => useDatasetReadinessSelection(() => [scope.dataset, scope.sheet]));
    const old = deferred<{ data: unknown }>();
    vi.mocked(api.put).mockReturnValueOnce(old.promise);
    const saving = state.save(1, choice);
    scope.sheet = 2; scope.sheet = 1;
    old.reject(new Error("old save failure"));
    await expect(saving).resolves.toBeUndefined();
    expect(api.put).toHaveBeenCalledWith("/experiments/1/analysis-selection",
      expect.objectContaining({ selected_target: "moisture" }), { signal: expect.any(AbortSignal) });
    expect(state.status.value).not.toBe("error");
    expect(state.choice.value.target).toBe("");
  });

  it("keeps source metadata when a saved definition supersedes readiness hydration", async () => {
    const state = setup(() => useDatasetReadinessSelection(() => [1]));
    vi.mocked(api.get).mockResolvedValue({ data: { metadata: { source_kind: "reference" } } });
    await state.refresh(1);
    state.invalidate();
    expect(state.metadata.value).toEqual({ source_kind: "reference" });
  });

  it("rejects retired compatibility previews independently of their retained cache", async () => {
    const scope = reactive({ target: "A" });
    const state = setup(() => useDatasetReadinessPreview(() => [scope.target]));
    const old = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(old.promise);
    const loading = state.load(null, { group_column: "specimen" });
    scope.target = "B"; scope.target = "A";
    old.reject(new Error("late preview failure"));
    await loading;
    expect(state.readiness.value).toBeNull();
    expect(state.error.value).toBeNull();
    expect(state.loading.value).toBe(false);
  });

  it("an old inventory rejection cannot evict the replacement after A → B → A", async () => {
    const scope = reactive({ dataset: 1 });
    const old = deferred<ExperimentFileAssets>();
    const fresh = deferred<ExperimentFileAssets>();
    const fetch = vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const state = setup(() => useDatasetInspection(() => [scope.dataset], fetch));
    const first = state.inventory(1, 2).catch(() => null);
    const ticket = state.contents.begin();
    scope.dataset = 2; scope.dataset = 1;
    const replacement = state.inventory(1, 2);
    old.reject(new Error("retired"));
    await first;
    expect(ticket.isCurrent()).toBe(false);
    expect(state.inventories.get("1:2")).toBe(replacement);
    fresh.resolve({ assets: [] } as unknown as ExperimentFileAssets);
    await replacement;
  });

  it("explicit selection retires bootstrap and route restoration before another request starts", () => {
    const navigation = setup(() => useDatasetNavigation(() => [1]));
    const bootstrap = navigation.bootstrap.begin();
    const route = navigation.route.begin();
    navigation.choose();
    expect(bootstrap.isCurrent()).toBe(false);
    expect(route.isCurrent()).toBe(false);
    expect(navigation.focus.begin().isCurrent()).toBe(true);
  });
});

describe("Synthesis request boundaries", () => {
  it.each(["project", "recipe"])("discards preview after %s A → B → A", async (field) => {
    const scope = reactive<Record<string, number>>({ project: 1, recipe: 1 });
    const state = setup(() => useSynthesisExecution(() => [scope.project, scope.recipe]));
    const old = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(old.promise);
    const preview = state.preview({ components: [] });
    scope[field] = 2; scope[field] = 1;
    old.resolve({ data: { seed: 42 } });
    expect(await preview).toBeUndefined();
    expect(state.previewing.value).toBe(false);
  });

  it("an old preview finally cannot hide the next preview spinner", async () => {
    const state = setup(() => useSynthesisExecution(() => [1]));
    const old = deferred<{ data: unknown }>();
    const fresh = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const first = state.preview({});
    const next = state.preview({});
    old.reject(new Error("late failure"));
    await first;
    expect(state.previewing.value).toBe(true);
    fresh.resolve({ data: { seed: 7 } });
    expect(await next).toEqual({ seed: 7 });
    expect(state.previewing.value).toBe(false);
  });

  it("stops a bundle after invalidation without redirecting remaining writes", async () => {
    const scope = reactive({ project: 1 });
    const state = setup(() => useSynthesisExecution(() => [scope.project]));
    const old = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(old.promise);
    const save = state.save(scope.project, [
      { name: "first", payload: { seed: 1 } }, { name: "second", payload: { seed: 2 } },
    ]);
    scope.project = 2;
    old.resolve({ data: { experiment_id: 99, result: { seed: 1 } } });
    expect(await save).toBeUndefined();
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith("/synthesis/save",
      { name: "first", seed: 1, experiment_id: null, project_id: 1 },
      { signal: expect.any(AbortSignal) });
    expect(state.saving.value).toBe(false);
  });

  it("snapshots every bundle payload before the first write", async () => {
    const state = setup(() => useSynthesisExecution(() => [1]));
    const old = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(old.promise).mockResolvedValueOnce({
      data: { experiment_id: 8, result: { seed: 2 } },
    });
    const items = [{ name: "first", payload: { seed: 1 } }, { name: "second", payload: { seed: 2 } }];
    const save = state.save(1, items);
    items[1].name = "changed";
    items[1].payload.seed = 999;
    old.resolve({ data: { experiment_id: 8, result: { seed: 1 } } });
    expect((await save)?.count).toBe(2);
    expect(api.post).toHaveBeenNthCalledWith(2, "/synthesis/save",
      { seed: 2, name: "second", experiment_id: 8, project_id: 1 },
      { signal: expect.any(AbortSignal) });
  });

  it("does not surface a save error in a reopened recipe", async () => {
    const scope = reactive({ recipe: 1 });
    const state = setup(() => useSynthesisExecution(() => [scope.recipe]));
    const old = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(old.promise);
    const save = state.save(1, [{ name: "old", payload: {} }]);
    scope.recipe = 2;
    old.reject(new Error("old save failed"));
    await expect(save).resolves.toBeUndefined();
    expect(state.saving.value).toBe(false);
  });

  it("discards old search results after query A → B → A before the debounce fires", async () => {
    const scope = reactive({ project: 1, query: "ethanol", source: "nist_quant_ir" });
    const state = setup(() => useSynthesisSearch(() => [scope.project], () => scope));
    const old = deferred<{ data: unknown }>();
    vi.mocked(api.get).mockReturnValueOnce(old.promise);
    const searching = state.search();
    scope.query = "water"; scope.query = "ethanol";
    old.resolve({ data: { components: [{ id: "ethanol" }] } });
    await searching;
    expect(state.results.value).toEqual([]);
    expect(state.searching.value).toBe(false);
  });
});
