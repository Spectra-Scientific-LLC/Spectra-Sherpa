<template>
  <section class="documentation-content">
    <header class="tab-header">
      <h1>Documentation</h1>
    </header>

    <div class="doc-tab">
      <div v-for="section in sections" :key="section.title" class="doc-group">
        <h3><i :class="section.icon" /> {{ section.title }}</h3>
        <div class="doc-cards">
          <a
            v-for="item in section.items"
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
  </section>
</template>

<script setup lang="ts">
const DOCS_BASE = "https://docs.spectrascientific.ai";

interface DocLink {
  title: string;
  desc: string;
  path: string;
}

interface DocSection {
  title: string;
  icon: string;
  items: DocLink[];
}

const sections: DocSection[] = [
  {
    title: "Introduction",
    icon: "pi pi-home",
    items: [
      { title: "What SpectraSherpa Is", desc: "Product scope, scientific foundations, and first paths", path: "/" },
      { title: "Cloud vs Local OSS", desc: "Choose hosted evaluation or local compute", path: "/introduction/cloud-vs-local/" },
      { title: "Current Capabilities", desc: "What is built and supported in this release", path: "/introduction/capabilities/" },
      { title: "Supported File Types", desc: "Base readers and optional SpectroChemPy formats", path: "/introduction/file-types/" },
      { title: "License", desc: "AGPLv3.0, upstream terms, and BYOK responsibilities", path: "/introduction/license/" },
    ],
  },
  {
    title: "Onboarding",
    icon: "pi pi-compass",
    items: [
      { title: "30 Minutes to Local Compute", desc: "Install and run the OSS app locally", path: "/onboarding/local-30-minutes/" },
      { title: "Import Your First Dataset", desc: "Check files, metadata, and the data matrix", path: "/onboarding/import-first-dataset/" },
      { title: "Data Import", desc: "Move from raw files into reusable datasets", path: "/workflows/data-import/" },
      { title: "Projects, Datasets, and Runs", desc: "Understand the core analysis objects", path: "/workflows/projects-datasets-runs/" },
    ],
  },
  {
    title: "Chemometrics",
    icon: "pi pi-chart-line",
    items: [
      { title: "Overview", desc: "How to read workflows, plots, and validation outputs", path: "/chemometrics/" },
      { title: "PCA", desc: "Exploratory structure, scores, loadings, and diagnostics", path: "/chemometrics/pca/" },
      { title: "PLS Calibration", desc: "Regression, validation, and model application", path: "/chemometrics/pls/" },
      { title: "Classification", desc: "PLS-DA and KNN classifier workflows", path: "/chemometrics/classification/" },
      { title: "SIMCA QC", desc: "Class-model acceptance and rejection workflows", path: "/chemometrics/simca/" },
      { title: "MCR-ALS", desc: "Curve resolution for mixtures and evolving systems", path: "/chemometrics/mcr-als/" },
    ],
  },
  {
    title: "Node Library",
    icon: "pi pi-sitemap",
    items: [
      { title: "Node Overview", desc: "Inputs, outputs, and node contract vocabulary", path: "/nodes/" },
      { title: "Data Nodes", desc: "Source, table, and dataset-shaping nodes", path: "/nodes/data/" },
      { title: "Preprocessing Nodes", desc: "Baseline, scaling, smoothing, and transforms", path: "/nodes/preprocessing/" },
      { title: "Regression Nodes", desc: "PLS calibration and related outputs", path: "/nodes/regression/" },
      { title: "Classification Nodes", desc: "PLS-DA, SIMCA, KNN, and metrics", path: "/nodes/classification/" },
      { title: "Optional SpectroChemPy Nodes", desc: "Extra algorithms and readers enabled by [scp]", path: "/nodes/spectrochempy/" },
    ],
  },
  {
    title: "Templates",
    icon: "pi pi-list",
    items: [
      { title: "Templates", desc: "Runnable workflow starters and how to read them", path: "/workflow-templates/" },
      { title: "PCA Starter", desc: "First-look exploratory analysis", path: "/workflow-templates/pca/" },
      { title: "PLS Calibration Starter", desc: "Quantitative calibration workflow", path: "/workflow-templates/pls-calibration/" },
      { title: "Classification Starters", desc: "Categorical prediction and QC workflows", path: "/workflow-templates/classification/" },
      { title: "MCR-ALS Starter", desc: "Resolve component spectra and profiles", path: "/workflow-templates/mcr-als/" },
    ],
  },
  {
    title: "Architecture and Developers",
    icon: "pi pi-code",
    items: [
      { title: "Architecture", desc: "System overview and extension boundaries", path: "/architecture/" },
      { title: "Workflow Execution", desc: "How DAGs run and preserve provenance", path: "/architecture/workflows/" },
      { title: "Plugins and Extension Points", desc: "Build new nodes and integrations", path: "/architecture/plugins/" },
      { title: "Export Design", desc: "How workflows become portable outputs", path: "/architecture/export/" },
      { title: "Developer Setup", desc: "Environment, tests, and contribution workflow", path: "/developers/setup/" },
      { title: "Attributions", desc: "SpectroChemPy, NIST, HITRAN/HAPI, and citations", path: "/attributions/" },
    ],
  },
];
</script>

<style scoped>
.documentation-content {
  display: flex;
  flex-direction: column;
  gap: 2rem;
  padding: 0 1rem;
  color: var(--text-color);
  height: 100%;
  overflow-y: auto;
}

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
  /* Sub-section headings stay in the body-text mid-gray; the near-black
   * weight is reserved for the page title (.tab-header h1). */
  color: var(--text-color);
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
