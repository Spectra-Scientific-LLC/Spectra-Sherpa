import { createPinia, setActivePinia } from "pinia";
import { reactive } from "vue";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import api from "@/api/client";
import SynthesisPanel from "@/views/data/SynthesisPanel.vue";
import ConcentrationCurveEditor from "@/components/ConcentrationCurveEditor.vue";
import { useSynthesisStore, type SelectedComponent } from "@/stores/synthesis";

const mocks = vi.hoisted(() => ({
  project: { currentProjectId: 1, fetchProjects: vi.fn() },
  data: { fetchCatalog: vi.fn(), fetchExperiments: vi.fn() },
  auth: { user: { id: 1 } },
  toast: vi.fn(),
}));
vi.mock("@/stores/project", () => ({ useProjectStore: () => mocks.project }));
vi.mock("@/stores/data", () => ({ useDataStore: () => mocks.data }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => mocks.auth }));
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: mocks.toast }) }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/api/client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
mocks.project = reactive(mocks.project);
mocks.auth = reactive(mocks.auth);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
type BundleItem = { id: string; name: string; payload: { components: never[] } };
type Panel = {
  onSourceOrGridChange(): void;
  loadSpectrum(component: SelectedComponent): Promise<void>;
  saveSynthesis(): Promise<void>;
  previewSynthesis(): Promise<void>;
  reopenRecipe(recipe: Record<string, unknown>, title: string): Promise<void>;
  synthesisBundle: BundleItem[];
  concentrationTraces: { x: number[]; y: number[] }[];
};
function mountPanel() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const wrapper = shallowMount(SynthesisPanel, { global: {
    plugins: [pinia], stubs: { Panel: { template: "<section><slot /></section>" } },
  } });
  const panel = wrapper.vm.$.setupState as unknown as Panel;
  return { wrapper, panel, store: useSynthesisStore() };
}
beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  mocks.project.currentProjectId = 1;
  vi.mocked(api.get).mockResolvedValue({ data: { sources: [], components: [] } });
});

