<template>
  <div class="export-tab">
    <div v-if="!hasDataToExport" class="empty-state">
      <i class="pi pi-download" style="font-size: 3rem; color: #94a3b8"></i>
      <h3>No Data to Export</h3>
      <p>Preprocess or blend spectra to export data.</p>
    </div>

    <div v-else class="export-content">
      <!-- Left Column: Export Configuration -->
      <div class="left-column">
        <div class="tab-section">
          <h3>Data Selection</h3>
          <p class="muted-text">Choose what to export</p>

          <div class="export-option">
            <RadioButton
              v-model="exportSource"
              value="preprocessed"
              inputId="source-preprocessed"
            />
            <label for="source-preprocessed" class="option-label">
              <strong>Preprocessed Spectra</strong>
              <span class="muted-text">Export {{ preprocessedCount }} preprocessed spectra</span>
            </label>
          </div>

          <div class="export-option">
            <RadioButton
              v-model="exportSource"
              value="blended"
              inputId="source-blended"
              :disabled="!hasBlendedData"
            />
            <label for="source-blended" class="option-label">
              <strong>Blended Spectrum</strong>
              <span class="muted-text">
                {{ hasBlendedData ? "Export blended result" : "No blended data available" }}
              </span>
            </label>
          </div>
        </div>

        <div class="tab-section">
          <h3>Export Format</h3>

          <div class="export-option">
            <RadioButton
              v-model="exportFormat"
              value="csv"
              inputId="format-csv"
            />
            <label for="format-csv" class="option-label">
              <strong>CSV (Comma-Separated Values)</strong>
              <span class="muted-text">Wavenumber and absorbance columns</span>
            </label>
          </div>

          <div class="export-option">
            <RadioButton
              v-model="exportFormat"
              value="json"
              inputId="format-json"
            />
            <label for="format-json" class="option-label">
              <strong>JSON (JavaScript Object Notation)</strong>
              <span class="muted-text">Structured data with metadata</span>
            </label>
          </div>

          <div class="export-option">
            <RadioButton
              v-model="exportFormat"
              value="nddataset"
              inputId="format-nddataset"
            />
            <label for="format-nddataset" class="option-label">
              <strong>NDDataset (SpectroChemPy)</strong>
              <span class="muted-text">JSON format for SpectroChemPy library</span>
            </label>
          </div>

          <div class="export-option">
            <RadioButton
              v-model="exportFormat"
              value="zip"
              inputId="format-zip"
            />
            <label for="format-zip" class="option-label">
              <strong>ZIP Archive</strong>
              <span class="muted-text">All files with metadata</span>
            </label>
          </div>
        </div>

        <div class="tab-section">
          <h3>Export Options</h3>

          <div class="checkbox-option">
            <Checkbox
              v-model="includeMetadata"
              inputId="opt-metadata"
              :binary="true"
            />
            <label for="opt-metadata">Include metadata (preprocessing settings, blend parameters)</label>
          </div>

          <div class="checkbox-option">
            <Checkbox
              v-model="includeConcentrations"
              inputId="opt-concentrations"
              :binary="true"
              :disabled="exportSource !== 'blended'"
            />
            <label for="opt-concentrations">Include concentration data (blended only)</label>
          </div>

          <div class="checkbox-option">
            <Checkbox
              v-model="includeTimestamp"
              inputId="opt-timestamp"
              :binary="true"
            />
            <label for="opt-timestamp">Add timestamp to filename</label>
          </div>

          <div class="field">
            <label>Custom Filename (optional)</label>
            <InputText
              v-model="customFilename"
              placeholder="Leave empty for auto-generated name"
            />
          </div>

          <Button
            label="Export Data"
            icon="pi pi-download"
            class="export-button"
            :loading="exporting"
            @click="exportData"
          />
        </div>
      </div>

      <!-- Right Column: Export Preview -->
      <div class="right-column">
        <div class="tab-section">
          <h3>Export Preview</h3>
          <p class="muted-text">Preview of export structure</p>

          <div class="preview-content">
            <div class="preview-section">
              <h4>
                <i class="pi pi-file"></i>
                Filename
              </h4>
              <code>{{ previewFilename }}</code>
            </div>

            <div class="preview-section">
              <h4>
                <i class="pi pi-database"></i>
                Contents
              </h4>
              <ul class="preview-list">
                <li v-if="exportSource === 'preprocessed'">
                  {{ preprocessedCount }} preprocessed spectra
                </li>
                <li v-if="exportSource === 'blended'">
                  Blended spectrum ({{ blendedDataPoints }} points)
                </li>
                <li v-if="includeMetadata">Metadata and settings</li>
                <li v-if="includeConcentrations && exportSource === 'blended'">
                  Concentration timeseries
                </li>
              </ul>
            </div>

            <div v-if="exportFormat === 'csv'" class="preview-section">
              <h4>
                <i class="pi pi-list"></i>
                CSV Structure
              </h4>
              <pre class="preview-code">wavenumber,absorbance
{{ csvPreview }}</pre>
            </div>

            <div v-if="exportFormat === 'json'" class="preview-section">
              <h4>
                <i class="pi pi-code"></i>
                JSON Structure
              </h4>
              <pre class="preview-code">{{ jsonPreview }}</pre>
            </div>

            <div v-if="exportFormat === 'nddataset'" class="preview-section">
              <h4>
                <i class="pi pi-th-large"></i>
                NDDataset Info
              </h4>
              <div class="info-grid">
                <div class="info-item">
                  <label>Shape:</label>
                  <span>{{ nddatasetShape }}</span>
                </div>
                <div class="info-item">
                  <label>X-axis:</label>
                  <span>Wavenumber (cm⁻¹)</span>
                </div>
                <div class="info-item">
                  <label>Y-axis:</label>
                  <span>Absorbance (a.u.)</span>
                </div>
              </div>
            </div>

            <div v-if="exportFormat === 'zip'" class="preview-section">
              <h4>
                <i class="pi pi-folder-open"></i>
                Archive Contents
              </h4>
              <ul class="preview-list">
                <li>spectra.csv - Spectral data</li>
                <li v-if="includeMetadata">metadata.json - Settings and parameters</li>
                <li v-if="includeConcentrations && exportSource === 'blended'">
                  concentrations.csv - Concentration data
                </li>
                <li>README.txt - Export information</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import InputText from "primevue/inputtext";
