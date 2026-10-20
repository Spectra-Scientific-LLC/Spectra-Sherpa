import { shallowMount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import SynthesisSettingsSection from "@/views/data/sections/SynthesisSettingsSection.vue";
import type { SynthesisSettings, SynthesisSource } from "@/stores/synthesis";
import InputNumber from "primevue/inputnumber";
import Dropdown from "primevue/dropdown";

function draft(source: SynthesisSource): SynthesisSettings {
  return {
    source, range_mode: "common", resolution_cm1: 1, apodization: "Blackman-Harris",
    n_samples: 24, pathlength_cm: 1, noise_sigma_au: 0, snap_tolerance_cm1: 0.1,
    wavenumber_min: 500, wavenumber_max: 4000, preview_wavenumber_min: null,
    preview_wavenumber_max: null, preview_wavenumber_interval_cm1: null,
    temperature_k: 296, pressure_atm: 1,
  };
}

describe("Synthesis settings section", () => {
  it.each(["nist_quant_ir", "hitran", "hitran_xsec"] as const)(
    "retains source-specific controls for %s", (source) => {
      const wrapper = shallowMount(SynthesisSettingsSection, {
        props: { settings: draft(source), sourceOptions: [{ id: source, label: source }] },
      });
      const ids = wrapper.findAll("label").map(label => label.attributes("for"));
      expect(ids).toEqual(expect.arrayContaining([
        "synth-source", "synth-resolution", "synth-samples", "synth-pathlength", "synth-noise",
      ]));
      expect(ids.includes("synth-apodization")).toBe(source === "nist_quant_ir");
      expect(ids.includes("synth-snaptol")).toBe(source !== "hitran");
      for (const id of ["synth-wmin", "synth-wmax", "synth-temperature", "synth-pressure"]) {
        expect(ids.includes(id)).toBe(source === "hitran");
      }
    },
  );

  it("emits draft edits without mutating its input or taking ownership of saving", () => {
    const settings = draft("hitran");
    const wrapper = shallowMount(SynthesisSettingsSection, {
      props: { settings, sourceOptions: [{ id: "hitran", label: "HITRAN" }] },
    });
    const samples = wrapper.findAllComponents(InputNumber)
      .find(control => control.attributes("inputid") === "synth-samples")!;
    samples.vm.$emit("update:modelValue", 99);
    samples.vm.$emit("input", { value: 99 });
    expect(wrapper.emitted("update:settings")?.[0]).toEqual([{ ...settings, n_samples: 99 }]);
    expect(wrapper.emitted("preview-change")).toHaveLength(1);
    expect(settings.n_samples).toBe(24);
    expect(samples.attributes("min")).toBe("2");
    expect(samples.attributes("max")).toBe("1000");
    const resolution = wrapper.findAllComponents(Dropdown)
      .find(control => control.attributes("inputid") === "synth-resolution")!;
    resolution.vm.$emit("change", { value: 2 });
    expect(wrapper.emitted("grid-change")).toHaveLength(1);
  });
});
