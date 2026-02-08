<template>
  <section class="card builder-view">
    <div class="section-header">
      <div>
        <h1>Spectra Builder</h1>
        <p class="section-subtitle">
          Preprocess raw spectra, sculpt concentration curves, and blend species.
        </p>
      </div>
    </div>

    <TabView v-model:activeIndex="activeTab" class="page-tabs">
      <TabPanel header="Preprocess">
        <div class="stack">
          <div class="panel">
            <h3>Data Source</h3>
            <div class="field">
              <label>Experiment</label>
              <Dropdown
                v-model="selectedExperiment"
                :options="store.experiments"
                optionLabel="name"
                placeholder="Select experiment"
                @change="onExperimentChange"
              />
            </div>
            <div v-if="store.files.length" class="field mt-2">
              <label>Experiment Files</label>
              <MultiSelect
                v-model="selectedExperimentFiles"
                :options="store.files"
                optionLabel="file_path"
                display="chip"
                placeholder="Select files"
              />
            </div>
            <div v-if="builderStore.libraryEntries.length" class="field mt-2">
              <label>Library Entries</label>
              <div class="stack">
                <div
                  v-for="entry in builderStore.libraryEntries"
                  :key="entry.id"
                  class="library-row"
                >
                  <span>{{ entry.compound_name }}</span>
                  <Button
                    icon="pi pi-times"
                    class="p-button-text p-button-danger"
                    @click="builderStore.removeLibraryEntry(entry.id)"
                  />
                </div>
              </div>
            </div>
            <Button
              label="Preprocess"
              icon="pi pi-cog"
              class="mt-3 w-full"
              :loading="builderStore.loading"
              @click="runPreprocess"
            />
          </div>

          <div class="panel">
            <h3>Preprocessing Settings</h3>
            <div class="stack">
              <div class="field">
                <label>Alignment Method</label>
                <Dropdown
                  v-model="builderStore.settings.wavenumber_alignment_method"
                  :options="alignmentOptions"
                />
              </div>
              <div class="field">
                <label>Range Limit</label>
                <div class="inline-toggle">
                  <span>Enable</span>
                  <InputSwitch v-model="builderStore.settings.apply_range_limit" />
                </div>
                <div v-if="builderStore.settings.apply_range_limit" class="form-grid two mt-2">
                  <InputNumber v-model="builderStore.settings.min_wavenumber" placeholder="Min" />
                  <InputNumber v-model="builderStore.settings.max_wavenumber" placeholder="Max" />
                </div>
              </div>
              <div class="field">
                <label>Cosmic Ray Removal</label>
                <InputSwitch v-model="builderStore.settings.apply_cosmic_ray_removal" />
              </div>
              <div class="field">
                <label>Savitzky-Golay</label>
                <InputSwitch v-model="builderStore.settings.apply_savgol" />
              </div>
              <div class="field">
                <label>Clip Floor</label>
                <InputSwitch v-model="builderStore.settings.apply_clip_floor" />
                <InputNumber
                  v-if="builderStore.settings.apply_clip_floor"
                  v-model="builderStore.settings.clip_floor"
                  class="mt-2"
                />
              </div>
            </div>
          </div>
        </div>
      </TabPanel>

      <TabPanel header="Blend">
        <div class="panel">
          <h3>Blending Controls</h3>
          <div v-if="builderStore.spectra.length === 0" class="muted-text">
            Preprocess spectra to activate blending.
          </div>
          <div v-else class="stack">
            <div
              v-for="record in builderStore.spectra"
              :key="record.label"
              class="blend-row"
            >
              <div>
                <strong>{{ record.label }}</strong>
                <div class="muted-text">Weight</div>
              </div>
              <Slider v-model="blendWeights[record.label]" :min="0" :max="1" :step="0.01" />
              <InputNumber
                v-model="blendWeights[record.label]"
                :min="0"
                :max="1"
                :step="0.01"
              />
            </div>
            <div class="field">
              <label>Pathlength (m)</label>
              <InputNumber v-model="pathlength" :min="0" :step="0.1" />
            </div>
            <Button
              label="Blend"
              icon="pi pi-sliders-h"
              class="w-full"
              :loading="builderStore.loading"
              @click="runBlend"
            />
          </div>
        </div>
      </TabPanel>

      <TabPanel header="Curve">
        <div class="panel">
          <h3>Concentration Curve</h3>
          <CurveEditor
            v-if="curvePoints.length"
            v-model:points="curvePoints"
            :samples-per-segment="builderStore.curveSamplesPerSegment"
          />
          <div v-else class="muted-text">Loading curve defaults...</div>
        </div>
      </TabPanel>

      <TabPanel header="Plot">
        <div class="panel plot-panel">
          <div class="section-header">
            <h3>{{ activePlotLabel }}</h3>
            <div class="plot-toggle">
              <Button
                label="Preprocess"
                class="p-button-text"
                :disabled="activePlot === 'preprocess'"
                @click="activePlot = 'preprocess'"
              />
              <Button
                label="Blend"
                class="p-button-text"
                :disabled="activePlot === 'blend'"
                @click="activePlot = 'blend'"
              />
            </div>
          </div>
          <PlotlyChart :data="currentPlotData" :layout="plotLayout" />
        </div>
      </TabPanel>

      <TabPanel header="Export">
        <div class="panel">
          <h3>Export</h3>
          <div class="export-actions">
            <Button
              label="Export Preprocess"
              class="p-button-text"
              @click="exportData('preprocess')"
            />
            <Button label="Export Blend" class="p-button-text" @click="exportData('blend')" />
          </div>
        </div>
      </TabPanel>
    </TabView>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import Button from "primevue/button";
