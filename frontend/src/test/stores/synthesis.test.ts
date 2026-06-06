import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import { useSynthesisStore } from "@/stores/synthesis";

function setScope(userId: number, projectId: number) {
  const authStore = useAuthStore();
  authStore.user = { id: userId, username: `user-${userId}` };
  const projectStore = useProjectStore();
  projectStore.currentProjectId = projectId;
}

describe("synthesis store state retention", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it("persists selected components, spectra, settings, and preview by user/project", () => {
    setScope(7, 101);
    const store = useSynthesisStore();

    store.sources = [{ id: "nist_quant_ir", label: "NIST Quantitative IR" }];
    store.settings.n_samples = 33;
    store.searchQuery = "co2";
    store.selectedComponents = [
      {
        id: "nist_quant_ir:co2",
        name: "Carbon dioxide",
        source: "nist_quant_ir",
        cas: "124-38-9",
        formula: "CO2",
        variants: [{ apodization: "Blackman-Harris", resolution_cm1: 1 }],
        spectrum: {
          component_id: "nist_quant_ir:co2",
          name: "Carbon dioxide",
          source: "nist_quant_ir",
          wavenumber: [400, 401],
          intensity: [0.1, 0.2],
          y_quantity: "decadic_absorption_coefficient",
          y_units: "ppm^-1 m^-1",
        },
        control_points: [
          { x: 0, y: 0 },
          { x: 100, y: 1 },
        ],
        concentration_max_ppm: 250,
        native_grid: { spacing: 1, min: 400, max: 401, n: 2 },
        loading: true,
      },
    ];
    store.previewResult = {
      source: "nist_quant_ir",
      wavenumber: [400, 401],
      absorbance: [[0.01, 0.02]],
      units: "absorbance",
      components: [{ id: "nist_quant_ir:co2", name: "Carbon dioxide", concentration_ppm: [10] }],
      recipe: { settings: { seed: 123 } },
      ground_truth: {},
      truncated: false,
    };
    store.flushPersist();

    setActivePinia(createPinia());
    setScope(7, 101);
    const restored = useSynthesisStore();

    expect(restored.settings.n_samples).toBe(33);
    expect(restored.sources).toEqual([{ id: "nist_quant_ir", label: "NIST Quantitative IR" }]);
    expect(restored.searchQuery).toBe("co2");
    expect(restored.selectedComponents).toHaveLength(1);
    expect(restored.selectedComponents[0].loading).toBe(false);
    expect(restored.selectedComponents[0].spectrum?.intensity).toEqual([0.1, 0.2]);
    expect(restored.previewResult?.absorbance).toEqual([[0.01, 0.02]]);
  });

  it("keeps synthesis state separate for different projects", () => {
    setScope(7, 101);
    const store = useSynthesisStore();
    store.searchQuery = "methanol";
    store.flushPersist();

    setActivePinia(createPinia());
    setScope(7, 202);
    const otherProjectStore = useSynthesisStore();

    expect(otherProjectStore.searchQuery).toBe("");
    expect(otherProjectStore.selectedComponents).toEqual([]);
  });

  it("trims oversized preview data before saving to browser storage", () => {
    setScope(7, 101);
    const store = useSynthesisStore();
    const largeAxis = Array.from({ length: 450_000 }, (_, index) => index);
    store.previewResult = {
      source: "nist_quant_ir",
      wavenumber: largeAxis,
      absorbance: [largeAxis.map((value) => value / 10_000)],
      units: "absorbance",
      components: [],
      recipe: {},
      ground_truth: {},
      truncated: false,
    };

    store.flushPersist();

    const raw = localStorage.getItem("spectra_sherpa_synthesis_state_v1:7:101");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string);
    expect(parsed.previewResult).toBeNull();
    expect(store.persistenceWarning).toContain("trimmed");
  });

  it("marks loaded spectra as refetchable when storage must trim spectra", () => {
    setScope(7, 101);
    const store = useSynthesisStore();
    const largeAxis = Array.from({ length: 450_000 }, (_, index) => index);
    store.selectedComponents = [
      {
        id: "nist_quant_ir:co2",
        name: "Carbon dioxide",
        source: "nist_quant_ir",
        variants: [{ apodization: "Blackman-Harris", resolution_cm1: 1 }],
        spectrum: {
          component_id: "nist_quant_ir:co2",
          name: "Carbon dioxide",
          source: "nist_quant_ir",
          wavenumber: largeAxis,
          intensity: largeAxis.map((value) => value / 100_000),
          y_quantity: "decadic_absorption_coefficient",
          y_units: "ppm^-1 m^-1",
        },
        control_points: [
          { x: 0, y: 0 },
          { x: 100, y: 1 },
        ],
        concentration_max_ppm: 250,
        native_grid: { spacing: 1, min: 0, max: 449_999, n: largeAxis.length },
        loading: false,
      },
    ];

    store.flushPersist();

    const raw = localStorage.getItem("spectra_sherpa_synthesis_state_v1:7:101");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string);
    expect(parsed.selectedComponents[0].spectrum).toBeNull();
    expect(parsed.selectedComponents[0].spectrum_storage_trimmed).toBe(true);

    setActivePinia(createPinia());
    setScope(7, 101);
    const restored = useSynthesisStore();
    expect(restored.selectedComponents[0].spectrum).toBeNull();
    expect(restored.selectedComponents[0].spectrum_storage_trimmed).toBe(true);
  });
});