import RadioButton from "primevue/radiobutton";
import { useToast } from "primevue/usetoast";
import { useBuilderStore } from "@/stores/builder";
import { downloadCsv, downloadJson } from "@/utils/download";

const builderStore = useBuilderStore();
const toast = useToast();

// Export configuration
const exportSource = ref<"preprocessed" | "blended">("preprocessed");
const exportFormat = ref<"csv" | "json" | "nddataset" | "zip">("csv");
const includeMetadata = ref(true);
const includeConcentrations = ref(false);
const includeTimestamp = ref(true);
const customFilename = ref("");
const exporting = ref(false);

const hasDataToExport = computed(() => {
  return builderStore.spectra.length > 0 || builderStore.blendResult;
});

const hasBlendedData = computed(() => {
  return builderStore.blendResult !== null;
});

const preprocessedCount = computed(() => {
  return builderStore.spectra.length;
});

const blendedDataPoints = computed(() => {
  if (!builderStore.blendResult) return 0;
  return builderStore.blendResult.wavenumbers.length;
});

const previewFilename = computed(() => {
  const timestamp = includeTimestamp.value
    ? `_${new Date().toISOString().split("T")[0]}`
    : "";
  const custom = customFilename.value || "spectra_export";
  const ext = exportFormat.value === "zip" ? "zip" : exportFormat.value;
  return `${custom}${timestamp}.${ext}`;
});

