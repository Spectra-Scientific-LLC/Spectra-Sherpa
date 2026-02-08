<template>
  <section class="templates-content">
    <div class="section-header">
      <div>
        <h1>Workflow Templates</h1>
        <p class="section-subtitle">
          Pre-built workflows based on SpectrochemPy analysis examples
        </p>
      </div>
    </div>

    <!-- Featured Projects Section -->
    <div class="template-section">
      <h2 class="section-title">Featured Workflows</h2>
      <div class="templates-grid">
        <!-- Project 1: Calibration Workflow -->
        <div class="template-card featured">
          <div class="template-badge">Calibration</div>
          <div class="template-header">
            <div class="template-icon">
              <i class="pi pi-chart-line"></i>
            </div>
            <div class="template-title">
              <h3>Absorption Calibration</h3>
              <p class="template-status">Ready to use</p>
            </div>
          </div>
          <p class="template-description">
            Build wavenumber-specific absorption vs. concentration calibration models
            using PLS regression with cross-validation.
          </p>
          <div class="template-steps">
            <h4>Workflow Steps</h4>
            <ol>
              <li>Load OPUS/CSV experimental spectra</li>
              <li>Load reference library spectra (JDX)</li>
              <li>Apply ASLS baseline correction</li>
              <li>SNV normalization</li>
              <li>PLS model with 10-fold CV</li>
              <li>Export calibration model</li>
            </ol>
          </div>
          <div class="template-actions">
            <Button
              label="Open in Builder"
              icon="pi pi-external-link"
              class="p-button-primary"
              @click="openTemplate('project1')"
            />
          </div>
        </div>

        <!-- Project 2: MCR Workflow -->
        <div class="template-card featured">
          <div class="template-badge">MCR-ALS</div>
          <div class="template-header">
            <div class="template-icon">
              <i class="pi pi-share-alt"></i>
            </div>
            <div class="template-title">
              <h3>MCR-ALS with Kinetics</h3>
              <p class="template-status">Ready to use</p>
            </div>
          </div>
          <p class="template-description">
            Multivariate Curve Resolution with kinetic constraints for time-resolved
            spectroscopy and reaction mechanism analysis.
          </p>
          <div class="template-steps">
            <h4>Workflow Steps</h4>
            <ol>
              <li>Load time-series spectra</li>
              <li>Apply ASLS baseline + smoothing</li>
              <li>Configure non-negativity & closure</li>
              <li>Run MCR-ALS optimization</li>
              <li>Plot concentrations & pure spectra</li>
              <li>Export results to CSV</li>
            </ol>
          </div>
          <div class="template-actions">
            <Button
              label="Open in Builder"
              icon="pi pi-external-link"
              class="p-button-primary"
              @click="openTemplate('project2')"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- SpectrochemPy Examples Section -->
    <div class="template-section">
      <h2 class="section-title">SpectrochemPy Examples</h2>
      <div class="templates-grid">
        <!-- IR OPUS Analysis -->
        <div class="template-card">
          <div class="template-badge ir">IR</div>
          <div class="template-header">
            <div class="template-icon ir">
              <i class="pi pi-file-import"></i>
            </div>
            <div class="template-title">
              <h3>IR OPUS Import & Analysis</h3>
              <p class="template-status">Spectroscopy</p>
            </div>
          </div>
          <p class="template-description">
            Import Bruker OPUS files, slice wavenumber range, apply rubberband baseline,
            normalize, and detect peaks.
          </p>
          <div class="template-actions">
            <Button
              label="Open in Builder"
              icon="pi pi-external-link"
              class="p-button-secondary"
              @click="openTemplate('ir_opus_analysis')"
            />
          </div>
        </div>

        <!-- Raman Processing -->
        <div class="template-card">
          <div class="template-badge raman">Raman</div>
          <div class="template-header">
            <div class="template-icon raman">
              <i class="pi pi-sun"></i>
            </div>
            <div class="template-title">
              <h3>Raman Processing Pipeline</h3>
              <p class="template-status">Spectroscopy</p>
            </div>
          </div>
          <p class="template-description">
            Cosmic ray removal, fluorescence baseline correction, Whittaker smoothing,
            and intensity normalization.
          </p>
          <div class="template-actions">
            <Button
              label="Open in Builder"
              icon="pi pi-external-link"
              class="p-button-secondary"
              @click="openTemplate('raman_processing')"
            />
          </div>
        </div>

        <!-- NMR Processing -->
        <div class="template-card">
          <div class="template-badge nmr">NMR</div>
          <div class="template-header">
            <div class="template-icon nmr">
              <i class="pi pi-wave-pulse"></i>
            </div>
            <div class="template-title">
              <h3>NMR Processing Workflow</h3>
              <p class="template-status">Spectroscopy</p>
            </div>
          </div>
          <p class="template-description">
            Phase correction, polynomial baseline, ppm slicing, CWT peak picking,
            and Lorentzian peak fitting.
          </p>
          <div class="template-actions">
            <Button
              label="Open in Builder"
              icon="pi pi-external-link"
              class="p-button-secondary"
              @click="openTemplate('nmr_processing')"
            />
          </div>
        </div>

        <!-- PLS Regression -->
        <div class="template-card">
          <div class="template-badge chemometrics">PLS</div>
          <div class="template-header">
            <div class="template-icon chemometrics">
              <i class="pi pi-chart-scatter"></i>
            </div>
            <div class="template-title">
              <h3>PLS Regression Analysis</h3>
              <p class="template-status">Chemometrics</p>
            </div>
          </div>
          <p class="template-description">
            Partial Least Squares regression with cross-validation, RMSECV plots,
            and predicted vs. actual visualization.
          </p>
          <div class="template-actions">
            <Button
              label="Open in Builder"
              icon="pi pi-external-link"
              class="p-button-secondary"
              @click="openTemplate('pls_regression')"
            />
          </div>
        </div>

        <!-- EFA Analysis -->
        <div class="template-card">
          <div class="template-badge chemometrics">EFA</div>
          <div class="template-header">
            <div class="template-icon chemometrics">
              <i class="pi pi-sort-amount-up"></i>
            </div>
            <div class="template-title">
              <h3>Evolving Factor Analysis</h3>
              <p class="template-status">Chemometrics</p>
            </div>
          </div>
          <p class="template-description">
            Determine component rank in evolving mixtures with forward/backward EFA
            and eigenvalue plots.
          </p>
          <div class="template-actions">
            <Button
              label="Open in Builder"
              icon="pi pi-external-link"
              class="p-button-secondary"
              @click="openTemplate('efa_analysis')"
            />
          </div>
        </div>

        <!-- IRIS Decomposition -->
        <div class="template-card">
          <div class="template-badge chemometrics">IRIS</div>
          <div class="template-header">
            <div class="template-icon chemometrics">
              <i class="pi pi-sliders-h"></i>
            </div>
            <div class="template-title">
              <h3>IRIS Decomposition</h3>
              <p class="template-status">Chemometrics</p>
            </div>
          </div>
          <p class="template-description">
            Integral Regularized Inversion of Spectra for relaxation time distribution
            analysis with Tikhonov regularization.
          </p>
          <div class="template-actions">
            <Button
              label="Open in Builder"
              icon="pi pi-external-link"
              class="p-button-secondary"
              @click="openTemplate('iris_decomposition')"
            />
          </div>
        </div>

        <!-- SIMPLISMA -->
        <div class="template-card">
          <div class="template-badge chemometrics">SIMPLISMA</div>
          <div class="template-header">
            <div class="template-icon chemometrics">
              <i class="pi pi-sitemap"></i>
            </div>
            <div class="template-title">
              <h3>SIMPLISMA Pure Variables</h3>
              <p class="template-status">Chemometrics</p>
            </div>
          </div>
          <p class="template-description">
            Self-modeling mixture analysis for initial pure component estimates
            with purity plots.
          </p>
          <div class="template-actions">
            <Button
              label="Open in Builder"
              icon="pi pi-external-link"
              class="p-button-secondary"
              @click="openTemplate('simplisma')"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- Basic Templates Section -->
    <div class="template-section">
      <h2 class="section-title">Basic Templates</h2>
      <div class="templates-grid">
        <div class="template-card">
          <div class="template-badge secondary">Basic</div>
          <div class="template-header">
            <div class="template-icon secondary">
              <i class="pi pi-filter"></i>
            </div>
            <div class="template-title">
              <h3>Standard Preprocessing</h3>
              <p class="template-status">Template</p>
            </div>
          </div>
          <p class="template-description">
            Basic preprocessing pipeline: ASLS baseline, Savitzky-Golay smoothing,
            SNV normalization.
          </p>
          <div class="template-actions">
            <Button
              label="Open in Builder"
              icon="pi pi-external-link"
              class="p-button-secondary"
              @click="openTemplate('preprocessing')"
            />
          </div>
        </div>

        <div class="template-card">
          <div class="template-badge secondary">Basic</div>
          <div class="template-header">
            <div class="template-icon secondary">
              <i class="pi pi-th-large"></i>
            </div>
            <div class="template-title">
              <h3>PCA Exploration</h3>
              <p class="template-status">Template</p>
            </div>
          </div>
          <p class="template-description">
            Exploratory PCA with scores, loadings, scree plots, and outlier detection
            (Hotelling T², Q residuals).
          </p>
          <div class="template-actions">
            <Button
              label="Open in Builder"
              icon="pi pi-external-link"
              class="p-button-secondary"
              @click="openTemplate('pca')"
            />
          </div>
        </div>

        <div class="template-card">
          <div class="template-badge secondary">Basic</div>
          <div class="template-header">
            <div class="template-icon secondary">
              <i class="pi pi-search"></i>
            </div>
            <div class="template-title">
              <h3>Peak Detection & Fitting</h3>
              <p class="template-status">Template</p>
            </div>
          </div>
          <p class="template-description">
            Automated peak detection with Gaussian/Lorentzian fitting, FWHM,
            and area quantification.
          </p>
          <div class="template-actions">
            <Button
              label="Open in Builder"
              icon="pi pi-external-link"
              class="p-button-secondary"
              @click="openTemplate('peaks')"
            />
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { useRouter } from "vue-router";
import Button from "primevue/button";
import { useToast } from "primevue/usetoast";
import { useWorkflowStore } from "@/stores/workflow";

