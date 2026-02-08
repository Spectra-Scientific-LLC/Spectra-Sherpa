<template>
  <section class="analysis-content">
    <div class="section-header">
      <div>
        <h1>Analysis</h1>
        <p class="section-subtitle">
          Apply chemometric and multivariate analysis methods (SpectrochemPy)
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

    <div class="analysis-layout">
      <!-- Left: Category Navigation -->
      <div class="category-nav">
        <div
          v-for="category in categories"
          :key="category.id"
          class="category-item"
          :class="{ active: activeCategory === category.id }"
          @click="activeCategory = category.id"
        >
          <i :class="category.icon"></i>
          <span>{{ category.name }}</span>
          <span class="method-count">{{ category.methods.length }}</span>
        </div>
      </div>

      <!-- Center: Method Cards -->
      <div class="methods-panel">
        <h2>{{ currentCategory?.name }}</h2>
        <div class="method-cards">
          <div
            v-for="method in currentCategory?.methods"
            :key="method.id"
            class="method-card"
            :class="{ selected: selectedMethod?.id === method.id, disabled: method.status !== 'available' }"
            @click="selectMethod(method)"
          >
            <div class="method-card-header">
              <div class="method-icon">
                <i :class="method.icon"></i>
              </div>
              <span class="method-badge" :class="method.status">
                {{ method.status === 'available' ? 'Ready' : 'Coming soon' }}
              </span>
            </div>
            <h3>{{ method.name }}</h3>
            <p>{{ method.shortDesc }}</p>
          </div>
        </div>
      </div>

      <!-- Right: Method Details -->
      <div class="details-panel" v-if="selectedMethod">
        <div class="details-header">
          <h3>{{ selectedMethod.name }}</h3>
          <span class="scp-badge">scp.{{ selectedMethod.scpClass }}()</span>
        </div>

        <p class="details-description">{{ selectedMethod.description }}</p>

        <!-- Quick Info -->
        <div class="quick-info">
          <div class="info-item">
            <span class="info-label">Input</span>
            <span class="info-value">{{ selectedMethod.input }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">Output</span>
            <span class="info-value">{{ selectedMethod.output }}</span>
          </div>
        </div>

        <!-- Parameters -->
        <div class="parameters-section" v-if="selectedMethod.parameters.length">
          <h4>Parameters</h4>
          <div class="parameters-list">
            <div v-for="param in selectedMethod.parameters" :key="param.name" class="param-row">
              <div class="param-info">
                <span class="param-name">{{ param.name }}</span>
                <span class="param-desc">{{ param.description }}</span>
              </div>
              <div class="param-input">
                <InputNumber
                  v-if="param.type === 'int'"
                  v-model="paramValues[param.name]"
                  :min="param.min"
                  :max="param.max"
                  size="small"
                />
                <InputNumber
                  v-else-if="param.type === 'float'"
                  v-model="paramValues[param.name]"
                  :min="param.min"
                  :max="param.max"
                  :minFractionDigits="1"
                  :maxFractionDigits="4"
                  size="small"
                />
                <Dropdown
                  v-else-if="param.type === 'choice'"
                  v-model="paramValues[param.name]"
                  :options="param.choices"
                  size="small"
                />
                <InputSwitch
                  v-else-if="param.type === 'bool'"
                  v-model="paramValues[param.name]"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- Actions -->
        <div class="details-actions">
          <Button
            label="Run Analysis"
            icon="pi pi-play"
            :loading="isRunning"
            :disabled="!selectedDataset || selectedMethod.status !== 'available' || isRunning"
            @click="runAnalysis"
          />
          <Button
            label="Add to Workflow"
            icon="pi pi-plus"
            class="p-button-outlined"
            @click="addToWorkflow"
          />
        </div>

        <!-- Code Preview -->
        <div class="code-preview">
          <div class="code-header">
            <h4>Python Code</h4>
            <Button
              icon="pi pi-copy"
              class="p-button-text p-button-sm"
              @click="copyCode"
            />
          </div>
          <pre><code>{{ generatedCode }}</code></pre>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else class="details-panel empty">
        <i class="pi pi-chart-bar"></i>
        <p>Select an analysis method to view details</p>
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

interface AnalysisMethod {
  id: string;
  name: string;
  shortDesc: string;
  description: string;
  icon: string;
  scpClass: string;
  status: "available" | "coming-soon";
  input: string;
  output: string;
  parameters: {
    name: string;
    description: string;
    type: "int" | "float" | "choice" | "bool";
    default: any;
    min?: number;
    max?: number;
    choices?: string[];
  }[];
}

interface Category {
  id: string;
  name: string;
  icon: string;
  methods: AnalysisMethod[];
}

// Datasets from experiment store
const datasets = computed(() =>
  experimentStore.experiments.map(exp => ({
    id: exp.id,
    name: exp.name,
  }))
);
const selectedDataset = ref<{ id: number; name: string } | null>(null);
const activeCategory = ref("decomposition");
const selectedMethod = ref<AnalysisMethod | null>(null);
const paramValues = ref<Record<string, any>>({});
const isRunning = ref(false);

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

const categories: Category[] = [
  {
    id: "decomposition",
    name: "Decomposition",
    icon: "pi pi-th-large",
    methods: [
      {
        id: "pca",
        name: "PCA",
        shortDesc: "Dimensionality reduction and pattern recognition",
        description: "Principal Component Analysis decomposes spectral data into orthogonal components ordered by explained variance. Ideal for exploratory analysis, outlier detection, and feature extraction.",
        icon: "pi pi-th-large",
        scpClass: "PCA",
        status: "available",
        input: "NDDataset (n_samples × n_features)",
        output: "Scores, Loadings, Explained Variance",
        parameters: [
          { name: "n_components", description: "Number of components to keep", type: "int", default: 10, min: 1, max: 50 },
          { name: "standardize", description: "Standardize data before PCA", type: "bool", default: true },
        ],
      },
      {
        id: "mcr",
        name: "MCR-ALS",
        shortDesc: "Spectral unmixing and concentration extraction",
        description: "Multivariate Curve Resolution with Alternating Least Squares. Decomposes mixture spectra into pure component spectra and concentration profiles.",
        icon: "pi pi-share-alt",
        scpClass: "MCR_ALS",
        status: "available",
        input: "NDDataset (mixtures)",
        output: "Pure Spectra (S), Concentrations (C)",
        parameters: [
          { name: "n_components", description: "Number of pure components", type: "int", default: 3, min: 1, max: 20 },
          { name: "max_iter", description: "Maximum iterations", type: "int", default: 100, min: 10, max: 1000 },
          { name: "tol", description: "Convergence tolerance", type: "float", default: 0.0001, min: 0.00001, max: 0.01 },
        ],
      },
      {
        id: "nmf",
        name: "NMF",
        shortDesc: "Non-negative spectral decomposition",
        description: "Non-negative Matrix Factorization constrains both components and loadings to be non-negative, often more interpretable for spectral data.",
        icon: "pi pi-sitemap",
        scpClass: "NMF",
        status: "coming-soon",
        input: "NDDataset (non-negative)",
        output: "Components, Loadings",
        parameters: [
          { name: "n_components", description: "Number of components", type: "int", default: 5, min: 1, max: 20 },
        ],
      },
    ],
  },
  {
    id: "clustering",
    name: "Classification & Clustering",
    icon: "pi pi-chart-scatter",
    methods: [
      {
        id: "kmeans",
        name: "K-Means Clustering",
        shortDesc: "Partition spectra into k groups",
        description: "Partition spectra into k clusters based on spectral similarity. Useful for identifying groups or categories in spectral datasets.",
        icon: "pi pi-chart-scatter",
        scpClass: "cluster_kmeans",
        status: "available",
        input: "NDDataset",
        output: "Cluster Labels, Centroids",
        parameters: [
          { name: "n_clusters", description: "Number of clusters", type: "int", default: 3, min: 2, max: 20 },
          { name: "n_init", description: "Number of initializations", type: "int", default: 10, min: 1, max: 50 },
        ],
      },
      {
        id: "hierarchical",
        name: "Hierarchical Clustering",
        shortDesc: "Build tree of spectral relationships",
        description: "Agglomerative hierarchical clustering builds a tree (dendrogram) showing relationships between spectra at different similarity levels.",
        icon: "pi pi-sitemap",
        scpClass: "cluster_hierarchical",
        status: "available",
        input: "NDDataset",
        output: "Dendrogram, Cluster Labels",
        parameters: [
          { name: "n_clusters", description: "Number of clusters (cut level)", type: "int", default: 3, min: 2, max: 20 },
          { name: "linkage", description: "Linkage method", type: "choice", default: "ward", choices: ["ward", "complete", "average", "single"] },
        ],
      },
      {
        id: "plsda",
        name: "PLS-DA",
        shortDesc: "Supervised classification",
        description: "Partial Least Squares Discriminant Analysis for supervised classification of spectra into predefined groups.",
        icon: "pi pi-tags",
        scpClass: "PLS_DA",
        status: "coming-soon",
        input: "NDDataset + Labels",
        output: "Classification Model",
        parameters: [
          { name: "n_components", description: "Number of latent variables", type: "int", default: 5, min: 1, max: 20 },
        ],
      },
    ],
  },
  {
    id: "regression",
    name: "Regression & Calibration",
    icon: "pi pi-chart-line",
    methods: [
      {
        id: "pls",
        name: "PLS Regression",
        shortDesc: "Quantitative calibration models",
        description: "Partial Least Squares regression builds quantitative models relating spectral features to concentrations or properties.",
        icon: "pi pi-chart-line",
        scpClass: "PLS",
        status: "available",
        input: "NDDataset + Y values",
        output: "Regression Model, Predictions",
        parameters: [
          { name: "n_components", description: "Number of latent variables", type: "int", default: 5, min: 1, max: 20 },
          { name: "scale", description: "Scale X data", type: "bool", default: true },
        ],
      },
      {
        id: "rsm",
        name: "RSM",
        shortDesc: "Response Surface Methodology",
        description: "Response Surface Methodology for DOE analysis. Fits polynomial models to explore relationships between factors and responses.",
        icon: "pi pi-sliders-h",
        scpClass: "RSM",
        status: "coming-soon",
        input: "DOE Data + Responses",
        output: "Surface Model, Optima",
        parameters: [
          { name: "order", description: "Polynomial order", type: "int", default: 2, min: 1, max: 3 },
        ],
      },
    ],
  },
  {
    id: "peaks",
    name: "Peak Analysis",
    icon: "pi pi-search",
    methods: [
      {
        id: "peak_detect",
        name: "Peak Detection",
        shortDesc: "Find and characterize peaks",
        description: "Automatically detect peaks in spectra, extracting position, height, width, and area for each peak.",
        icon: "pi pi-search",
        scpClass: "find_peaks",
        status: "available",
        input: "NDDataset (spectrum)",
        output: "Peak Table (position, height, width)",
        parameters: [
          { name: "height_threshold", description: "Minimum peak height", type: "float", default: 0.01, min: 0, max: 1 },
          { name: "distance", description: "Minimum distance between peaks", type: "int", default: 10, min: 1, max: 100 },
        ],
      },
      {
        id: "peak_fit",
        name: "Peak Fitting",
        shortDesc: "Fit peak profiles",
        description: "Fit detected peaks with analytical functions (Gaussian, Lorentzian, Voigt) for accurate quantification.",
        icon: "pi pi-chart-bar",
        scpClass: "fit_peaks",
        status: "coming-soon",
        input: "Spectrum + Peak positions",
        output: "Fitted Parameters, Areas",
        parameters: [
          { name: "profile", description: "Peak profile function", type: "choice", default: "gaussian", choices: ["gaussian", "lorentzian", "voigt"] },
        ],
      },
    ],
  },
];

const currentCategory = computed(() => {
  return categories.find((c) => c.id === activeCategory.value);
});

const selectMethod = (method: AnalysisMethod) => {
  if (method.status !== "available") return;
  selectedMethod.value = method;
  paramValues.value = {};
  method.parameters.forEach((p) => {
    paramValues.value[p.name] = p.default;
  });
};

const generatedCode = computed(() => {
  if (!selectedMethod.value) return "";
  const method = selectedMethod.value;
  const params = method.parameters
    .map((p) => `    ${p.name}=${JSON.stringify(paramValues.value[p.name] ?? p.default)}`)
    .join(",\n");

  return `import spectrochempy as scp

# Load your dataset
dataset = scp.read("your_data.csv")

# Run ${method.name}
model = scp.${method.scpClass}(
${params}
)
result = model.fit(dataset)

# Access results
print(result)`;
});

const runAnalysis = async () => {
  if (!selectedMethod.value || !selectedDataset.value) return;

  isRunning.value = true;
  const method = selectedMethod.value;

  toast.add({
    severity: "info",
    summary: "Running Analysis",
    detail: `Executing ${method.name} on ${selectedDataset.value.name}...`,
    life: 2000,
  });

  try {
    // Build parameters object
    const params: Record<string, any> = {};
    method.parameters.forEach((p) => {
      params[p.name] = paramValues.value[p.name] ?? p.default;
    });

    // Call analysis API endpoint
    const response = await api.post(`/analysis/${method.scpClass.toLowerCase()}`, {
      experiment_id: selectedDataset.value.id,
      parameters: params,
    });

    toast.add({
      severity: "success",
      summary: "Analysis Complete",
      detail: `${method.name} completed successfully`,
      life: 3000,
    });

    // Refresh experiment files to show analysis results
    await experimentStore.fetchFiles(selectedDataset.value.id);

    return response.data;
  } catch (err: any) {
    const message = err?.response?.data?.detail || err?.message || "Analysis failed";
    toast.add({
      severity: "error",
      summary: "Analysis Error",
      detail: message,
      life: 4000,
    });
    throw err;
  } finally {
    isRunning.value = false;
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
.analysis-content {
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

.analysis-layout {
  display: grid;
  grid-template-columns: 200px 1fr 380px;
  gap: 20px;
  flex: 1;
  min-height: 0;
}

/* Category Navigation */
.category-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.category-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s ease;
  color: #64748b;
}

.category-item:hover {
  background: #f1f5f9;
}

.category-item.active {
  background: #eff6ff;
  color: #3b82f6;
  font-weight: 500;
}

.category-item i {
  font-size: 1.1rem;
}

.category-item span:first-of-type {
  flex: 1;
  font-size: 0.9rem;
}

.method-count {
  font-size: 0.75rem;
  padding: 2px 8px;
  background: #e2e8f0;
  border-radius: 10px;
}

.category-item.active .method-count {
  background: #dbeafe;
}

/* Methods Panel */
.methods-panel {
  overflow-y: auto;
}

.methods-panel h2 {
  margin: 0 0 16px;
  font-size: 1.1rem;
  font-weight: 600;
  color: #334155;
}

.method-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
}

.method-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.method-card:hover:not(.disabled) {
  border-color: #3b82f6;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.1);
}

.method-card.selected {
  border-color: #3b82f6;
  background: #eff6ff;
}

.method-card.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.method-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.method-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #eff6ff;
  border-radius: 8px;
}

.method-icon i {
  font-size: 1.25rem;
  color: #3b82f6;
}

.method-badge {
  font-size: 0.65rem;
  font-weight: 500;
  padding: 3px 8px;
  border-radius: 4px;
}

.method-badge.available {
  background: #dcfce7;
  color: #166534;
}

.method-badge.coming-soon {
  background: #fef3c7;
  color: #92400e;
}

.method-card h3 {
  margin: 0 0 6px;
  font-size: 1rem;
  font-weight: 600;
}

.method-card p {
  margin: 0;
  font-size: 0.8rem;
  color: #64748b;
  line-height: 1.4;
}

/* Details Panel */
.details-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 20px;
  overflow-y: auto;
}

