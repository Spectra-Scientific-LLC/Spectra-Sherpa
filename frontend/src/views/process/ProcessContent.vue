<template>
  <section class="process-content">
    <div class="section-header">
      <div>
        <h1>Process</h1>
        <p class="section-subtitle">
          Apply preprocessing operations to spectral data (SpectrochemPy methods)
        </p>
      </div>
      <div class="header-actions">
        <Dropdown
          v-model="selectedDataset"
          :options="datasets"
          optionLabel="name"
          placeholder="Select dataset"
          class="dataset-selector"
        />
      </div>
    </div>

    <div class="process-layout">
      <!-- Left: Operation Categories -->
      <div class="process-categories">
        <!-- Baseline Correction -->
        <div class="category-card" :class="{ active: activeCategory === 'baseline' }">
          <div class="category-header" @click="activeCategory = 'baseline'">
            <i class="pi pi-minus"></i>
            <h3>Baseline Correction</h3>
            <i class="pi pi-chevron-right expand-icon"></i>
          </div>
          <p class="category-description">
            Remove baseline drift and background interference
          </p>
          <div v-if="activeCategory === 'baseline'" class="method-list">
            <div
              v-for="method in baselineMethods"
              :key="method.id"
              class="method-item"
              :class="{ selected: selectedMethod?.id === method.id }"
              @click="selectMethod(method)"
            >
              <span class="method-name">{{ method.name }}</span>
              <span class="method-tag" :class="method.status">{{ method.statusLabel }}</span>
            </div>
          </div>
        </div>

        <!-- Smoothing -->
        <div class="category-card" :class="{ active: activeCategory === 'smoothing' }">
          <div class="category-header" @click="activeCategory = 'smoothing'">
            <i class="pi pi-chart-line"></i>
            <h3>Smoothing</h3>
            <i class="pi pi-chevron-right expand-icon"></i>
          </div>
          <p class="category-description">
            Reduce noise while preserving spectral features
          </p>
          <div v-if="activeCategory === 'smoothing'" class="method-list">
            <div
              v-for="method in smoothingMethods"
              :key="method.id"
              class="method-item"
              :class="{ selected: selectedMethod?.id === method.id }"
              @click="selectMethod(method)"
            >
              <span class="method-name">{{ method.name }}</span>
              <span class="method-tag" :class="method.status">{{ method.statusLabel }}</span>
            </div>
          </div>
        </div>

        <!-- Alignment -->
        <div class="category-card" :class="{ active: activeCategory === 'alignment' }">
          <div class="category-header" @click="activeCategory = 'alignment'">
            <i class="pi pi-arrows-h"></i>
            <h3>Alignment</h3>
            <i class="pi pi-chevron-right expand-icon"></i>
          </div>
          <p class="category-description">
            Correct wavenumber shifts and align spectra
          </p>
          <div v-if="activeCategory === 'alignment'" class="method-list">
            <div
              v-for="method in alignmentMethods"
              :key="method.id"
              class="method-item"
              :class="{ selected: selectedMethod?.id === method.id }"
              @click="selectMethod(method)"
            >
              <span class="method-name">{{ method.name }}</span>
              <span class="method-tag" :class="method.status">{{ method.statusLabel }}</span>
            </div>
          </div>
        </div>

        <!-- Interpolation -->
        <div class="category-card" :class="{ active: activeCategory === 'interpolation' }">
          <div class="category-header" @click="activeCategory = 'interpolation'">
            <i class="pi pi-table"></i>
            <h3>Interpolation</h3>
            <i class="pi pi-chevron-right expand-icon"></i>
          </div>
          <p class="category-description">
            Resample spectra to common wavenumber grid
          </p>
          <div v-if="activeCategory === 'interpolation'" class="method-list">
            <div
              v-for="method in interpolationMethods"
              :key="method.id"
              class="method-item"
              :class="{ selected: selectedMethod?.id === method.id }"
              @click="selectMethod(method)"
            >
              <span class="method-name">{{ method.name }}</span>
              <span class="method-tag" :class="method.status">{{ method.statusLabel }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Method Details Panel -->
      <div class="method-details" v-if="selectedMethod">
        <div class="details-header">
          <h3>{{ selectedMethod.name }}</h3>
          <span class="scp-badge">scp.{{ selectedMethod.scpMethod }}()</span>
        </div>
        <p class="details-description">{{ selectedMethod.description }}</p>

        <div class="parameters-section">
          <h4>Parameters</h4>
          <div class="parameters-grid">
            <div v-for="param in selectedMethod.parameters" :key="param.name" class="param-field">
              <label>{{ param.label }}</label>
              <InputNumber
                v-if="param.type === 'number'"
                v-model="paramValues[param.name]"
                :min="param.min"
                :max="param.max"
                :step="param.step"
              />
              <Dropdown
                v-else-if="param.type === 'select'"
                v-model="paramValues[param.name]"
                :options="param.options"
              />
              <InputSwitch
                v-else-if="param.type === 'boolean'"
                v-model="paramValues[param.name]"
              />
            </div>
          </div>
        </div>

        <div class="details-actions">
          <Button
            label="Apply to Dataset"
            icon="pi pi-play"
            :loading="isProcessing"
            :disabled="!selectedDataset || selectedMethod.status !== 'available' || isProcessing"
            @click="applyMethod"
          />
          <Button
            label="Add to Workflow"
            icon="pi pi-plus"
            class="p-button-outlined"
            @click="addToWorkflow"
          />
        </div>

        <div class="code-preview">
          <h4>Python Code</h4>
          <pre><code>{{ generatedCode }}</code></pre>
          <Button
            icon="pi pi-copy"
            class="p-button-text p-button-sm copy-btn"
            @click="copyCode"
          />
        </div>
      </div>

      <!-- Empty State -->
      <div v-else class="method-details empty">
        <i class="pi pi-arrow-left"></i>
        <p>Select a processing method to view details and parameters</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import Button from "primevue/button";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import InputSwitch from "primevue/inputswitch";
import { useToast } from "primevue/usetoast";
import { useExperimentStore } from "@/stores/experiment";
import api from "@/api/client";

const toast = useToast();
const experimentStore = useExperimentStore();

interface ProcessMethod {
  id: string;
  name: string;
  scpMethod: string;
  description: string;
  status: "available" | "coming-soon";
  statusLabel: string;
  parameters: {
    name: string;
    label: string;
    type: "number" | "select" | "boolean";
    default: any;
    min?: number;
    max?: number;
    step?: number;
    options?: string[];
  }[];
}

// Datasets from experiment store
const datasets = computed(() =>
  experimentStore.experiments.map(exp => ({
    id: exp.id,
    name: exp.name,
  }))
);
const selectedDataset = ref<{ id: number; name: string } | null>(null);
const isProcessing = ref(false);

// Fetch experiments on mount
onMounted(async () => {
  if (experimentStore.experiments.length === 0) {
    try {
      await experimentStore.fetchExperiments();
    } catch {
      toast.add({
        severity: "error",
        summary: "Error",
        detail: "Failed to load experiments",
        life: 3000,
      });
    }
  }
});

const activeCategory = ref<string | null>("baseline");
const selectedMethod = ref<ProcessMethod | null>(null);
const paramValues = ref<Record<string, any>>({});

// Baseline methods
const baselineMethods: ProcessMethod[] = [
  {
    id: "als",
    name: "ALS Baseline",
    scpMethod: "baseline_als",
    description: "Asymmetric Least Squares baseline correction. Good for smooth baselines with known asymmetry.",
    status: "available",
    statusLabel: "Available",
    parameters: [
      { name: "lam", label: "Lambda (smoothness)", type: "number", default: 1e5, min: 1e2, max: 1e9, step: 1e4 },
      { name: "p", label: "Asymmetry (p)", type: "number", default: 0.001, min: 0.0001, max: 0.5, step: 0.001 },
      { name: "niter", label: "Iterations", type: "number", default: 10, min: 1, max: 100, step: 1 },
    ],
  },
  {
    id: "polynomial",
    name: "Polynomial Fit",
    scpMethod: "baseline_polynomial",
    description: "Fit and subtract polynomial baseline of specified order.",
    status: "available",
    statusLabel: "Available",
    parameters: [
      { name: "order", label: "Polynomial Order", type: "number", default: 2, min: 1, max: 10, step: 1 },
    ],
  },
  {
    id: "rubberband",
    name: "Rubberband",
    scpMethod: "baseline_rubberband",
    description: "Convex hull baseline correction for spectra with peaks above baseline.",
    status: "coming-soon",
    statusLabel: "Coming soon",
    parameters: [],
  },
];

// Smoothing methods
const smoothingMethods: ProcessMethod[] = [
  {
    id: "savgol",
    name: "Savitzky-Golay",
    scpMethod: "smooth_savgol",
    description: "Polynomial smoothing filter that preserves peak shapes and heights.",
    status: "available",
    statusLabel: "Available",
    parameters: [
      { name: "window", label: "Window Size", type: "number", default: 15, min: 5, max: 51, step: 2 },
      { name: "order", label: "Polynomial Order", type: "number", default: 2, min: 1, max: 5, step: 1 },
      { name: "deriv", label: "Derivative", type: "number", default: 0, min: 0, max: 2, step: 1 },
    ],
  },
  {
    id: "moving_avg",
    name: "Moving Average",
    scpMethod: "smooth_ma",
    description: "Simple moving average filter for noise reduction.",
    status: "available",
    statusLabel: "Available",
    parameters: [
      { name: "window", label: "Window Size", type: "number", default: 5, min: 3, max: 51, step: 2 },
    ],
  },
  {
    id: "gaussian",
    name: "Gaussian Filter",
    scpMethod: "smooth_gaussian",
    description: "Gaussian-weighted smoothing for gentle noise reduction.",
    status: "coming-soon",
    statusLabel: "Coming soon",
    parameters: [
      { name: "sigma", label: "Sigma", type: "number", default: 1.0, min: 0.1, max: 10, step: 0.1 },
    ],
  },
];

// Alignment methods
const alignmentMethods: ProcessMethod[] = [
  {
    id: "peak_align",
    name: "Peak Alignment",
    scpMethod: "align_peak",
    description: "Align spectra based on a reference peak position.",
    status: "available",
    statusLabel: "Available",
    parameters: [
      { name: "target", label: "Target Wavenumber", type: "number", default: 2350, min: 400, max: 4000, step: 1 },
      { name: "window", label: "Search Window", type: "number", default: 50, min: 5, max: 200, step: 5 },
    ],
  },
  {
    id: "dtw",
    name: "DTW Alignment",
    scpMethod: "align_dtw",
    description: "Dynamic Time Warping for non-linear spectral alignment.",
    status: "coming-soon",
    statusLabel: "Coming soon",
    parameters: [],
  },
  {
    id: "reference_shift",
    name: "Reference Shift",
    scpMethod: "align_reference",
    description: "Shift spectra to match a reference spectrum.",
    status: "coming-soon",
    statusLabel: "Coming soon",
    parameters: [],
  },
];

// Interpolation methods
const interpolationMethods: ProcessMethod[] = [
  {
    id: "linear",
    name: "Linear Interpolation",
    scpMethod: "interpolate",
    description: "Resample to uniform wavenumber grid using linear interpolation.",
    status: "available",
    statusLabel: "Available",
    parameters: [
      { name: "start", label: "Start (cm⁻¹)", type: "number", default: 400, min: 0, max: 10000, step: 10 },
      { name: "end", label: "End (cm⁻¹)", type: "number", default: 4000, min: 0, max: 10000, step: 10 },
      { name: "points", label: "Number of Points", type: "number", default: 1000, min: 100, max: 10000, step: 100 },
    ],
  },
  {
    id: "pchip",
    name: "PCHIP",
    scpMethod: "interpolate_pchip",
    description: "Piecewise Cubic Hermite Interpolating Polynomial - preserves monotonicity.",
    status: "available",
    statusLabel: "Available",
    parameters: [
      { name: "start", label: "Start (cm⁻¹)", type: "number", default: 400, min: 0, max: 10000, step: 10 },
      { name: "end", label: "End (cm⁻¹)", type: "number", default: 4000, min: 0, max: 10000, step: 10 },
      { name: "points", label: "Number of Points", type: "number", default: 1000, min: 100, max: 10000, step: 100 },
    ],
  },
  {
    id: "spline",
    name: "Spline",
    scpMethod: "interpolate_spline",
    description: "Cubic spline interpolation for smooth resampling.",
    status: "coming-soon",
    statusLabel: "Coming soon",
    parameters: [],
  },
];

const selectMethod = (method: ProcessMethod) => {
  selectedMethod.value = method;
  // Initialize parameter values with defaults
  paramValues.value = {};
  method.parameters.forEach((param) => {
    paramValues.value[param.name] = param.default;
  });
};

const generatedCode = computed(() => {
  if (!selectedMethod.value) return "";
  const method = selectedMethod.value;
  const params = method.parameters
    .map((p) => `${p.name}=${paramValues.value[p.name] ?? p.default}`)
    .join(", ");
  return `# Apply ${method.name}
result = dataset.${method.scpMethod}(${params})`;
});

const applyMethod = async () => {
  if (!selectedMethod.value || !selectedDataset.value) return;

  isProcessing.value = true;
  const method = selectedMethod.value;

  toast.add({
    severity: "info",
    summary: "Processing",
    detail: `Applying ${method.name} to ${selectedDataset.value.name}...`,
    life: 2000,
  });

  try {
    // Build parameters object
    const params: Record<string, any> = {};
    method.parameters.forEach((p) => {
      params[p.name] = paramValues.value[p.name] ?? p.default;
    });

    // Call processing API endpoint
    const response = await api.post(`/process/${method.scpMethod}`, {
      experiment_id: selectedDataset.value.id,
      parameters: params,
    });

    toast.add({
      severity: "success",
      summary: "Processing Complete",
      detail: `${method.name} applied successfully`,
      life: 3000,
    });

    // Refresh experiment files to show processed data
    await experimentStore.fetchFiles(selectedDataset.value.id);

    return response.data;
  } catch (err: any) {
    const message = err?.response?.data?.detail || err?.message || "Processing failed";
    toast.add({
      severity: "error",
      summary: "Processing Error",
      detail: message,
      life: 4000,
    });
    throw err;
  } finally {
    isProcessing.value = false;
  }
};

const addToWorkflow = () => {
  toast.add({
    severity: "success",
    summary: "Added to Workflow",
    detail: `${selectedMethod.value?.name} node added to workflow builder`,
    life: 2000,
  });
};

const copyCode = () => {
  navigator.clipboard.writeText(generatedCode.value);
  toast.add({
    severity: "success",
    summary: "Copied",
    detail: "Python code copied to clipboard",
    life: 1500,
  });
};
</script>

<style scoped>
.process-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
  height: 100%;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.section-header h1 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
}