const router = useRouter();
const toast = useToast();
const workflowStore = useWorkflowStore();

const openTemplate = (templateId: string) => {
  const success = workflowStore.loadTemplate(templateId);

  if (success) {
    toast.add({
      severity: "success",
      summary: "Template Loaded",
      detail: `Loaded "${workflowStore.workflowName}" into Builder`,
      life: 2000,
    });
    router.push("/workflows/builder");
  } else {
    toast.add({
      severity: "error",
      summary: "Template Not Found",
      detail: `Could not find template: ${templateId}`,
      life: 3000,
    });
  }
};
</script>

<style scoped>
.templates-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 8px;
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

.template-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  color: #334155;
  padding-bottom: 8px;
  border-bottom: 1px solid #e2e8f0;
}

.templates-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 20px;
}

.template-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.template-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.template-card.featured {
  border-color: #3b82f6;
  background: linear-gradient(to bottom right, #ffffff, #eff6ff);
}

/* Badge styles */
.template-badge {
  display: inline-block;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 4px 10px;
  border-radius: 4px;
  background: #dbeafe;
  color: #1d4ed8;
  width: fit-content;
}

.template-badge.secondary {
  background: #f1f5f9;
  color: #64748b;
}

.template-badge.ir {
  background: #fef3c7;
  color: #92400e;
}

.template-badge.raman {
  background: #dcfce7;
  color: #166534;
}

.template-badge.nmr {
  background: #fce7f3;
  color: #9d174d;
}

.template-badge.chemometrics {
  background: #ede9fe;
  color: #5b21b6;
}

.template-header {
  display: flex;
  align-items: center;
  gap: 16px;
}

/* Icon styles */
.template-icon {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #eff6ff;
  border-radius: 12px;
  flex-shrink: 0;
}

.template-icon i {
  font-size: 1.75rem;
  color: #3b82f6;
}

.template-icon.secondary {
  background: #f1f5f9;
}

.template-icon.secondary i {
  color: #64748b;
}

.template-icon.ir {
  background: #fef3c7;
}

.template-icon.ir i {
  color: #d97706;
}

.template-icon.raman {
  background: #dcfce7;
}

.template-icon.raman i {
  color: #16a34a;
}

.template-icon.nmr {
  background: #fce7f3;
}

.template-icon.nmr i {
  color: #db2777;
}

.template-icon.chemometrics {
  background: #ede9fe;
}

.template-icon.chemometrics i {
  color: #7c3aed;
}

.template-title h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
}

.template-status {
  margin: 4px 0 0;
  font-size: 0.8rem;
  color: #10b981;
  font-weight: 500;
}

.template-description {
  margin: 0;
  color: #64748b;
  font-size: 0.9rem;
  line-height: 1.5;
}

.template-steps {
  background: #f8fafc;
  border-radius: 8px;
  padding: 16px;
}

.template-steps h4 {
  margin: 0 0 12px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #334155;
}

.template-steps ol {
  margin: 0;
  padding-left: 20px;
}

.template-steps li {
  font-size: 0.85rem;
  color: #64748b;
  margin-bottom: 6px;
  line-height: 1.4;
}

.template-steps li:last-child {
  margin-bottom: 0;
}

.template-actions {
  display: flex;
  gap: 12px;
  margin-top: auto;
  padding-top: 8px;
}

@media (max-width: 768px) {
  .templates-grid {
    grid-template-columns: 1fr;
  }
}
</style>