const csvPreview = computed(() => {
  if (exportSource.value === "preprocessed" && builderStore.spectra.length > 0) {
    const first = builderStore.spectra[0];
    return `${first.wavenumber[0].toFixed(2)},${first.absorbance[0].toFixed(6)}\n...`;
  } else if (exportSource.value === "blended" && builderStore.blendResult) {
    const wn = builderStore.blendResult.wavenumbers[0];
    const abs = builderStore.blendResult.absorbance_matrix[0][0];
    return `${wn.toFixed(2)},${abs.toFixed(6)}\n...`;
  }
  return "...";
});

const jsonPreview = computed(() => {
  const preview = {
    format: "Spectra Builder Export",
    version: "1.0",
    timestamp: new Date().toISOString(),
    data_type: exportSource.value,
    spectra_count: exportSource.value === "preprocessed" ? preprocessedCount.value : 1,
  };
  return JSON.stringify(preview, null, 2);
});

const nddatasetShape = computed(() => {
  if (exportSource.value === "preprocessed" && builderStore.spectra.length > 0) {
    const first = builderStore.spectra[0];
    return `(${first.wavenumber.length}, ${preprocessedCount.value})`;
  } else if (exportSource.value === "blended" && builderStore.blendResult) {
    const wn_len = builderStore.blendResult.wavenumbers.length;
    const time_len = builderStore.blendResult.times.length;
    return `(${wn_len}, ${time_len})`;
  }
  return "(0, 0)";
});

const exportData = async () => {
  exporting.value = true;

  try {
    if (exportFormat.value === "csv") {
      exportAsCsv();
    } else if (exportFormat.value === "json") {
      exportAsJson();
    } else if (exportFormat.value === "nddataset") {
      exportAsNDDataset();
    } else if (exportFormat.value === "zip") {
      exportAsZip();
    }

    toast.add({
      severity: "success",
      summary: "Export Complete",
      detail: `Data exported as ${exportFormat.value.toUpperCase()}`,
      life: 3000,
    });
  } catch (error: any) {
    console.error("Export failed:", error);
    toast.add({
      severity: "error",
      summary: "Export Failed",
      detail: error.message || "Unable to export data",
      life: 3000,
    });
  } finally {
    exporting.value = false;
  }
};

const exportAsCsv = () => {
  if (exportSource.value === "preprocessed") {
    // Export all preprocessed spectra as separate columns
    const wavenumbers = builderStore.spectra[0].wavenumber;
    const headers = ["wavenumber", ...builderStore.spectra.map((s) => s.label)];
    const rows = wavenumbers.map((wn, i) => {
      const absorbances = builderStore.spectra.map((s) => s.absorbance[i]);
      return [wn, ...absorbances];
    });

    downloadCsv([headers, ...rows], previewFilename.value);
  } else if (exportSource.value === "blended" && builderStore.blendResult) {
    // Export blended spectrum
    const { wavenumbers, absorbance_matrix } = builderStore.blendResult;
    const headers = ["wavenumber", ...absorbance_matrix[0].map((_, i) => `t${i}`)];
    const rows = wavenumbers.map((wn, i) => {
      return [wn, ...absorbance_matrix[i]];
    });

    downloadCsv([headers, ...rows], previewFilename.value);
  }
};

const exportAsJson = () => {
  const exportData: any = {
    format: "Spectra Builder Export",
    version: "1.0",
    timestamp: new Date().toISOString(),
    data_type: exportSource.value,
  };

  if (exportSource.value === "preprocessed") {
    exportData.spectra = builderStore.spectra.map((s) => ({
      label: s.label,
      wavenumber: s.wavenumber,
      absorbance: s.absorbance,
      source: s.source,
    }));
  } else if (exportSource.value === "blended" && builderStore.blendResult) {
    exportData.blended_spectrum = builderStore.blendResult;
    if (includeConcentrations.value && builderStore.blendConcentrations) {
      exportData.concentrations = builderStore.blendConcentrations;
    }
  }

  if (includeMetadata.value) {
    exportData.preprocessing_settings = builderStore.settings;
    if (exportSource.value === "blended" && builderStore.blendSettings) {
      exportData.blend_settings = builderStore.blendSettings;
    }
  }

  downloadJson(exportData, previewFilename.value);
};