.section-subtitle {
  margin-top: 4px;
  color: #64748b;
  font-size: 0.95rem;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.dataset-selector {
  min-width: 250px;
}

.process-layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 20px;
  flex: 1;
  min-height: 0;
}

.process-categories {
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
}

.category-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
  transition: border-color 0.2s ease;
}

.category-card.active {
  border-color: #3b82f6;
}

.category-header {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.category-header i:first-child {
  font-size: 1.1rem;
  color: #3b82f6;
}

.category-header h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  flex: 1;
}

.expand-icon {
  font-size: 0.8rem;
  color: #94a3b8;
  transition: transform 0.2s ease;
}

.category-card.active .expand-icon {
  transform: rotate(90deg);
}

.category-description {
  margin: 8px 0 0;
  font-size: 0.85rem;
  color: #64748b;
}

.method-list {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.method-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.method-item:hover {
  background: #eff6ff;
}

.method-item.selected {
  background: #dbeafe;
  border: 1px solid #3b82f6;
}

.method-name {
  font-size: 0.9rem;
  font-weight: 500;
}

.method-tag {
  font-size: 0.7rem;
  padding: 2px 8px;
  border-radius: 4px;
}

.method-tag.available {
  background: #dcfce7;
  color: #166534;
}

.method-tag.coming-soon {
  background: #fef3c7;
  color: #92400e;
}

.method-details {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 24px;
  overflow-y: auto;
}

.method-details.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  text-align: center;
}

