<template>
  <div class="template-gallery">
    <!-- Featured -->
    <div class="tg-section">
      <h3 class="tg-section-title">Featured Workflows</h3>
      <div class="tg-cards">
        <div
          v-for="tmpl in featured"
          :key="tmpl.id"
          class="tg-card featured"
          @click="$emit('select', tmpl.id)"
        >
          <div class="tg-badge">{{ tmpl.badge }}</div>
          <div class="tg-card-header">
            <div class="tg-icon">
              <i :class="tmpl.icon"></i>
            </div>
            <div>
              <h4 class="tg-card-title">{{ tmpl.title }}</h4>
              <p class="tg-card-sub">Ready to use</p>
            </div>
          </div>
          <p class="tg-card-desc">{{ tmpl.description }}</p>
          <div v-if="tmpl.steps" class="tg-steps">
            <ol>
              <li v-for="step in tmpl.steps" :key="step">{{ step }}</li>
            </ol>
          </div>
        </div>
      </div>
    </div>

    <!-- SpectrochemPy Examples -->
    <div class="tg-section">
      <h3 class="tg-section-title">SpectrochemPy Examples</h3>
      <div class="tg-cards">
        <div
          v-for="tmpl in examples"
          :key="tmpl.id"
          class="tg-card"
          :class="tmpl.technique"
          @click="$emit('select', tmpl.id)"
        >
          <div class="tg-badge" :class="tmpl.technique">{{ tmpl.badge }}</div>
          <div class="tg-card-header">
            <div class="tg-icon" :class="tmpl.technique">
              <i :class="tmpl.icon"></i>
            </div>
            <div>
              <h4 class="tg-card-title">{{ tmpl.title }}</h4>
              <p class="tg-card-sub">{{ tmpl.category }}</p>
            </div>
          </div>
          <p class="tg-card-desc">{{ tmpl.description }}</p>
        </div>
      </div>
    </div>

    <!-- Basic Templates -->
    <div class="tg-section">
      <h3 class="tg-section-title">Basic Templates</h3>
      <div class="tg-cards">
        <div
          v-for="tmpl in basics"
          :key="tmpl.id"
          class="tg-card basic"
          @click="$emit('select', tmpl.id)"
        >
          <div class="tg-badge basic">{{ tmpl.badge }}</div>
          <div class="tg-card-header">
            <div class="tg-icon basic">
              <i :class="tmpl.icon"></i>
            </div>
            <div>
              <h4 class="tg-card-title">{{ tmpl.title }}</h4>
              <p class="tg-card-sub">Template</p>
            </div>
          </div>
          <p class="tg-card-desc">{{ tmpl.description }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineEmits<{
  select: [templateId: string];
}>();

interface TemplateItem {
  id: string;
  badge: string;
  icon: string;
  title: string;
  description: string;
  technique?: string;
  category?: string;
  steps?: string[];
}

const featured: TemplateItem[] = [
  {
    id: "project1",
    badge: "Calibration",
    icon: "pi pi-chart-line",
    title: "Absorption Calibration",
    description:
      "Build wavenumber-specific absorption vs. concentration calibration models using PLS regression with cross-validation.",
    steps: [
      "Load OPUS/CSV experimental spectra",
      "Load reference library spectra (JDX)",
      "Apply ASLS baseline correction",
      "SNV normalization",
      "PLS model with 10-fold CV",
      "Export calibration model",
    ],
  },
  {
    id: "project2",
    badge: "MCR-ALS",
    icon: "pi pi-share-alt",
    title: "MCR-ALS with Kinetics",
    description:
      "Multivariate Curve Resolution with kinetic constraints for time-resolved spectroscopy and reaction mechanism analysis.",
    steps: [
      "Load time-series spectra",
      "Apply ASLS baseline + smoothing",
      "Configure non-negativity & closure",
      "Run MCR-ALS optimization",
      "Plot concentrations & pure spectra",
      "Export results to CSV",
    ],
  },
];

const examples: TemplateItem[] = [
  {
    id: "ir_opus_analysis",
    badge: "IR",
    technique: "ir",
    icon: "pi pi-file-import",
    title: "IR OPUS Import & Analysis",
    category: "Spectroscopy",
    description:
      "Import Bruker OPUS files, slice wavenumber range, apply rubberband baseline, normalize, and detect peaks.",
  },
  {
    id: "raman_processing",
    badge: "Raman",
    technique: "raman",
    icon: "pi pi-sun",
    title: "Raman Processing Pipeline",
    category: "Spectroscopy",
    description:
      "Cosmic ray removal, fluorescence baseline correction, Whittaker smoothing, and intensity normalization.",
  },
  {
    id: "nmr_processing",
    badge: "NMR",
    technique: "nmr",
    icon: "pi pi-wave-pulse",
    title: "NMR Processing Workflow",
    category: "Spectroscopy",
    description:
      "Phase correction, polynomial baseline, ppm slicing, CWT peak picking, and Lorentzian peak fitting.",
  },
  {
    id: "pls_regression",
    badge: "PLS",
    technique: "chemometrics",
    icon: "pi pi-chart-scatter",
    title: "PLS Regression Analysis",
    category: "Chemometrics",
    description:
      "Partial Least Squares regression with cross-validation, RMSECV plots, and predicted vs. actual visualization.",
  },
  {
    id: "efa_analysis",
    badge: "EFA",
    technique: "chemometrics",
    icon: "pi pi-sort-amount-up",
    title: "Evolving Factor Analysis",
    category: "Chemometrics",
    description:
      "Determine component rank in evolving mixtures with forward/backward EFA and eigenvalue plots.",
  },
  {
    id: "iris_decomposition",
    badge: "IRIS",
    technique: "chemometrics",
    icon: "pi pi-sliders-h",
    title: "IRIS Decomposition",
    category: "Chemometrics",
    description:
      "Integral Regularized Inversion of Spectra for relaxation time distribution analysis with Tikhonov regularization.",
  },
  {
    id: "simplisma",
    badge: "SIMPLISMA",
    technique: "chemometrics",
    icon: "pi pi-sitemap",
    title: "SIMPLISMA Pure Variables",
    category: "Chemometrics",
    description:
      "Self-modeling mixture analysis for initial pure component estimates with purity plots.",
  },
];

const basics: TemplateItem[] = [
  {
    id: "preprocessing",
    badge: "Basic",
    icon: "pi pi-filter",
    title: "Standard Preprocessing",
    description:
      "Basic preprocessing pipeline: ASLS baseline, Savitzky-Golay smoothing, SNV normalization.",
  },
  {
    id: "pca",
    badge: "Basic",
    icon: "pi pi-th-large",
    title: "PCA Exploration",
    description:
      "Exploratory PCA with scores, loadings, scree plots, and outlier detection (Hotelling T\u00B2, Q residuals).",
  },
  {
    id: "peaks",
    badge: "Basic",
    icon: "pi pi-search",
    title: "Peak Detection & Fitting",
    description:
      "Automated peak detection with Gaussian/Lorentzian fitting, FWHM, and area quantification.",
  },
];
</script>

<style scoped>
.template-gallery {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.tg-section-title {
  margin: 0 0 12px;
  font-size: 0.95rem;
  font-weight: 600;
  color: #334155;
  padding-bottom: 8px;
  border-bottom: 1px solid #e2e8f0;
}

.tg-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tg-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.tg-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.1);
}

