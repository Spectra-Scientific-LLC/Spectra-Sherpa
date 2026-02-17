<template>
  <div class="doc-tab">
    <!-- Getting Started -->
    <div class="doc-group">
      <h3><i class="pi pi-home" /> Getting Started</h3>
      <div class="doc-cards">
        <a
          v-for="item in gettingStarted"
          :key="item.path"
          :href="DOCS_BASE + item.path"
          target="_blank"
          rel="noopener"
          class="doc-card"
        >
          <span class="card-title">{{ item.title }}</span>
          <span class="card-desc">{{ item.desc }}</span>
          <i class="pi pi-external-link card-icon" />
        </a>
      </div>
    </div>

    <!-- User Guide -->
    <div class="doc-group">
      <h3><i class="pi pi-book" /> User Guide</h3>
      <div class="doc-cards">
        <a
          v-for="item in userGuide"
          :key="item.path"
          :href="DOCS_BASE + item.path"
          target="_blank"
          rel="noopener"
          class="doc-card"
        >
          <span class="card-title">{{ item.title }}</span>
          <span class="card-desc">{{ item.desc }}</span>
          <i class="pi pi-external-link card-icon" />
        </a>
      </div>
    </div>

    <!-- Developer -->
    <div class="doc-group">
      <h3><i class="pi pi-code" /> Developer Guide</h3>
      <div class="doc-cards">
        <a
          v-for="item in developer"
          :key="item.path"
          :href="DOCS_BASE + item.path"
          target="_blank"
          rel="noopener"
          class="doc-card"
        >
          <span class="card-title">{{ item.title }}</span>
          <span class="card-desc">{{ item.desc }}</span>
          <i class="pi pi-external-link card-icon" />
        </a>
      </div>
    </div>

    <!-- Examples -->
    <div class="doc-group">
      <h3><i class="pi pi-list" /> Examples</h3>
      <div class="doc-cards">
        <a
          v-for="item in examples"
          :key="item.path"
          :href="DOCS_BASE + item.path"
          target="_blank"
          rel="noopener"
          class="doc-card"
        >
          <span class="card-title">{{ item.title }}</span>
          <span class="card-desc">{{ item.desc }}</span>
          <i class="pi pi-external-link card-icon" />
        </a>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const DOCS_BASE = "https://docs.spectrascientific.ai";

interface DocLink {
  title: string;
  desc: string;
  path: string;
}

const gettingStarted: DocLink[] = [
  { title: "Installation", desc: "Install SpectraSherpa from PyPI or source", path: "/user/installation/" },
  { title: "Quickstart", desc: "Your first spectral analysis in minutes", path: "/user/quickstart/" },
  { title: "Configuration", desc: "Environment variables and app modes", path: "/user/configuration/" },
];

const userGuide: DocLink[] = [
  { title: "Experiments", desc: "Create and manage spectral experiments", path: "/user/experiments/" },
  { title: "Workflow Builder", desc: "Build DAG-based analysis pipelines", path: "/user/workflow/" },
  { title: "DOE (96-Well)", desc: "Design of experiments with plate layouts", path: "/user/doe/" },
  { title: "Synthesis Builder", desc: "Plan and track synthesis procedures", path: "/user/synthesis/" },
  { title: "NIST Library", desc: "Search the NIST spectral reference library", path: "/user/library/" },
  { title: "User Manual", desc: "Complete reference for all features", path: "/user/manual/" },
];

const developer: DocLink[] = [
  { title: "Setup & Contributing", desc: "Dev environment, testing, and contribution guide", path: "/dev/setup/" },
  { title: "Architecture", desc: "System design, backend/frontend split, data flow", path: "/dev/architecture/" },
  { title: "Your First Node", desc: "Build a custom DAG node plugin", path: "/dev/first_plugin/" },
  { title: "Node Reference", desc: "All built-in workflow nodes and their parameters", path: "/user/reference/nodes/" },
];

const examples: DocLink[] = [
  { title: "Loading Data", desc: "Import spectra from CSV, SPA, SPG, and more", path: "/user/examples/01_loading_data/" },
  { title: "Dataset Manipulation", desc: "Slice, merge, and transform datasets", path: "/user/examples/02_dataset_manipulation/" },
  { title: "Plotting", desc: "Visualize spectra with built-in plot tools", path: "/user/examples/03_plotting/" },
  { title: "Smoothing", desc: "Savitzky-Golay and other smoothing methods", path: "/user/examples/04_preprocessing_smoothing/" },
  { title: "Baseline Correction", desc: "Remove baselines with multiple algorithms", path: "/user/examples/05_preprocessing_baseline/" },
  { title: "Peak Finding", desc: "Detect and characterize spectral peaks", path: "/user/examples/06_peak_finding/" },
  { title: "Peak Fitting", desc: "Fit peaks with Gaussian, Lorentzian models", path: "/user/examples/07_peak_fitting/" },
  { title: "PCA", desc: "Principal component analysis for spectral data", path: "/user/examples/08_pca/" },
  { title: "MCR-ALS", desc: "Multivariate curve resolution", path: "/user/examples/09_mcr_als/" },
  { title: "PLS Regression", desc: "Partial least squares for quantitative analysis", path: "/user/examples/10_pls_regression/" },
];
</script>

<style scoped>
.doc-tab {
  display: flex;
  flex-direction: column;
  gap: 28px;
  max-width: 900px;
}

.doc-group h3 {
  margin: 0 0 12px;
  font-size: 1rem;
  font-weight: 600;
  color: #1f2937;
  display: flex;
  align-items: center;
  gap: 8px;
}

.doc-group h3 i {
  font-size: 0.95rem;
  color: #6366f1;
}

.doc-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.doc-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 16px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  text-decoration: none;
  color: inherit;
  position: relative;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.doc-card:hover {
  border-color: #6366f1;
  box-shadow: 0 1px 4px rgba(99, 102, 241, 0.15);
}

.card-title {
  font-weight: 600;
  font-size: 0.9rem;
  color: #1f2937;
}

.card-desc {
  font-size: 0.8rem;
  color: #6b7280;
  line-height: 1.4;
}

.card-icon {
  position: absolute;
  top: 14px;
  right: 14px;
  font-size: 0.75rem;
  color: #9ca3af;
}

.doc-card:hover .card-icon {
  color: #6366f1;
}
</style>