.method-details.empty i {
  font-size: 2rem;
  margin-bottom: 12px;
}

.details-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.details-header h3 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
}

.scp-badge {
  font-family: monospace;
  font-size: 0.8rem;
  padding: 4px 10px;
  background: #f1f5f9;
  border-radius: 4px;
  color: #475569;
}

.details-description {
  color: #64748b;
  font-size: 0.95rem;
  line-height: 1.5;
  margin-bottom: 20px;
}

.parameters-section h4,
.code-preview h4 {
  margin: 0 0 12px;
  font-size: 0.9rem;
  font-weight: 600;
  color: #334155;
}

.parameters-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.param-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.param-field label {
  font-size: 0.85rem;
  font-weight: 500;
  color: #475569;
}

.details-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.code-preview {
  position: relative;
  background: #1e293b;
  border-radius: 8px;
  padding: 16px;
}

.code-preview h4 {
  color: #94a3b8;
  margin-bottom: 8px;
}

.code-preview pre {
  margin: 0;
  font-family: "Fira Code", monospace;
  font-size: 0.85rem;
  color: #e2e8f0;
  white-space: pre-wrap;
}

.copy-btn {
  position: absolute;
  top: 12px;
  right: 12px;
  color: #94a3b8;
}

.copy-btn:hover {
  color: #e2e8f0;
}

@media (max-width: 900px) {
  .process-layout {
    grid-template-columns: 1fr;
  }
}
</style>
