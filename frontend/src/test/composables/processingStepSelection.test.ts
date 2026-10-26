import { effectScope, ref, nextTick } from "vue";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  useProcessingStepSelection,
  type StepEntry,
  type StepPortfolio,
} from "@/views/data/composables/useProcessingStepSelection";
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/api/client", () => ({ default: api }));
const scopes: ReturnType<typeof effectScope>[] = [];
afterEach(() => scopes.splice(0).forEach((s) => s.stop()));
const files = [{ id: 5, file_path: "raw/Day_2024_08_05.nc" }] as StepEntry["file"][];
const catalog = {
  date: "2024-08-05",
  process_file_id: 6,
  source_sha256: "a",
  process_sha256: "b",
  wafers: [
    {
      asset_id: "Wafer_01",
      steps: [
        { step_id: "etch", label: "Etch" },
        { step_id: "passivation", label: "Passivation" },
      ],
    },
  ],
};
const selection = {
  experiment_id: 4,
  file_id: 5,
  process_file_id: 6,
  asset_id: "Wafer_01",
  step_id: "production" as const,
};
const saved = {
  id: 1,
  project_id: 6,
  name: "Etch",
  selection_sha256: "a".repeat(64),
  selection: {
    partitions: [{ ...selection, source_sha256: "a", process_sha256: "b", intervals: [] }],
  },
} as unknown as StepPortfolio;
function setup() {
  const identity = ref(4);
  const scope = effectScope();
  scopes.push(scope);
  const state = scope.run(() =>
    useProcessingStepSelection(
      () => [identity.value],
      () => 6,
    ),
  )!;
  return { state, identity };
}
beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation(async (url: string) => ({
    data: url.endsWith("time-series-portfolios") ? [] : url.endsWith("/files") ? files : catalog,
  }));
  api.post.mockResolvedValue({ data: { dataset: { data: [[1, 2]] } } });
});
it("loads retained catalogs without segmentation, selection or averaging", async () => {
  const { state } = setup();
  await state.load([4, 8], files, 4);
  expect(state.entries.value).toHaveLength(2);
  expect(state.selections.value).toEqual([]);
  expect(api.post).not.toHaveBeenCalled();
  expect(api.get.mock.calls.map((c) => c[0])).toContain("/experiments/8/files/5/bosch-steps");
});
it("rejects stale project data even if transport ignores cancellation", async () => {
  const { state, identity } = setup();
  let finish!: (value: unknown) => void;
  api.get.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const pending = state.load([4], files, 4);
  identity.value = 9;
  finish({ data: [saved] });
  await pending;
  expect(state.portfolios.value).toEqual([]);
  expect(state.entries.value).toEqual([]);
  expect(api.get).toHaveBeenCalledTimes(1);
});
it("saves exact selectors and restores immutable portfolio identity", async () => {
  const { state } = setup();
  await state.load([4], files, 4);
  state.selections.value = [selection];
  await nextTick();
  api.post.mockResolvedValue({ data: saved });
  await state.save("Etch");
  expect(api.post.mock.calls[0][1]).toEqual({ name: "Etch", selections: [selection] });
  expect(state.selectedPortfolio.value?.selection_sha256).toBe(saved.selection_sha256);
  state.clear();
  await state.show(saved);
  expect(state.selections.value).toEqual([selection]);
  expect(state.selectedPortfolio.value?.id).toBe(1);
});
it("does not apply a save receipt to a changed selection", async () => {
  const { state } = setup();
  state.selections.value = [selection];
  await nextTick();
  let finish!: (value: unknown) => void;
  api.post.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const pending = state.save("Etch");
  state.selections.value = [];
  finish({ data: saved });
  await pending;
  expect(state.selectedPortfolio.value).toBeNull();
});
it("previews original phase spectra with explicit wafer identity", async () => {
  const { state } = setup();
  await state.load([4], files, 4);
  state.selections.value = [selection];
  await nextTick();
  await state.compare();
  expect(api.post.mock.calls.map((c) => c[1].step_id)).toEqual(["etch", "passivation"]);
  expect(state.preview.value[0].members).toHaveLength(2);
  expect(
    api.post.mock.calls.every((c) => c[1].max_rows === 4 && c[1].asset_id === "Wafer_01"),
  ).toBe(true);
});

it('does not reclassify sources from an old dataset file response', async () => {
 const {state, identity}=setup();
 let finish!: (value: unknown) => void;
 api.get.mockImplementationOnce(async()=>({data:[]}));
 api.get.mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 const pending=state.load([8],files,4);
 await nextTick();
 identity.value=9;
 finish({data:files});
 await pending;
 expect(state.sourceExperimentIds.value).toEqual([]);
 expect(state.entries.value).toEqual([]);
 expect(api.get).toHaveBeenCalledTimes(2);
});
