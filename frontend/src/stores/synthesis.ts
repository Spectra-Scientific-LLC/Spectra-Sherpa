import { defineStore } from "pinia";
import { computed, reactive, ref, watch } from "vue";

import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";

const STORAGE_PREFIX = "spectra_sherpa_synthesis_state_v1";
const STORAGE_SOFT_LIMIT_CHARS = 3_800_000;
const STORAGE_EVENT_BOUND = "spectra_sherpa_synthesis_storage_bound";

export type SynthesisSource = "nist_quant_ir" | "hitran" | "hitran_xsec";
export type SynthesisRangeMode = "common" | "widest";

export interface SourceInfo {
  id: SynthesisSource;
  label: string;
  available?: boolean;
  requires_key?: boolean;
  default_resolution_cm1?: number;
  default_apodization?: string;
}

export interface Variant {
  resolution_cm1: number;
  apodization: string;
}

export interface HitranXsecOption {
  temperature_k?: [number, number] | null;
  pressure_torr?: [number, number] | null;
  wavenumber_cm1?: [number, number] | null;
  sets?: number | null;
  resolution_cm1?: number | null;
  npts?: number | null;
  broadener?: string | null;
}

export interface ComponentSummary {
  id: string;
  name: string;
  source: SynthesisSource;
  cas?: string | null;
  formula?: string | null;
  variants: Variant[];
  xsec_options?: HitranXsecOption[];
}

export interface SpectrumPayload {
  component_id: string;
  name: string;
  source: SynthesisSource;
  wavenumber: number[];
  intensity: number[];
  y_quantity: string;
  y_units: string;
  resolution_cm1?: number | null;
  apodization?: string | null;
  cached?: boolean;
}

export interface ControlPoint {
  x: number;
  y: number;
}

export interface NativeGrid {
  spacing: number;
  min: number;
  max: number;
  n: number;
}

export interface SelectedComponent extends ComponentSummary {
  spectrum: SpectrumPayload | null;
  control_points: ControlPoint[];
  concentration_max_ppm: number;
  native_grid: NativeGrid | null;
  loading: boolean;
  load_progress?: number | null;
  load_message?: string | null;
  spectrum_storage_trimmed?: boolean;
  selected_xsec_option?: number;
}

export interface SynthesisResult {
  source: SynthesisSource;
  wavenumber: number[];
  absorbance: number[][];
  units: string;
  components: Array<{ id: string; name: string; concentration_ppm: number[] }>;
  recipe: Record<string, unknown>;
  ground_truth: Record<string, unknown>;
  truncated: boolean;
}

export interface SynthesisSettings {
  source: SynthesisSource;
  range_mode: SynthesisRangeMode;
  resolution_cm1: number;
  apodization: string;
  n_samples: number;
  pathlength_cm: number;
  noise_sigma_au: number;
  snap_tolerance_cm1: number;
  wavenumber_min: number;
  wavenumber_max: number;
  preview_wavenumber_min: number | null;
  preview_wavenumber_max: number | null;
  preview_wavenumber_interval_cm1: number | null;
  temperature_k: number;
  pressure_atm: number;
}

interface SynthesisSnapshot {
  version: 1;
  saved_at: string;
  sources: SourceInfo[];
  settings: SynthesisSettings;
  searchQuery: string;
  searchResults: ComponentSummary[];
  selectedComponents: SelectedComponent[];
  previewResult: SynthesisResult | null;
  showTransmittance: boolean;
  previewStartSample: number;
  previewSkip: number;
  crosshair: { x: number; y: number } | null;
  sliceSelection: { sampleIndex: number; wavenumberIndex: number } | null;
  datasetName: string;
  recipeSeed: number | null;
  logConcentration: boolean;
  normalizeComposition: boolean;
}

export function defaultDatasetName(): string {
  const timestamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
  return `synthetic-ftir-${timestamp}`;
}

function defaultSettings(): SynthesisSettings {
  return {
    source: "nist_quant_ir",
    range_mode: "common",
    resolution_cm1: 1,
    apodization: "Blackman-Harris",
    n_samples: 50,
    pathlength_cm: 10,
    noise_sigma_au: 0.001,
    snap_tolerance_cm1: 0.05,
    wavenumber_min: 400,
    wavenumber_max: 4000,
    preview_wavenumber_min: null,
    preview_wavenumber_max: null,
    preview_wavenumber_interval_cm1: null,
    temperature_k: 293,
    pressure_atm: 1,
  };
}

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function asSelectedComponent(value: SelectedComponent): SelectedComponent {
  return {
    ...value,
    variants: Array.isArray(value.variants) ? value.variants : [],
    xsec_options: Array.isArray(value.xsec_options) ? value.xsec_options : [],
    control_points: Array.isArray(value.control_points) ? value.control_points : [],
    concentration_max_ppm: Number(value.concentration_max_ppm) || 0,
    spectrum: value.spectrum ?? null,
    native_grid: value.native_grid ?? null,
    loading: false,
    load_progress: null,
    load_message: null,
    spectrum_storage_trimmed: Boolean(value.spectrum_storage_trimmed),
  };
}