const exportAsNDDataset = () => {
  // Export in SpectroChemPy NDDataset format
  const nddataset: any = {
    _implements: "NDDataset",
    _api_version: "0.6",
  };

  if (exportSource.value === "preprocessed") {
    const wavenumbers = builderStore.spectra[0].wavenumber;
    const absorbances = builderStore.spectra.map((s) => s.absorbance);

    nddataset.data = absorbances;
    nddataset.dims = ["y", "x"];
    nddataset.coordset = {
      x: {
        _implements: "Coord",
        data: wavenumbers,
        labels: null,
        title: "Wavenumber",
        units: "cm^-1",
      },
      y: {
        _implements: "Coord",
        data: builderStore.spectra.map((s) => s.label),
        labels: null,
        title: "Spectrum",
        units: null,
      },
    };
  } else if (exportSource.value === "blended" && builderStore.blendResult) {
    nddataset.data = builderStore.blendResult.absorbance_matrix;
    nddataset.dims = ["y", "x"];
    nddataset.coordset = {
      x: {
        _implements: "Coord",
        data: builderStore.blendResult.times,
        labels: null,
        title: builderStore.blendMetadata?.x_label || "Time",
        units: builderStore.blendMetadata?.x_unit || "s",
      },
      y: {
        _implements: "Coord",
        data: builderStore.blendResult.wavenumbers,
        labels: null,
        title: "Wavenumber",
        units: "cm^-1",
      },
    };
  }

  if (includeMetadata.value) {
    nddataset.meta = {
      preprocessing_settings: builderStore.settings,
      blend_settings: builderStore.blendSettings,
      export_timestamp: new Date().toISOString(),
    };
  }

  downloadJson(nddataset, previewFilename.value);
};

const exportAsZip = () => {
  // For now, just export as JSON with a note
  toast.add({
    severity: "info",
    summary: "ZIP Export",
    detail: "ZIP export is not yet implemented - exporting as JSON instead",
    life: 4000,
  });
  exportAsJson();
};
</script>

<style scoped>
.export-tab {
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

.export-content {
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

.tab-section h3 {
  margin: 0 0 8px;
  font-size: 1rem;
  font-weight: 600;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
}

.export-option {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px;
  margin-bottom: 8px;
  background: #f8fafc;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
}

.export-option:hover {
  background: #f1f5f9;
}

.option-label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  cursor: pointer;
}

.option-label strong {
  color: #1e293b;
  font-size: 0.95rem;
}

.checkbox-option {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
}

.checkbox-option label {
  color: #334155;
  font-size: 0.9rem;
  cursor: pointer;
}

.field {
  margin-top: 16px;
}

.field label {
  display: block;
  font-weight: 500;
  font-size: 0.9rem;
  color: #334155;
  margin-bottom: 6px;
}

.export-button {
  width: 100%;
  margin-top: 16px;
}

.muted-text {
  color: #64748b;
  font-size: 0.85rem;
}

.preview-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 16px;
}

.preview-section {
  padding: 16px;
  background: #f8fafc;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.preview-section h4 {
  margin: 0 0 12px;
  font-size: 0.95rem;
  font-weight: 600;
  color: #475569;
  display: flex;
  align-items: center;
  gap: 8px;
}

.preview-section code {
  display: block;
  padding: 8px 12px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  font-family: "Courier New", monospace;
  font-size: 0.9rem;
  color: #1e293b;
}

.preview-code {
  padding: 12px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  font-family: "Courier New", monospace;
  font-size: 0.85rem;
  color: #1e293b;
  overflow-x: auto;
  white-space: pre;
}

.preview-list {
  margin: 0;
  padding-left: 20px;
}

.preview-list li {
  margin-bottom: 6px;
  color: #475569;
  font-size: 0.9rem;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-item label {
  font-size: 0.85rem;
  color: #64748b;
  font-weight: 500;
}

.info-item span {
  font-size: 0.95rem;
  color: #1e293b;
  font-weight: 600;
}

@media (max-width: 1200px) {
  .export-content {
    grid-template-columns: 1fr;
  }
}
</style>