.tg-card.featured {
  border-color: #3b82f6;
  background: linear-gradient(to bottom right, #ffffff, #eff6ff);
}

.tg-badge {
  display: inline-block;
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 3px 8px;
  border-radius: 4px;
  background: #dbeafe;
  color: #1d4ed8;
  width: fit-content;
}

.tg-badge.basic {
  background: #f1f5f9;
  color: #64748b;
}

.tg-badge.ir {
  background: #fef3c7;
  color: #92400e;
}

.tg-badge.raman {
  background: #dcfce7;
  color: #166534;
}

.tg-badge.nmr {
  background: #fce7f3;
  color: #9d174d;
}

.tg-badge.chemometrics {
  background: #ede9fe;
  color: #5b21b6;
}

.tg-card-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.tg-icon {
  width: 42px;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #eff6ff;
  border-radius: 10px;
  flex-shrink: 0;
}

.tg-icon i {
  font-size: 1.25rem;
  color: #3b82f6;
}

.tg-icon.basic {
  background: #f1f5f9;
}

.tg-icon.basic i {
  color: #64748b;
}

.tg-icon.ir {
  background: #fef3c7;
}

.tg-icon.ir i {
  color: #d97706;
}

.tg-icon.raman {
  background: #dcfce7;
}

.tg-icon.raman i {
  color: #16a34a;
}

.tg-icon.nmr {
  background: #fce7f3;
}

.tg-icon.nmr i {
  color: #db2777;
}

.tg-icon.chemometrics {
  background: #ede9fe;
}

.tg-icon.chemometrics i {
  color: #7c3aed;
}

.tg-card-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: #1e293b;
}

.tg-card-sub {
  margin: 2px 0 0;
  font-size: 0.75rem;
  color: #10b981;
  font-weight: 500;
}

.tg-card-desc {
  margin: 0;
  color: #64748b;
  font-size: 0.8rem;
  line-height: 1.5;
}

.tg-steps {
  background: #f8fafc;
  border-radius: 6px;
  padding: 10px 12px;
}

.tg-steps ol {
  margin: 0;
  padding-left: 18px;
}

.tg-steps li {
  font-size: 0.78rem;
  color: #64748b;
  margin-bottom: 4px;
  line-height: 1.4;
}

.tg-steps li:last-child {
  margin-bottom: 0;
}
</style>