.details-panel.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  text-align: center;
}

.details-panel.empty i {
  font-size: 2.5rem;
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
  font-size: 1.2rem;
  font-weight: 600;
}

.scp-badge {
  font-family: monospace;
  font-size: 0.75rem;
  padding: 4px 10px;
  background: #f1f5f9;
  border-radius: 4px;
  color: #475569;
}

.details-description {
  color: #64748b;
  font-size: 0.9rem;
  line-height: 1.5;
  margin-bottom: 16px;
}

.quick-info {
  display: flex;
  gap: 16px;
  margin-bottom: 20px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-label {
  font-size: 0.75rem;
  font-weight: 500;
  color: #94a3b8;
  text-transform: uppercase;
}

.info-value {
  font-size: 0.85rem;
  color: #334155;
}

.parameters-section h4 {
  margin: 0 0 12px;
  font-size: 0.9rem;
  font-weight: 600;
  color: #334155;
}

.parameters-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 20px;
}

.param-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.param-info {
  flex: 1;
}

.param-name {
  font-size: 0.85rem;
  font-weight: 500;
  font-family: monospace;
}

.param-desc {
  display: block;
  font-size: 0.75rem;
  color: #94a3b8;
}

.param-input {
  width: 120px;
}

.details-actions {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

.code-preview {
  background: #1e293b;
  border-radius: 8px;
  padding: 16px;
}

.code-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.code-header h4 {
  margin: 0;
  font-size: 0.85rem;
  color: #94a3b8;
}

.code-preview pre {
  margin: 0;
  font-family: "Fira Code", monospace;
  font-size: 0.8rem;
  color: #e2e8f0;
  white-space: pre-wrap;
  line-height: 1.5;
}

@media (max-width: 1200px) {
  .analysis-layout {
    grid-template-columns: 180px 1fr 320px;
  }
}

@media (max-width: 900px) {
  .analysis-layout {
    grid-template-columns: 1fr;
  }

  .category-nav {
    flex-direction: row;
    overflow-x: auto;
  }
}
</style>