describe("Mounted synthesis workspace scope", () => {
  it("binds the editor and resolved traces to the same current sample count", async () => {
    const { wrapper, panel, store } = mountPanel();
    await flushPromises();
    const points = [{ x: 0, y: .1 }, { x: 50, y: .5 }, { x: 100, y: .9 }];
    store.selectedComponents = [{ id: "acetone", name: "Acetone", source: "nist_quant_ir", variants: [],
      spectrum: null, loading: false, native_grid: null, concentration_max_ppm: 100, control_points: points }];
    for (const count of [50, 3, 100]) {
      store.settings.n_samples = count;
      await flushPromises();
      expect(wrapper.findComponent(ConcentrationCurveEditor).props("sampleCount")).toBe(count);
      expect(panel.concentrationTraces[0].x).toEqual(Array.from({ length: count }, (_, i) => i));
      expect(panel.concentrationTraces[0].y).toHaveLength(count);
      expect(store.selectedComponents[0].control_points).toEqual(points);
    }
    wrapper.unmount();
  });
  it("notifies only when grid edits clear an actual selection, not catalogue hits", async () => {
    const { wrapper, panel, store } = mountPanel();
    await flushPromises();
    store.searchResults = [{ id: "water", name: "Water", source: "nist_quant_ir", variants: [] }];
    mocks.toast.mockClear();
    panel.onSourceOrGridChange();
    panel.onSourceOrGridChange();
    expect(mocks.toast).not.toHaveBeenCalled();
    store.selectedComponents = [{ id: "water", name: "Water", source: "nist_quant_ir", variants: [],
      spectrum: null, loading: false, native_grid: null, concentration_max_ppm: 10, control_points: [] }];
    panel.onSourceOrGridChange();
    panel.onSourceOrGridChange();
    expect(mocks.toast).toHaveBeenCalledTimes(1);
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({ summary: "Selection cleared" }));
    wrapper.unmount();
  });
  it.each([400, 422])("reports definitive HTTP %s refusal with its remedy", async status => {
    const { wrapper, panel } = mountPanel();
    await flushPromises();
    panel.synthesisBundle = [{ id: "a", name: "first", payload: { components: [] } }];
    vi.mocked(api.post).mockRejectedValueOnce({ isAxiosError: true,
      response: { status, data: { detail: "Select an admitted source." } } });
    await panel.saveSynthesis();
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({
      severity: "error", summary: "Save refused",
      detail: "0 of 1 files saved. Select an admitted source.",
    }));
    expect(JSON.stringify(mocks.toast.mock.calls)).not.toContain("may also have saved");
    wrapper.unmount();
  });

  it("keeps lost acknowledgements explicitly uncertain", async () => {
    const { wrapper, panel } = mountPanel();
    await flushPromises();
    panel.synthesisBundle = [{ id: "a", name: "first", payload: { components: [] } }];
    vi.mocked(api.post).mockRejectedValueOnce(new Error("Network disconnected"));
    await panel.saveSynthesis();
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({
      severity: "warn", summary: "Save acknowledgement incomplete",
      detail: expect.stringContaining("may also have saved"),
    }));
    wrapper.unmount();
  });

  it("keeps pure-spectrum acquisition through concentration and unrelated component edits", async () => {
    const { wrapper, panel, store } = mountPanel();
    await flushPromises();
    store.selectedComponents = [{
      id: "water", name: "Water", source: "nist_quant_ir", variants: [],
      spectrum: null, loading: false, native_grid: null, concentration_max_ppm: 10,
      control_points: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
    }];
    const component = store.selectedComponents[0];
    const held = deferred<{ data: unknown }>();
    vi.mocked(api.get).mockReturnValueOnce(held.promise);
    const pending = panel.loadSpectrum(component);
    component.concentration_max_ppm = 25;
    component.control_points[0].y = .5;
    store.selectedComponents.push({ ...component, id: "ethanol", name: "Ethanol", loading: false });
    expect(component.loading).toBe(true);
    const spectrum = { component_id: "water", name: "Water", source: "nist_quant_ir",
      wavenumber: [1000, 1001, 1002], intensity: [1, 2, 1], y_quantity: "absorbance", y_units: "AU" };
    held.resolve({ data: spectrum });
    await pending;
    expect(component.spectrum).toEqual(spectrum);
    expect(component.loading).toBe(false);
    expect(component.concentration_max_ppm).toBe(25);
    wrapper.unmount();
  });

  it.each(["remove", "grid", "project"])("rejects a spectrum for changed acquisition identity: %s", async change => {
    const { wrapper, panel, store } = mountPanel();
    await flushPromises();
    store.selectedComponents = [{
      id: "water", name: "Water", source: "nist_quant_ir", variants: [],
      spectrum: null, loading: false, native_grid: null, concentration_max_ppm: 10, control_points: [],
    }];
    const component = store.selectedComponents[0];
    const held = deferred<{ data: unknown }>();
    vi.mocked(api.get).mockReturnValueOnce(held.promise);
    const pending = panel.loadSpectrum(component);
    if (change === "remove") store.selectedComponents = [];
    if (change === "grid") store.settings.resolution_cm1 = 8;
    if (change === "project") mocks.project.currentProjectId = 2;
    held.resolve({ data: { wavenumber: [1000], intensity: [1] } });
    await pending;
    expect(component.spectrum).toBeNull();
    expect(component.loading).toBe(false);
    wrapper.unmount();
  });

  it("keeps the new project's bundle when an accepted old save finishes", async () => {
    const { wrapper, panel, store } = mountPanel();
    await flushPromises();
    const held = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(held.promise);
    panel.synthesisBundle = [
      { id: "a", name: "first", payload: { components: [] } },
      { id: "b", name: "second", payload: { components: [] } },
    ];
    store.datasetName = "Old bundle";
    const saving = panel.saveSynthesis();
    mocks.project.currentProjectId = 2;
    await flushPromises();
    panel.synthesisBundle = [{ id: "new", name: "New draft", payload: { components: [] } }];
    store.datasetName = "New draft";
    mocks.toast.mockClear();
    held.resolve({ data: { experiment_id: 10, result: { seed: 2 } } });
    await saving;
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith("/synthesis/save",
      expect.objectContaining({ project_id: 1, name: "Old bundle" }),
      { signal: expect.any(AbortSignal) });
    expect(panel.synthesisBundle.map(item => item.id)).toEqual(["new"]);
    expect(store.datasetName).toBe("New draft");
    expect(store.previewResult).toBeNull();
    expect(wrapper.emitted("saved")).toBeUndefined();
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({
      severity: "warn", summary: "Bundle partly saved",
      detail: expect.stringContaining("1 of 2 files confirmed saved in project 1"),
    }));
    expect(mocks.project.fetchProjects).toHaveBeenCalledOnce();
    expect(mocks.data.fetchCatalog).toHaveBeenCalledOnce();
    wrapper.unmount();
  });

  it("keeps a save pending through draft edits and component replacement", async () => {
    const { wrapper, panel, store } = mountPanel();
    await flushPromises();
    const held = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(held.promise);
    store.datasetName = "Saved snapshot";
    panel.synthesisBundle = [{ id: "a", name: "first", payload: { components: [] } }];
    const pending = panel.saveSynthesis();
    store.datasetName = "New draft";
    store.settings.n_samples = 7;
    expect(store.saving).toBe(true);
    await panel.saveSynthesis();
    expect(api.post).toHaveBeenCalledTimes(1);
    wrapper.unmount();
    expect(store.saving).toBe(true);
    held.resolve({ data: { experiment_id: 10, result: { seed: 2 } } });
    await pending;
    expect(store.saving).toBe(false);
    expect(store.datasetName).toBe("New draft");
    expect(store.previewResult).toBeNull();
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
    expect(mocks.data.fetchCatalog).toHaveBeenCalledOnce();
  });

  it("recipe reopening invalidates an outstanding preview, including a late error", async () => {
    const { wrapper, panel, store } = mountPanel();
    await flushPromises();
    const held = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(held.promise);
    const preview = panel.previewSynthesis();
    await panel.reopenRecipe({
      settings: { source: "nist_quant_ir", n_samples: 5 },
      components: [{ component_id: "water", name: "Water" }],
    }, "Reopened");
    mocks.toast.mockClear();
    held.reject(new Error("retired preview failed"));
    await preview;
    expect(store.datasetName).toBe("Reopened copy");
    expect(store.previewResult).toBeNull();
    expect(mocks.toast).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("the first recipe's source response cannot resume search or announce completion after reopening another", async () => {
    const { wrapper, panel, store } = mountPanel();
    await flushPromises();
    const held = deferred<{ data: unknown }>();
    vi.mocked(api.get).mockReturnValueOnce(held.promise);
    const first = panel.reopenRecipe({
      settings: { source: "nist_quant_ir" }, components: [{ component_id: "ethanol" }],
    }, "First");
    await panel.reopenRecipe({
      settings: { source: "nist_quant_ir" }, components: [{ component_id: "water" }],
    }, "Second");
    const calls = vi.mocked(api.get).mock.calls.length;
    const notices = mocks.toast.mock.calls.length;
    held.resolve({ data: { sources: [{ id: "hitran", label: "Old source" }] } });
    await first;
    expect(vi.mocked(api.get).mock.calls).toHaveLength(calls);
    expect(mocks.toast.mock.calls).toHaveLength(notices);
    expect(store.datasetName).toBe("Second copy");
    expect(store.settings.source).toBe("nist_quant_ir");
    expect(store.selectedComponents[0].id).toBe("water");
    wrapper.unmount();
  });
});
