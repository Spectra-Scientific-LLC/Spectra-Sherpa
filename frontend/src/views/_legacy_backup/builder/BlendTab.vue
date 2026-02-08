<template>
  <div class="blend-tab">
    <div v-if="builderStore.spectra.length === 0" class="empty-state">
      <i class="pi pi-flask" style="font-size: 3rem; color: #94a3b8"></i>
      <h3>No Preprocessed Spectra</h3>
      <p>Preprocess spectra in the "Preprocess" tab before blending.</p>
    </div>

    <div v-else class="blend-content">
      <!-- Left Column: Species Selection & Concentration Controls -->
      <div class="left-column">
        <div class="tab-section">
          <h3>Species Selection</h3>
          <p class="muted-text">Select species to blend and set concentrations</p>

          <div class="species-list">
            <div
              v-for="spectrum in builderStore.spectra"
              :key="spectrum.label"
              class="species-item"
            >
              <div class="species-header">
                <Checkbox
                  v-model="selectedSpecies"
                  :value="spectrum.label"
                  :inputId="`species-${spectrum.label}`"
                />
                <label :for="`species-${spectrum.label}`" class="species-label">
                  {{ spectrum.label }}
                </label>
              </div>

              <div v-if="selectedSpecies.includes(spectrum.label)" class="concentration-control">
                <label>Concentration</label>
                <div class="slider-input-group">
                  <Slider
                    v-model="concentrations[spectrum.label]"
                    :min="0"
                    :max="10000"
                    :step="10"
                    class="concentration-slider"
                  />
                  <InputNumber
                    v-model="concentrations[spectrum.label]"
                    :min="0"
                    :step="10"
                    showButtons
                    class="concentration-input"
                  />
                </div>
                <small class="muted-text">{{ concentrationUnit }}</small>
              </div>
            </div>
          </div>
        </div>

        <div class="tab-section">
          <h3>Blend Settings</h3>

          <div class="field">
            <label>Concentration Mode</label>
            <Dropdown
              v-model="concentrationMode"
              :options="concentrationModeOptions"
              optionLabel="label"
              optionValue="value"
              placeholder="Select mode"
            />
            <small class="muted-text">
              {{ concentrationModeHelp }}
            </small>
          </div>

          <div class="field">
            <label>Pathlength (m)</label>
            <InputNumber
              v-model="pathlength"
              :min="0"
              :step="0.001"
              :minFractionDigits="3"
              placeholder="Optional"
            />
            <small class="muted-text">
              For converting ppm to ppm·m (product mode)
            </small>
          </div>

          <div class="field">
            <div class="checkbox-field">
              <InputSwitch v-model="clipNegative" />
              <label>Clip Negative Values</label>
            </div>
            <small class="muted-text">
              Remove negative absorbance from model intercepts
            </small>
          </div>

          <div class="field">
            <div class="checkbox-field">
              <InputSwitch v-model="systemSaturationEnabled" />
              <label>System Saturation</label>
            </div>
            <small class="muted-text">
              Apply detector saturation after blending
            </small>
          </div>

          <div v-if="systemSaturationEnabled" class="form-grid two">
            <div class="field">
              <label>S_system (plateau)</label>
              <InputNumber
                v-model="sSystem"
                :min="0"
                :step="0.1"
                :minFractionDigits="2"
              />
            </div>
            <div class="field">
              <label>P_system (shape)</label>
              <InputNumber
                v-model="pSystem"
                :min="0"
                :step="0.1"
                :minFractionDigits="2"
              />
            </div>
          </div>

          <Button
            label="Blend Species"
            icon="pi pi-flask"
            class="blend-button"
            :loading="blending"
            :disabled="selectedSpecies.length === 0"
            @click="blendSpecies"
          />
        </div>
      </div>

      <!-- Right Column: Metadata & Preview Plot -->
      <div class="right-column">
        <div class="tab-section">
          <h3>Metadata</h3>
          <p class="muted-text">Optional metadata for NDDataset export</p>

          <div class="field">
            <label>X-axis Label</label>
            <InputText
              v-model="xLabel"
              placeholder="e.g., Time, Sample Number"
            />
          </div>

          <div class="field">
            <label>X-axis Unit</label>
            <InputText
              v-model="xUnit"
              placeholder="e.g., s, min, hr"
            />
          </div>

          <div class="field">
            <label>Description</label>
            <Textarea
              v-model="description"
              rows="3"
              placeholder="Optional description of this blend"
            />
          </div>
        </div>

        <div class="tab-section plot-section">
          <h3>Blended Spectrum Preview</h3>

          <div v-if="!blendResult" class="empty-plot">
            <i class="pi pi-chart-line" style="font-size: 2.5rem; color: #cbd5e1"></i>
            <p>Select species and click "Blend Species" to preview</p>
          </div>

          <div v-else>
            <PlotlyChart :data="plotData" :layout="plotLayout" />

            <div class="blend-stats">
              <div class="stat-item">
                <label>Min:</label>
                <span>{{ blendResult.statistics.min.toFixed(6) }}</span>
              </div>
              <div class="stat-item">
                <label>Max:</label>
                <span>{{ blendResult.statistics.max.toFixed(6) }}</span>
              </div>
              <div class="stat-item">
                <label>Mean:</label>
                <span>{{ blendResult.statistics.mean.toFixed(6) }}</span>
              </div>
              <div class="stat-item">
                <label>Std Dev:</label>
                <span>{{ blendResult.statistics.std.toFixed(6) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive } from "vue";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import InputSwitch from "primevue/inputswitch";
import InputText from "primevue/inputtext";
import Slider from "primevue/slider";
import Textarea from "primevue/textarea";
import { useToast } from "primevue/usetoast";
import { useBuilderStore } from "@/stores/builder";
import PlotlyChart from "@/components/PlotlyChart.vue";
import api from "@/api/client";

const builderStore = useBuilderStore();
const toast = useToast();

// Species selection and concentrations
const selectedSpecies = ref<string[]>([]);
const concentrations = reactive<Record<string, number>>({});

// Initialize concentrations for all spectra
builderStore.spectra.forEach((spectrum) => {
  if (!(spectrum.label in concentrations)) {
    concentrations[spectrum.label] = 100; // Default 100 ppm
  }
});

// Blend settings
const concentrationMode = ref("product"); // "concentration" (ppm) or "product" (ppm·m)
const pathlength = ref<number | null>(null);
const clipNegative = ref(false);
const systemSaturationEnabled = ref(false);
const sSystem = ref(1.0);
const pSystem = ref(1.0);

// Metadata
const xLabel = ref("Time");
const xUnit = ref("s");
const description = ref("");

// Blend results
const blending = ref(false);
const blendResult = ref<any>(null);

const concentrationModeOptions = [
  { label: "Concentration (ppm)", value: "concentration" },
  { label: "Product (ppm·m)", value: "product" },
];

const concentrationModeHelp = computed(() => {
  if (concentrationMode.value === "concentration") {
    return "Calibrated in ppm - provide concentration in ppm";
  } else {
    return "Calibrated in ppm·m - provide concentration in ppm and set pathlength, OR provide ppm·m directly";
  }
});

const concentrationUnit = computed(() => {
  if (concentrationMode.value === "concentration") {
    return "ppm";
  } else if (pathlength.value && pathlength.value > 0) {
    return "ppm (will be converted to ppm·m)";
  } else {
    return "ppm·m";
  }
});

const plotData = computed(() => {
  if (!blendResult.value) return [];

  // For single time point, show as scatter
  if (blendResult.value.times.length === 1) {
    return [
      {
        x: blendResult.value.wavenumbers,
        y: blendResult.value.absorbance_matrix.map((row: number[]) => row[0]),
        type: "scatter",
        mode: "lines",
        line: { color: "#3b82f6", width: 1.5 },
        hovertemplate: "Wavenumber: %{x:.1f} cm⁻¹<br>Absorbance: %{y:.6f}<extra></extra>",
      },
    ];
  }

  // For multiple time points, show heatmap
  return [
    {
      x: blendResult.value.times,
      y: blendResult.value.wavenumbers,
      z: blendResult.value.absorbance_matrix,
      type: "heatmap",
      colorscale: "Viridis",
      hovertemplate: "Time: %{x}<br>Wavenumber: %{y:.1f} cm⁻¹<br>Absorbance: %{z:.6f}<extra></extra>",
    },
  ];
});

const plotLayout = computed(() => {
  if (!blendResult.value) return {};

  if (blendResult.value.times.length === 1) {
    return {
      title: { text: "Blended Spectrum", font: { size: 14 } },
      xaxis: { title: "Wavenumber (cm⁻¹)", autorange: "reversed" },
      yaxis: { title: "Absorbance (a.u.)" },
      hovermode: "closest",
      template: "plotly_white",
      height: 500,
      margin: { t: 40, r: 20, l: 60, b: 50 },
    };
  } else {
    return {
      title: { text: "Blended Spectrum Time Series", font: { size: 14 } },
      xaxis: { title: xLabel.value + (xUnit.value ? ` (${xUnit.value})` : "") },
      yaxis: { title: "Wavenumber (cm⁻¹)" },
      template: "plotly_white",
      height: 500,
      margin: { t: 40, r: 20, l: 60, b: 50 },
    };
  }
});

const blendSpecies = async () => {
  if (selectedSpecies.value.length === 0) {
    toast.add({
      severity: "warn",
      summary: "No Species Selected",
      detail: "Select at least one species to blend",
      life: 3000,
    });
    return;
  }

  blending.value = true;

  try {
    // Build concentration timeseries (single time point for now)
    const concentrationTimeseries: Record<string, number[]> = {};
    selectedSpecies.value.forEach((label) => {
      concentrationTimeseries[label] = [concentrations[label]];
    });

    // Build species list from preprocessed spectra
    const speciesList = selectedSpecies.value.map((label) => {
      const spectrum = builderStore.spectra.find((s) => s.label === label);
      if (!spectrum) throw new Error(`Spectrum ${label} not found`);

      return {
        label: spectrum.label,
        filename: spectrum.label + ".csv",
        wavenumber: spectrum.wavenumber,
        absorbance: spectrum.absorbance,
        source: spectrum.source || "csv",
        model_type: spectrum.model_type || null,
        concentration_mode: concentrationMode.value,
        x_label: xLabel.value || null,
        x_unit: xUnit.value || null,
        pathlength_m: pathlength.value || null,
      };
    });

    // Build blend settings
    const settings = {
      system_saturation_enabled: systemSaturationEnabled.value,
      s_system: sSystem.value,
      p_system: pSystem.value,
      clip_negative: clipNegative.value,
    };

    // Call blend API
    const response = await api.post("/api/v1/builder/blend", {
      species: speciesList,
      concentration_timeseries: concentrationTimeseries,
      pathlength_m: pathlength.value || null,
      settings,
    });

    blendResult.value = response.data;

    // Store blend metadata
    builderStore.blendConcentrations = concentrationTimeseries;
    builderStore.blendSettings = settings;
    builderStore.blendMetadata = {
      x_label: xLabel.value,
      x_unit: xUnit.value,
      description: description.value,
    };

    toast.add({
      severity: "success",
      summary: "Blend Complete",
      detail: `Blended ${selectedSpecies.value.length} species`,
      life: 3000,
    });
  } catch (error: any) {
    console.error("Blend failed:", error);
    toast.add({
      severity: "error",
      summary: "Blend Failed",
      detail: error.response?.data?.detail || "Unable to blend species",
      life: 3000,
    });
  } finally {
    blending.value = false;
  }
};
</script>

<style scoped>
.blend-tab {
  display: flex;
  flex-direction: column;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
  color: #64748b;
}

.empty-state h3 {
  margin: 16px 0 8px;
  font-size: 1.2rem;
  color: #475569;
}

.blend-content {
  display: grid;
  grid-template-columns: 400px 1fr;
  gap: 20px;
}

.left-column,
.right-column {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.tab-section {
  background: #ffffff;
  border-radius: 8px;
  padding: 20px;
}

.plot-section {
  min-height: 600px;
}

.tab-section h3 {
  margin: 0 0 8px;
  font-size: 1rem;
  font-weight: 600;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
}

.species-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 16px;
}

.species-item {
  padding: 12px;
  background: #f8fafc;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.species-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.species-label {
  font-weight: 500;
  color: #334155;
  cursor: pointer;
}

.concentration-control {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e2e8f0;
}

.concentration-control label {
  display: block;
  font-size: 0.9rem;
  font-weight: 500;
  color: #334155;
  margin-bottom: 6px;
}

.slider-input-group {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
  align-items: center;
}

.concentration-slider {
  width: 100%;
}

.concentration-input {
  width: 120px;
}

.field {
  margin-bottom: 16px;
}

.field label {
  display: block;
  font-weight: 500;
  font-size: 0.9rem;
  color: #334155;
  margin-bottom: 6px;
}

.checkbox-field {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.checkbox-field label {
  margin: 0;
}

.form-grid.two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 8px;
}

.blend-button {
  width: 100%;
  margin-top: 8px;
}

.muted-text {
  color: #64748b;
  font-size: 0.85rem;
}

.empty-plot {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 100px 20px;
  text-align: center;
  color: #94a3b8;
  background: #f8fafc;
  border-radius: 8px;
  border: 2px dashed #e2e8f0;
}

.empty-plot p {
  margin-top: 16px;
  color: #64748b;
}

.blend-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-top: 16px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 6px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-item label {
  font-size: 0.85rem;
  color: #64748b;
  font-weight: 500;
}

.stat-item span {
  font-size: 1rem;
  color: #1e293b;
  font-weight: 600;
}

@media (max-width: 1200px) {
  .blend-content {
    grid-template-columns: 1fr;
  }
}
</style>