import Dropdown from "primevue/dropdown";
import InputNumber from "primevue/inputnumber";
import InputSwitch from "primevue/inputswitch";
import MultiSelect from "primevue/multiselect";
import Slider from "primevue/slider";
import TabPanel from "primevue/tabpanel";
import TabView from "primevue/tabview";
import { useToast } from "primevue/usetoast";

import { useExperimentStore } from "@/stores/experiment";
import { useBuilderStore } from "@/stores/builder";
import PlotlyChart from "@/components/PlotlyChart.vue";
import CurveEditor from "@/components/CurveEditor.vue";
import { buildSegments, sampleSegments } from "@/utils/curve";
import { downloadCsv, downloadJson } from "@/utils/download";
import type { CurvePoint } from "@/types";

const store = useExperimentStore();
const builderStore = useBuilderStore();
const toast = useToast();

const activeTab = ref(0);
const selectedExperiment = ref<any>(null);
const selectedExperimentFiles = ref<any[]>([]);
const alignmentOptions = ["pchip", "linear", "sinc"];
const blendWeights = reactive<Record<string, number>>({});
const pathlength = ref<number | null>(null);
const curvePoints = ref<CurvePoint[]>([...builderStore.curvePoints]);
const activePlot = ref<"preprocess" | "blend">("preprocess");

const plotLayout = {
  title: { text: "Spectrum Preview" },
  xaxis: { title: { text: "Wavenumber (cm-1)" }, autorange: "reversed" },
  yaxis: { title: { text: "Absorbance" } },
  margin: { t: 40, r: 20, l: 60, b: 40 },
};

const activePlotLabel = computed(() =>
  activePlot.value === "preprocess" ? "Preprocessed Spectra" : "Blend Result"
);

const currentPlotData = computed(() =>
  activePlot.value === "preprocess" ? builderStore.plotTraces : builderStore.blendTraces
);

const refreshBlendWeights = () => {
  builderStore.spectra.forEach((record) => {
    if (blendWeights[record.label] === undefined) {
      blendWeights[record.label] = 0.5;
    }
  });
};

onMounted(async () => {
  try {
    await store.fetchExperiments();
    await builderStore.fetchCurveDefaults();
    curvePoints.value = [...builderStore.curvePoints];
  } catch {
    toast.add({
      severity: "error",
      summary: "Error",
      detail: "Failed to load builder data.",
      life: 3000,
    });
  }
});