export const useSynthesisStore = defineStore("synthesis", () => {
  const authStore = useAuthStore();
  const projectStore = useProjectStore();

  const sources = ref<SourceInfo[]>([]);
  const searchQuery = ref("");
  const searchResults = ref<ComponentSummary[]>([]);
  const selectedComponents = ref<SelectedComponent[]>([]);
  const previewResult = ref<SynthesisResult | null>(null);
  const searching = ref(false);
  const previewing = ref(false);
  const saving = ref(false);
  const showTransmittance = ref(false);
  const previewStartSample = ref(0);
  const previewSkip = ref(1);
  const crosshair = ref<{ x: number; y: number } | null>(null);
  const sliceSelection = ref<{ sampleIndex: number; wavenumberIndex: number } | null>(null);
  const datasetName = ref(defaultDatasetName());
  const recipeSeed = ref<number | null>(null);
  const logConcentration = ref(false);
  const normalizeComposition = ref(false);
  const persistenceWarning = ref<string | null>(null);
  const settings = reactive<SynthesisSettings>(defaultSettings());

  const storageKey = computed(
    () =>
      `${STORAGE_PREFIX}:${authStore.user?.id ?? "local"}:${
        projectStore.currentProjectId ?? "no-project"
      }`,
  );

  let hydrating = false;
  let persistTimer: ReturnType<typeof setTimeout> | null = null;

  function snapshot(options: { spectra: boolean; preview: boolean; search: boolean }): SynthesisSnapshot {
    return {
      version: 1,
      saved_at: new Date().toISOString(),
      sources: cloneJson(sources.value),
      settings: cloneJson(settings),
      searchQuery: searchQuery.value,
      // Search results are a transient catalog view, not builder state.
      // Persisting large HITRAN/X-section result sets can churn browser
      // storage and cause the table to disappear after hydration. Keep the
      // query and refetch results on demand.
      searchResults: [],
      selectedComponents: selectedComponents.value.map((component) => {
        const { spectrum, ...componentMeta } = component;
        return {
          ...cloneJson(componentMeta),
          loading: false,
          load_progress: null,
          load_message: null,
          spectrum: options.spectra ? cloneJson(spectrum) : null,
          spectrum_storage_trimmed: !options.spectra && spectrum !== null,
        };
      }),
      previewResult: options.preview ? cloneJson(previewResult.value) : null,
      showTransmittance: showTransmittance.value,
      previewStartSample: previewStartSample.value,
      previewSkip: previewSkip.value,
      crosshair: cloneJson(crosshair.value),
      sliceSelection: cloneJson(sliceSelection.value),
      datasetName: datasetName.value,
      recipeSeed: recipeSeed.value,
      logConcentration: logConcentration.value,
      normalizeComposition: normalizeComposition.value,
    };
  }

  function resetState(): void {
    Object.assign(settings, defaultSettings());
    sources.value = [];
    searchQuery.value = "";
    searchResults.value = [];
    selectedComponents.value = [];
    previewResult.value = null;
    showTransmittance.value = false;
    previewStartSample.value = 0;
    previewSkip.value = 1;
    crosshair.value = null;
    sliceSelection.value = null;
    datasetName.value = defaultDatasetName();
    recipeSeed.value = null;
    logConcentration.value = false;
    normalizeComposition.value = false;
    persistenceWarning.value = null;
  }

  function applySnapshot(parsed: Partial<SynthesisSnapshot>): void {
    resetState();
    sources.value = Array.isArray(parsed.sources) ? cloneJson(parsed.sources) : [];
    Object.assign(settings, { ...defaultSettings(), ...(parsed.settings ?? {}) });
    searchQuery.value = typeof parsed.searchQuery === "string" ? parsed.searchQuery : "";
    searchResults.value = Array.isArray(parsed.searchResults)
      ? cloneJson(parsed.searchResults)
      : [];
    selectedComponents.value = Array.isArray(parsed.selectedComponents)
      ? cloneJson(parsed.selectedComponents).map(asSelectedComponent)
      : [];
    previewResult.value = parsed.previewResult ? cloneJson(parsed.previewResult) : null;
    showTransmittance.value = Boolean(parsed.showTransmittance);
    previewStartSample.value = Number(parsed.previewStartSample) || 0;
    previewSkip.value = Math.max(1, Number(parsed.previewSkip) || 1);
    crosshair.value = parsed.crosshair ?? null;
    sliceSelection.value = parsed.sliceSelection ?? null;
    datasetName.value =
      typeof parsed.datasetName === "string" && parsed.datasetName.trim()
        ? parsed.datasetName
        : defaultDatasetName();
    recipeSeed.value = Number.isFinite(Number(parsed.recipeSeed))
      ? Number(parsed.recipeSeed)
      : null;
    logConcentration.value = Boolean(parsed.logConcentration);
    normalizeComposition.value = Boolean(parsed.normalizeComposition);
  }

  function hydrate(key = storageKey.value): void {
    hydrating = true;
    try {
      const raw = localStorage.getItem(key);
      if (!raw) {
        resetState();
        return;
      }
      const parsed = JSON.parse(raw) as Partial<SynthesisSnapshot>;
      if (parsed.version !== 1) {
        resetState();
        return;
      }
      applySnapshot(parsed);
    } catch {
      resetState();
    } finally {
      hydrating = false;
    }
  }

  function persistNow(key = storageKey.value): void {
    if (hydrating) return;

    const variants = [
      { spectra: true, preview: true, search: true },
      { spectra: true, preview: false, search: true },
      { spectra: true, preview: false, search: false },
      { spectra: false, preview: false, search: false },
    ];

    for (const [index, variant] of variants.entries()) {
      const serialized = JSON.stringify(snapshot(variant));
      if (serialized.length > STORAGE_SOFT_LIMIT_CHARS && index < variants.length - 1) {
        continue;
      }
      try {
        localStorage.setItem(key, serialized);
        persistenceWarning.value =
          index === 0
            ? null
            : "The synthesis recipe was retained, but large preview/search data was trimmed for browser storage.";
        return;
      } catch {
        if (index < variants.length - 1) {
          continue;
        }
      }
    }
    persistenceWarning.value =
      "Browser storage rejected the synthesis state. The current tab will retain it until refresh.";
  }

  function schedulePersist(key = storageKey.value): void {
    if (hydrating) return;
    if (persistTimer) {
      clearTimeout(persistTimer);
    }
    persistTimer = setTimeout(() => {
      persistTimer = null;
      persistNow(key);
    }, 120);
  }

  function flushPersist(): void {
    if (persistTimer) {
      clearTimeout(persistTimer);
      persistTimer = null;
    }
    persistNow();
  }

  function invalidatePreview(): void {
    // Guard against hydration paths (applySnapshot/resetState) firing
    // downstream watchers that clear the just-restored preview. Without
    // this, a settings.n_samples mutation during applySnapshot triggers
    // the panel's n_samples watcher AFTER hydrate finishes, clobbering
    // the freshly restored previewResult on the next flush.
    if (hydrating) return;
    previewResult.value = null;
    crosshair.value = null;
    sliceSelection.value = null;
  }

  function clearForSourceOrGridChange(): void {
    if (hydrating) return;
    selectedComponents.value = [];
    previewResult.value = null;
    recipeSeed.value = null;
    searchResults.value = [];
    crosshair.value = null;
    sliceSelection.value = null;
  }

  watch(
    storageKey,
    (next, previous) => {
      if (previous) {
        persistNow(previous);
      }
      hydrate(next);
    },
    { immediate: true },
  );

  watch(
    [
      settings,
      sources,
      searchQuery,
      searchResults,
      selectedComponents,
      previewResult,
      showTransmittance,
      previewStartSample,
      previewSkip,
      crosshair,
      sliceSelection,
      datasetName,
      recipeSeed,
      logConcentration,
      normalizeComposition,
    ],
    () => schedulePersist(),
    { deep: true },
  );

  if (typeof window !== "undefined" && !(window as unknown as Record<string, boolean>)[STORAGE_EVENT_BOUND]) {
    (window as unknown as Record<string, boolean>)[STORAGE_EVENT_BOUND] = true;
    window.addEventListener("storage", (event) => {
      if (event.key === storageKey.value) {
        hydrate(event.key);
      }
    });
  }

  return {
    sources,
    searchQuery,
    searchResults,
    selectedComponents,
    previewResult,
    searching,
    previewing,
    saving,
    showTransmittance,
    previewStartSample,
    previewSkip,
    crosshair,
    sliceSelection,
    datasetName,
    recipeSeed,
    logConcentration,
    normalizeComposition,
    persistenceWarning,
    settings,
    flushPersist,
    hydrate,
    invalidatePreview,
    clearForSourceOrGridChange,
  };
});
