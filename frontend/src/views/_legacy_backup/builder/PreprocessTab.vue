<template>
  <div class="preprocess-tab">
    <div class="preprocess-grid">
      <!-- Left: Data Source & Settings -->
      <div class="left-column">
        <div class="tab-section">
          <h3>Data Source</h3>

          <div class="field">
            <label>Experiment</label>
            <Dropdown
              v-model="selectedExperiment"
              :options="experimentStore.experiments"
              optionLabel="name"
              placeholder="Select experiment"
              @change="onExperimentChange"
            />
          </div>

          <div v-if="experimentStore.files.length" class="field">
            <label>Experiment Files</label>
            <MultiSelect
              v-model="selectedExperimentFiles"
              :options="experimentStore.files"
              optionLabel="file_path"
              display="chip"
              placeholder="Select files"
            />
          </div>

          <div v-if="builderStore.libraryEntries.length" class="field">
            <label>Library Entries ({{ builderStore.libraryEntries.length }})</label>
            <div class="library-list">
              <div v-for="entry in builderStore.libraryEntries" :key="entry.id" class="library-item">
                <span>{{ entry.compound_name }}</span>
                <Button
                  icon="pi pi-times"
                  class="p-button-text p-button-sm p-button-danger"
                  @click="builderStore.removeLibraryEntry(entry.id)"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- File Info Preview -->
        <div v-if="builderStore.fileInfo || builderStore.fileInfoLoading" class="tab-section file-info-section">
          <h3>File Info</h3>
          <div v-if="builderStore.fileInfoLoading" class="loading-info">
            <i class="pi pi-spin pi-spinner"></i> Loading file info...
          </div>
          <div v-else-if="builderStore.fileInfo" class="file-info-grid">
            <div class="info-row">
              <span class="info-label">Spectra</span>
              <span class="info-value">{{ builderStore.fileInfo.num_spectra }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">Points</span>
              <span class="info-value">{{ builderStore.fileInfo.num_wavenumbers }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">WN Range</span>
              <span class="info-value">
                {{ builderStore.fileInfo.wavenumber_min?.toFixed(1) }} - {{ builderStore.fileInfo.wavenumber_max?.toFixed(1) }}
              </span>
            </div>
            <div class="info-row">
              <span class="info-label">Abs Range</span>
              <span class="info-value">
                {{ builderStore.fileInfo.absorbance_min?.toFixed(3) }} - {{ builderStore.fileInfo.absorbance_max?.toFixed(3) }}
              </span>
            </div>
            <div class="info-row">
              <span class="info-label">Source</span>
              <span class="info-value">{{ builderStore.fileInfo.source }}</span>
            </div>
            <div v-if="isWavenumberRangeWarning" class="range-warning">
              <i class="pi pi-exclamation-triangle"></i>
              WN range ({{ builderStore.fileInfo.wavenumber_min?.toFixed(0) }}-{{ builderStore.fileInfo.wavenumber_max?.toFixed(0) }})
              is outside filter range ({{ builderStore.settings.min_wavenumber }}-{{ builderStore.settings.max_wavenumber }}).
              <strong>Disable "Apply Range Limit"</strong> or adjust range.
            </div>
          </div>
        </div>

        <div class="tab-section">
          <h3>Preprocessing Settings</h3>

          <div class="field">
            <label>Alignment Method</label>
            <Dropdown
              v-model="builderStore.settings.wavenumber_alignment_method"
              :options="alignmentOptions"
            />
          </div>

          <!-- Filter Direction for 2D data -->
          <div v-if="is2DData" class="field">
            <label>Filter Direction</label>
            <Dropdown
              v-model="filterDirection"
              :options="filterDirectionOptions"
              optionLabel="label"
              optionValue="value"
            />
            <small class="field-hint">
              Apply smoothing/filtering along {{ filterDirection === 'wavenumber' ? 'spectral' : 'temporal' }} axis
            </small>
          </div>

          <div class="field">
            <div class="checkbox-field">
              <InputSwitch v-model="builderStore.settings.apply_range_limit" />
              <label>Apply Range Limit</label>
            </div>
            <div v-if="builderStore.settings.apply_range_limit" class="range-inputs">
              <InputNumber v-model="builderStore.settings.min_wavenumber" placeholder="Min cm⁻¹" />
              <InputNumber v-model="builderStore.settings.max_wavenumber" placeholder="Max cm⁻¹" />
            </div>
          </div>

          <div class="field">
            <div class="checkbox-field">
              <InputSwitch v-model="builderStore.settings.apply_cosmic_ray_removal" />
              <label>Cosmic Ray Removal</label>
            </div>
          </div>

          <div class="field">
            <div class="checkbox-field">
              <InputSwitch v-model="builderStore.settings.apply_savgol" />
              <label>Savitzky-Golay Smoothing</label>
            </div>
          </div>

          <div class="field">
            <div class="checkbox-field">
              <InputSwitch v-model="builderStore.settings.apply_clip_floor" />
              <label>Clip Floor</label>
            </div>
            <InputNumber
              v-if="builderStore.settings.apply_clip_floor"
              v-model="builderStore.settings.clip_floor"
              placeholder="Floor value"
            />
          </div>

          <Button
            label="Run Preprocessing"
            icon="pi pi-cog"
            class="preprocess-button"
            :loading="builderStore.loading"
            :disabled="!hasDataSelected"
            @click="runPreprocess"
          />
        </div>

        <!-- Slice info panel for 2D data -->
        <div v-if="is2DData && selectedTimeIndex >= 0" class="tab-section slice-info">
          <h3>Selected Point</h3>
          <div class="info-grid">
            <div class="info-item">
              <span class="info-label">Time Index</span>
              <span class="info-value">{{ selectedTimeIndex + 1 }} / {{ spectra2D.nTime }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">Wavenumber</span>
              <span class="info-value">{{ selectedWavenumber.toFixed(1) }} cm⁻¹</span>
            </div>
            <div class="info-item">
              <span class="info-label">Absorbance</span>
              <span class="info-value">{{ selectedAbsorbance.toFixed(4) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Plot(s) -->
      <div class="right-column">
        <!-- 1D Data: Simple line plot -->
        <template v-if="!is2DData">
          <div class="tab-section plot-section">
            <h3>Preprocessed Spectra</h3>

            <div v-if="builderStore.plotTraces.length === 0" class="empty-plot">
              <i class="pi pi-chart-line" style="font-size: 2.5rem; color: #cbd5e1"></i>
              <p>Select data and run preprocessing to view spectra</p>
            </div>

            <PlotlyChart v-else :data="builderStore.plotTraces" :layout="plotLayout1D" />
          </div>
        </template>

        <!-- 2D Data: Contour + slices -->
        <template v-else>
          <!-- Main contour/heatmap -->
          <div class="tab-section plot-section-contour">
            <h3>Time-Resolved Spectra ({{ spectra2D.nTime }} spectra x {{ spectra2D.nWavenumber }} points)</h3>
            <PlotlyChart
              :data="contourData"
              :layout="contourLayout"
              @click="onContourClick"
            />
          </div>

          <!-- Slice plots side by side -->
          <div class="slice-plots-row">
            <!-- Time slice: spectrum at selected time -->
            <div class="tab-section slice-plot">
              <h3>Spectrum at Time {{ selectedTimeIndex + 1 }}</h3>
              <PlotlyChart :data="timeSliceData" :layout="timeSliceLayout" />
            </div>

            <!-- Spectral slice: profile at selected wavenumber -->
            <div class="tab-section slice-plot">
              <h3>Profile at {{ selectedWavenumber.toFixed(1) }} cm⁻¹</h3>
              <PlotlyChart :data="spectralSliceData" :layout="spectralSliceLayout" />
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import Button from "primevue/button";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import InputSwitch from "primevue/inputswitch";
import MultiSelect from "primevue/multiselect";
import { useToast } from "primevue/usetoast";
import { useExperimentStore } from "@/stores/experiment";
import { useBuilderStore } from "@/stores/builder";
import PlotlyChart from "@/components/PlotlyChart.vue";

const experimentStore = useExperimentStore();
const builderStore = useBuilderStore();
const toast = useToast();

const selectedExperiment = ref<any>(null);
const selectedExperimentFiles = ref<any[]>([]);
const alignmentOptions = ["none", "pchip", "linear", "sinc"];
const filterDirectionOptions = [
  { label: "Wavenumber (spectral)", value: "wavenumber" },
  { label: "Time (temporal)", value: "time" },
];
const filterDirection = ref("wavenumber");

// Check if the wavenumber range in file info is outside the filter range
const isWavenumberRangeWarning = computed(() => {
  if (!builderStore.fileInfo || !builderStore.settings.apply_range_limit) return false;
  const { wavenumber_min, wavenumber_max } = builderStore.fileInfo;
  const { min_wavenumber, max_wavenumber } = builderStore.settings;
  if (wavenumber_min == null || wavenumber_max == null) return false;
  if (min_wavenumber == null || max_wavenumber == null) return false;
  // Warning if file range doesn't overlap with filter range
  return wavenumber_max < min_wavenumber || wavenumber_min > max_wavenumber;
});

// Fetch file info when file selection changes
watch(selectedExperimentFiles, async (files) => {
  if (files.length === 1 && selectedExperiment.value) {
    const expId = String(selectedExperiment.value.id).padStart(3, "0");
    const filePath = `experiments/exp_${expId}/${files[0].file_path}`;
    try {
      await builderStore.fetchFileInfo(filePath);
    } catch {
      // Silently fail - file info is optional
    }
  } else {
    builderStore.clearFileInfo();
  }
});

// 2D visualization state
const selectedTimeIndex = ref(0);
const selectedWavenumberIndex = ref(0);

// Check if data is 2D (multiple spectra with same wavenumber axis)
const is2DData = computed(() => {
  const spectra = builderStore.spectra;
  // Need at least 2 spectra for 2D view
  if (!spectra || spectra.length < 2) return false;

  // Check if all spectra have the same wavenumber length
  const firstLen = spectra[0]?.wavenumber?.length ?? 0;
  if (firstLen === 0) return false;

  // Check all spectra have matching wavenumber length
  const allSameLength = spectra.every((s) => {
    const len = s?.wavenumber?.length ?? 0;
    return len === firstLen;
  });

  // Consider it 2D if we have multiple spectra with same wavenumber grid
  // (e.g., time-resolved data from MAT files)
  return allSameLength && spectra.length >= 2;
});

// Build 2D data structure for contour plot
const spectra2D = computed(() => {
  const spectra = builderStore.spectra;
  if (!is2DData.value || spectra.length === 0) {
    return { wavenumbers: [], timeIndices: [], matrix: [], nTime: 0, nWavenumber: 0 };
  }

  const wavenumbers = spectra[0].wavenumber || [];
  const nTime = spectra.length;
  const nWavenumber = wavenumbers.length;
  const timeIndices = Array.from({ length: nTime }, (_, i) => i + 1);

  // Build absorbance matrix [time][wavenumber]
  const matrix = spectra.map((s) => s.absorbance || []);

  return { wavenumbers, timeIndices, matrix, nTime, nWavenumber };
});

// Selected point values
const selectedWavenumber = computed(() => {
  const wn = spectra2D.value.wavenumbers;
  const idx = Math.min(selectedWavenumberIndex.value, wn.length - 1);
  return wn[idx] ?? 0;
});

const selectedAbsorbance = computed(() => {
  const mat = spectra2D.value.matrix;
  const ti = Math.min(selectedTimeIndex.value, mat.length - 1);
  const wi = Math.min(selectedWavenumberIndex.value, (mat[ti]?.length ?? 1) - 1);
  return mat[ti]?.[wi] ?? 0;
});

// Contour plot data
const contourData = computed(() => {
  const { wavenumbers, timeIndices, matrix } = spectra2D.value;
  if (matrix.length === 0 || wavenumbers.length === 0) {
    return [];
  }

  // Main heatmap trace
  const traces: any[] = [
    {
      z: matrix,
      x: wavenumbers,
      y: timeIndices,
      type: "heatmap",
      colorscale: "Viridis",
      hoverongaps: false,
      hovertemplate: "Wavenumber: %{x:.1f} cm⁻¹<br>Time: %{y}<br>Absorbance: %{z:.4f}<extra></extra>",
    },
  ];

  // Only add crosshairs if we have valid data
  if (wavenumbers.length > 0 && timeIndices.length > 0) {
    // Crosshair - vertical line at selected wavenumber
    traces.push({
      x: [selectedWavenumber.value, selectedWavenumber.value],
      y: [timeIndices[0], timeIndices[timeIndices.length - 1]],
      type: "scatter",
      mode: "lines",
      line: { color: "rgba(255,255,255,0.8)", width: 1, dash: "dot" },
      hoverinfo: "skip",
      showlegend: false,
    });

    // Crosshair - horizontal line at selected time
    traces.push({
      x: [wavenumbers[0], wavenumbers[wavenumbers.length - 1]],
      y: [selectedTimeIndex.value + 1, selectedTimeIndex.value + 1],
      type: "scatter",
      mode: "lines",
      line: { color: "rgba(255,255,255,0.8)", width: 1, dash: "dot" },
      hoverinfo: "skip",
      showlegend: false,
    });
  }

  return traces;
});

const contourLayout = computed(() => ({
  title: { text: "", font: { size: 14 } },
  xaxis: {
    title: "Wavenumber (cm⁻¹)",
    autorange: "reversed",
  },
  yaxis: {
    title: "Time Index",
  },
  hovermode: "closest",
  template: "plotly_white",
  height: 400,
  margin: { t: 20, r: 80, l: 60, b: 50 },
}));

// Time slice data (spectrum at selected time)
const timeSliceData = computed(() => {
  const { wavenumbers, matrix } = spectra2D.value;
  if (wavenumbers.length === 0 || matrix.length === 0) return [];

  const ti = Math.min(selectedTimeIndex.value, matrix.length - 1);
  const spectrum = matrix[ti] || [];

  return [
    {
      x: wavenumbers,
      y: spectrum,
      type: "scatter",
      mode: "lines",
      name: `Time ${ti + 1}`,
      line: { color: "#3b82f6", width: 1.5 },
    },
    // Marker at selected wavenumber
    {
      x: [selectedWavenumber.value],
      y: [selectedAbsorbance.value],
      type: "scatter",
      mode: "markers",
      marker: { color: "#ef4444", size: 10, symbol: "circle" },
      hoverinfo: "skip",
      showlegend: false,
    },
  ];
});

const timeSliceLayout = {
  xaxis: { title: "Wavenumber (cm⁻¹)", autorange: "reversed" },
  yaxis: { title: "Absorbance" },
  hovermode: "closest",
  template: "plotly_white",
  height: 250,
  margin: { t: 10, r: 20, l: 50, b: 40 },
  showlegend: false,
};

// Spectral slice data (profile at selected wavenumber)
const spectralSliceData = computed(() => {
  const { timeIndices, matrix } = spectra2D.value;
  if (timeIndices.length === 0 || matrix.length === 0) return [];

  const wi = selectedWavenumberIndex.value;
  const profile = matrix.map((row) => row[wi] ?? 0);

  return [
    {
      x: timeIndices,
      y: profile,
      type: "scatter",
      mode: "lines",
      name: `${selectedWavenumber.value.toFixed(1)} cm⁻¹`,
      line: { color: "#10b981", width: 1.5 },
    },
    // Marker at selected time
    {
      x: [selectedTimeIndex.value + 1],
      y: [selectedAbsorbance.value],
      type: "scatter",
      mode: "markers",
      marker: { color: "#ef4444", size: 10, symbol: "circle" },
      hoverinfo: "skip",
      showlegend: false,
    },
  ];
});

const spectralSliceLayout = {
  xaxis: { title: "Time Index" },
  yaxis: { title: "Absorbance" },
  hovermode: "closest",
  template: "plotly_white",
  height: 250,
  margin: { t: 10, r: 20, l: 50, b: 40 },
  showlegend: false,
};

// 1D plot layout (for non-2D data)
const plotLayout1D = {
  title: { text: "Preprocessed Spectra", font: { size: 14 } },
  xaxis: { title: "Wavenumber (cm⁻¹)", autorange: "reversed" },
  yaxis: { title: "Absorbance" },
  hovermode: "closest",
  template: "plotly_white",
  height: 600,
  margin: { t: 40, r: 20, l: 60, b: 50 },
};

// Handle click on contour plot
const onContourClick = (event: any) => {
  if (!event.points || event.points.length === 0) return;

  const point = event.points[0];
  const clickedWavenumber = point.x;
  const clickedTime = point.y;

  // Find closest wavenumber index
  const wavenumbers = spectra2D.value.wavenumbers;
  let closestWnIdx = 0;
  let minDiff = Math.abs(wavenumbers[0] - clickedWavenumber);
  for (let i = 1; i < wavenumbers.length; i++) {
    const diff = Math.abs(wavenumbers[i] - clickedWavenumber);
    if (diff < minDiff) {
      minDiff = diff;
      closestWnIdx = i;
    }
  }

  selectedWavenumberIndex.value = closestWnIdx;
  selectedTimeIndex.value = Math.max(0, Math.round(clickedTime) - 1);
};

const hasDataSelected = computed(() => {
  return selectedExperimentFiles.value.length > 0 || builderStore.libraryEntries.length > 0;
});

const onExperimentChange = async () => {
  if (!selectedExperiment.value) return;
  try {
    await experimentStore.selectExperiment(selectedExperiment.value.id);
    selectedExperimentFiles.value = [];
  } catch {
    toast.add({
      severity: "error",
      summary: "Error",
      detail: "Failed to load experiment files",
      life: 3000,
    });
  }
};

const runPreprocess = async () => {
  const spectraPayloads = [];

  if (selectedExperiment.value) {
    const expId = String(selectedExperiment.value.id).padStart(3, "0");
    selectedExperimentFiles.value.forEach((file) => {
      spectraPayloads.push({
        label: file.file_path.split("/").pop(),
        file_path: `experiments/exp_${expId}/${file.file_path}`,
        source: file.file_type || "csv",
      });
    });
  }

  builderStore.libraryEntries.forEach((entry) => {
    spectraPayloads.push({
      label: entry.compound_name,
      file_path: entry.file_path,
      source: "jdx",
    });
  });

  try {
    // Update filter direction in settings before preprocessing
    builderStore.settings.filter_direction = filterDirection.value as "wavenumber" | "time";

    await builderStore.preprocessSpectra(spectraPayloads);
    // Reset selection when new data loads
    selectedTimeIndex.value = 0;
    selectedWavenumberIndex.value = Math.floor((spectra2D.value.nWavenumber || 1) / 2);
    toast.add({
      severity: "success",
      summary: "Success",
      detail: `Preprocessed ${spectraPayloads.length} spectra`,
      life: 3000,
    });
  } catch {
    toast.add({
      severity: "error",
      summary: "Preprocessing failed",
      detail: "Unable to preprocess spectra",
      life: 3000,
    });
  }
};

// Initialize selection to middle of data when 2D data changes
watch(
  () => spectra2D.value.nWavenumber,
  (nWn) => {
    if (nWn > 0) {
      selectedWavenumberIndex.value = Math.floor(nWn / 2);
    }
  }
);
</script>

<style scoped>
.preprocess-tab {
  display: flex;
  flex-direction: column;
}

.preprocess-grid {
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
  min-height: 650px;
}

.plot-section-contour {
  min-height: 450px;
}

.slice-plots-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.slice-plot {
  background: #ffffff;
  border-radius: 8px;
  padding: 16px;
  min-height: 300px;
}

.slice-plot h3 {
  margin: 0 0 12px;
  font-size: 0.9rem;
  font-weight: 600;
  color: #334155;
}

.tab-section h3 {
  margin: 0 0 16px;
  font-size: 1rem;
  font-weight: 600;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
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
}

.checkbox-field label {
  margin: 0;
}

.field-hint {
  display: block;
  margin-top: 4px;
  font-size: 0.8rem;
  color: #64748b;
}

.range-inputs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-top: 8px;
}

.library-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.library-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #f8fafc;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

/* File Info Section */
.file-info-section {
  background: linear-gradient(135deg, #f0f9ff, #e0f2fe);
  border: 1px solid #7dd3fc;
}

.file-info-section h3 {
  color: #0369a1;
  border-bottom-color: #7dd3fc;
}

.file-info-grid {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 8px;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 4px;
}

.info-row .info-label {
  font-size: 0.85rem;
  color: #64748b;
}

.info-row .info-value {
  font-weight: 600;
  font-size: 0.85rem;
  color: #0369a1;
  font-family: "SF Mono", "Monaco", monospace;
}

.loading-info {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
  font-size: 0.9rem;
}

.range-warning {
  margin-top: 8px;
  padding: 8px 12px;
  background: #fef3c7;
  border: 1px solid #f59e0b;
  border-radius: 6px;
  color: #92400e;
  font-size: 0.85rem;
  line-height: 1.4;
}

.range-warning i {
  color: #f59e0b;
  margin-right: 4px;
}

.preprocess-button {
  width: 100%;
  margin-top: 8px;
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

/* Slice info panel */
.slice-info {
  background: linear-gradient(135deg, #f8fafc, #f1f5f9);
}

.slice-info h3 {
  border-bottom: none;
  padding-bottom: 0;
  margin-bottom: 12px;
}

.info-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.info-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: white;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}

.info-label {
  font-size: 0.85rem;
  color: #64748b;
}

.info-value {
  font-weight: 600;
  font-size: 0.9rem;
  color: #1e293b;
  font-family: "SF Mono", "Monaco", monospace;
}

@media (max-width: 1200px) {
  .preprocess-grid {
    grid-template-columns: 1fr;
  }

  .slice-plots-row {
    grid-template-columns: 1fr;
  }
}
</style>