watch(
  () => builderStore.spectra,
  () => refreshBlendWeights(),
  { deep: true }
);

watch(
  () => curvePoints.value,
  (next) => {
    builderStore.curvePoints = [...next];
    builderStore.curveSegments = buildSegments(next);
  },
  { deep: true }
);

const onExperimentChange = async () => {
  if (!selectedExperiment.value) {
    return;
  }
  try {
    await store.selectExperiment(selectedExperiment.value.id);
    selectedExperimentFiles.value = [];
  } catch {
    toast.add({
      severity: "error",
      summary: "Error",
      detail: "Failed to load experiment files.",
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

  if (!spectraPayloads.length) {
    toast.add({
      severity: "warn",
      summary: "No spectra",
      detail: "Select files or library entries first.",
      life: 3000,
    });
    return;
  }

  try {
    await builderStore.preprocessSpectra(spectraPayloads);
    activePlot.value = "preprocess";
  } catch {
    toast.add({
      severity: "error",
      summary: "Preprocess failed",
      detail: "Unable to preprocess the selected spectra.",
      life: 3000,
    });
  }
};

const runBlend = async () => {
  if (builderStore.spectra.length === 0) {
    return;
  }
  if (curvePoints.value.length < 2) {
    toast.add({
      severity: "warn",
      summary: "Curve missing",
      detail: "Add at least two curve points before blending.",
      life: 3000,
    });
    return;
  }
  const segments = buildSegments(curvePoints.value);
  const samples = sampleSegments(segments, builderStore.curveSamplesPerSegment);
  const baseCurve = samples.map((point) => point.y);
  const concentrationTimeseries: Record<string, number[]> = {};

  builderStore.spectra.forEach((record) => {
    const weight = blendWeights[record.label] ?? 0;
    concentrationTimeseries[record.label] = baseCurve.map((value) => value * weight);
  });

  const speciesPayloads = builderStore.spectra.map((record) => ({
    ...record,
    model_type: "raw",
  }));

  try {
    await builderStore.blendSpectra(
      speciesPayloads,
      concentrationTimeseries,
      pathlength.value || undefined
    );
    activePlot.value = "blend";
  } catch {
    toast.add({
      severity: "error",
      summary: "Blend failed",
      detail: "Unable to blend spectra with the current settings.",
      life: 3000,
    });
  }
};

const exportData = (mode: "preprocess" | "blend") => {
  if (mode === "preprocess") {
    if (!builderStore.spectra.length) {
      return;
    }
    downloadJson(builderStore.spectra, "preprocessed_spectra.json");
    const rows = [["wavenumber", ...builderStore.spectra.map((s) => s.label)]];
    const length = builderStore.spectra[0]?.wavenumber?.length || 0;
    for (let i = 0; i < length; i += 1) {
      const row = [builderStore.spectra[0].wavenumber?.[i] ?? ""];
      builderStore.spectra.forEach((s) => row.push(s.absorbance?.[i] ?? ""));
      rows.push(row);
    }
    downloadCsv(rows, "preprocessed_spectra.csv");
    return;
  }
  if (!builderStore.blendResult) {
    return;
  }
  downloadJson(builderStore.blendResult, "blend_result.json");
  const rows = [["wavenumber", ...builderStore.blendResult.times.map((t) => `t${t}`)]];
  builderStore.blendResult.wavenumbers.forEach((wn, idx) => {
    const row = [wn, ...builderStore.blendResult!.absorbance_matrix[idx]];
    rows.push(row);
  });
  downloadCsv(rows, "blend_result.csv");
};
</script>

<style scoped>
.builder-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.plot-panel {
  min-height: 600px;
}

.export-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.w-full {
  width: 100%;
}

.mt-2 {
  margin-top: 12px;
}

.mt-3 {
  margin-top: 16px;
}

.library-row,
.blend-row {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 10px;
  align-items: center;
}

.blend-row {
  grid-template-columns: 1fr 120px 90px;
}

.plot-toggle {
  display: flex;
  gap: 6px;
}

.inline-toggle {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
</style>
