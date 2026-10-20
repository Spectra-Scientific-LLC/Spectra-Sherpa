<template>
  <div class="synthesis-grid synthesis-grid--source">
    <div class="field">
      <label for="synth-source">Database</label>
      <Dropdown
        inputId="synth-source"
        :modelValue="settings.source"
        @update:modelValue="edit('source', $event)"
        :options="sourceOptions"
        optionLabel="label"
        optionValue="id"
        @change="$emit('source-change')"
      />
    </div>
    <div class="field">
      <label for="synth-resolution">Resolution</label>
      <Dropdown
        inputId="synth-resolution"
        :modelValue="settings.resolution_cm1"
        @update:modelValue="edit('resolution_cm1', $event)"
        :options="resolutionOptions"
        optionLabel="label"
        optionValue="value"
        @change="$emit('grid-change')"
      />
    </div>
    <div class="field" v-if="settings.source === 'nist_quant_ir'">
      <label for="synth-apodization">Apodization</label>
      <Dropdown
        inputId="synth-apodization"
        :modelValue="settings.apodization"
        @update:modelValue="edit('apodization', $event)"
        :options="apodizationOptions"
        optionLabel="label"
        optionValue="value"
        @change="$emit('grid-change')"
      />
    </div>
    <div class="field" v-if="settings.source === 'hitran'">
      <label for="synth-wmin">Min cm^-1</label>
      <InputNumber
        inputId="synth-wmin"
        :modelValue="settings.wavenumber_min"
        @update:modelValue="edit('wavenumber_min', $event)"
        :min="1"
        :useGrouping="false"
        @input="$emit('grid-change')"
      />
    </div>
    <div class="field" v-if="settings.source === 'hitran'">
      <label for="synth-wmax">Max cm^-1</label>
      <InputNumber
        inputId="synth-wmax"
        :modelValue="settings.wavenumber_max"
        @update:modelValue="edit('wavenumber_max', $event)"
        :min="2"
        :useGrouping="false"
        @input="$emit('grid-change')"
      />
    </div>
    <div class="field" v-if="settings.source === 'hitran'">
      <label for="synth-temperature">Temperature (K)</label>
      <InputNumber
        inputId="synth-temperature"
        :modelValue="settings.temperature_k"
        @update:modelValue="edit('temperature_k', $event)"
        :min="50"
        :max="5000"
        :maxFractionDigits="2"
        :useGrouping="false"
        @input="$emit('grid-change')"
      />
    </div>
    <div class="field" v-if="settings.source === 'hitran'">
      <label for="synth-pressure">Pressure (atm)</label>
      <InputNumber
        inputId="synth-pressure"
        :modelValue="settings.pressure_atm"
        @update:modelValue="edit('pressure_atm', $event)"
        :min="0.000001"
        :maxFractionDigits="6"
        :useGrouping="false"
        @input="$emit('grid-change')"
      />
    </div>
  </div>
  <div class="synthesis-grid synthesis-grid--generation">
    <div class="field">
      <label for="synth-samples">Samples</label>
      <InputNumber
        inputId="synth-samples"
        :modelValue="settings.n_samples"
        @update:modelValue="edit('n_samples', $event)"
        :min="2"
        :max="1000"
        :useGrouping="false"
        @input="$emit('preview-change')"
      />
    </div>
    <div class="field">
      <label for="synth-pathlength">Path length (cm)</label>
      <InputNumber
        inputId="synth-pathlength"
        :modelValue="settings.pathlength_cm"
        @update:modelValue="edit('pathlength_cm', $event)"
        :min="0.001"
        :maxFractionDigits="4"
        :useGrouping="false"
        @input="$emit('preview-change')"
      />
    </div>
    <div class="field">
      <label for="synth-noise">Noise sigma (AU)</label>
      <InputNumber
        inputId="synth-noise"
        :modelValue="settings.noise_sigma_au"
        @update:modelValue="edit('noise_sigma_au', $event)"
        :min="0"
        :maxFractionDigits="6"
        :useGrouping="false"
        @input="$emit('preview-change')"
      />
    </div>
    <div v-if="!isHitranLineByLine" class="field field--wide">
      <label for="synth-snaptol">Wavenumber snap tolerance (cm⁻¹)</label>
      <InputNumber
        inputId="synth-snaptol"
        :modelValue="settings.snap_tolerance_cm1"
        @update:modelValue="edit('snap_tolerance_cm1', $event)"
        :min="0"
        :max="5"
        :maxFractionDigits="4"
        :useGrouping="false"
        @input="$emit('preview-change')"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import type { SynthesisSettings } from "@/stores/synthesis";

// Emits edits to the parent's draft only. Acquisition, preview cancellation and
// persistence remain in their existing owners; this section performs no I/O.
const props = defineProps<{
  settings: SynthesisSettings;
  sourceOptions: Array<{ id: string; label: string }>;
}>();
const emit = defineEmits<{
  "update:settings": [settings: SynthesisSettings];
  "source-change": [];
  "grid-change": [];
  "preview-change": [];
}>();
function edit<K extends keyof SynthesisSettings>(key: K, value: SynthesisSettings[K]): void {
  emit("update:settings", { ...props.settings, [key]: value });
}
const isHitranLineByLine = computed(() => props.settings.source === "hitran");
const resolutionOptions = [
  { label: "1 cm^-1", value: 1 },
  { label: "2 cm^-1", value: 2 },
  { label: "0.5 cm^-1", value: 0.5 },
  { label: "0.25 cm^-1", value: 0.25 },
  { label: "0.125 cm^-1", value: 0.125 },
];
const apodizationOptions = [
  { label: "Blackman-Harris", value: "Blackman-Harris" },
  { label: "Triangular", value: "Triangular" },
];
</script>

<style scoped>
.synthesis-grid { display: grid; gap: 0.75rem; }
.synthesis-grid--source {
  grid-template-columns: minmax(180px, 1.4fr) minmax(115px, 0.8fr) repeat(4, minmax(120px, 0.85fr));
}
.synthesis-grid--generation {
  grid-template-columns: minmax(110px, 0.75fr) minmax(150px, 1fr) minmax(150px, 1fr) minmax(245px, 1.35fr);
  margin-top: 0.75rem;
}
.field { display: flex; flex-direction: column; gap: 0.35rem; min-width: 0; }
.field label { color: var(--text-color-secondary); font-size: 0.78rem; font-weight: 600; text-transform: uppercase; white-space: nowrap; }
.field :deep(.p-dropdown), .field :deep(.p-inputnumber) { width: 100%; }
@media (max-width: 720px) {
  .synthesis-grid { grid-template-columns: 1fr; }
  .field label { white-space: normal; }
}
@media (min-width: 721px) and (max-width: 980px) {
  .synthesis-grid { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
}
</style>
